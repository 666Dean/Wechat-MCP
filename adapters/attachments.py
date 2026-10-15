# SPDX-License-Identifier: MIT
"""Read-only, source-bound local file cache resolution. Never downloads or executes."""
import hashlib
import io
import os
import re
import stat
import time
import zipfile
from pathlib import Path
from axr.aet import AXRError

MAX_FILE = 512 * 1024
MAX_TEXT = 24000


def file_metadata(text):
    """WeChat appmsg type 6 only; no server URLs, attachment keys or arbitrary paths."""
    from defusedxml import ElementTree
    if not isinstance(text, str) or len(text.encode('utf8')) > 1024 * 1024:
        raise AXRError('attachment_metadata_budget')
    try:
        root = ElementTree.fromstring(text)
        app = root if root.tag == 'appmsg' else root.find('appmsg')
        if app is None or app.findtext('type') != '6':
            return None
        filename = app.findtext('title') or ''
        md5 = app.findtext('appattach/md5') or app.findtext('md5') or ''
        size = int(app.findtext('appattach/totallen') or '0')
        if (not filename or len(filename) > 255 or any(ord(c) < 32 for c in filename)
                or '/' in filename or '\\' in filename or filename in {'.', '..'}
                or not re.fullmatch('[0-9a-fA-F]{32}', md5) or not 0 < size <= 2**31):
            raise ValueError()
        from axr_integration.content_safety import mask_credentials
        _,masked=mask_credentials(filename)
        if masked:
            suffix=Path(filename).suffix.lower()
            filename='附件'+(suffix if suffix in {'.txt','.md','.csv','.json','.docx','.pdf'} else '')
        return {'filename': filename, 'md5': md5.lower(), 'size': size,
                'kind': 'file', 'local_content_verified': False}
    except Exception as exc:
        raise AXRError('attachment_metadata_invalid') from exc


def validate_attachment_controls(config):
    if not isinstance(config, dict) or type(config.get('enabled')) is not bool:
        raise AXRError('attachment_control_requires_boolean')
    roots = config.get('cache_roots', [])
    if (not isinstance(roots, list) or len(roots) > 8 or
            any(not isinstance(r, str) or not Path(r).is_absolute() for r in roots)
            or (config['enabled'] and not roots)):
        raise AXRError('explicit_attachment_cache_roots_required')
    return config


def identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def windows_identity(path=None, handle=None):
    """Compare Windows pathname and open handle through the same native API.

    Python's stat/fstat timestamp representations can differ on Windows. Do not
    weaken identity checks or compare fields obtained through different APIs.
    """
    import ctypes
    import msvcrt
    from ctypes import wintypes
    class Info(ctypes.Structure):
        _fields_=[('attributes',wintypes.DWORD),('created',wintypes.FILETIME),
            ('accessed',wintypes.FILETIME),('written',wintypes.FILETIME),
            ('volume',wintypes.DWORD),('size_high',wintypes.DWORD),
            ('size_low',wintypes.DWORD),('links',wintypes.DWORD),
            ('index_high',wintypes.DWORD),('index_low',wintypes.DWORD)]
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
        wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    api.CreateFileW.restype=wintypes.HANDLE
    api.GetFileInformationByHandle.argtypes=[wintypes.HANDLE,ctypes.POINTER(Info)]
    api.GetFileInformationByHandle.restype=wintypes.BOOL
    api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle.restype=wintypes.BOOL
    owned=handle is None
    raw=api.CreateFileW(str(path),0x80,7,None,3,0x00200000,None) if owned else msvcrt.get_osfhandle(handle.fileno())
    if raw==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        info=Info()
        if not api.GetFileInformationByHandle(raw,ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & (0x400|0x10):raise AXRError('attachment_link_or_directory_rejected')
        return (info.volume,info.index_high,info.index_low,info.size_high,info.size_low,
            info.written.dwHighDateTime,info.written.dwLowDateTime,
            info.created.dwHighDateTime,info.created.dwLowDateTime)
    finally:
        if owned:api.CloseHandle(raw)


class AttachmentResolver:
    def __init__(self, config):
        self.config = validate_attachment_controls(config)

    def resolve(self, metadata):
        if not self.config['enabled']:
            raise AXRError('attachment_access_disabled')
        if not 0 < metadata['size'] <= MAX_FILE:
            raise AXRError('attachment_file_budget')
        roots = []
        for name in self.config['cache_roots']:
            root = Path(name)
            if root.is_symlink() or not root.is_dir() or root.resolve() != root:
                raise AXRError('attachment_cache_root_not_canonical')
            roots.append(root)
        matches = []; visited = 0; bytes_read = 0; deadline = time.monotonic()+5
        for root in roots:
            for directory, dirs, files in os.walk(root, followlinks=False):
                visited += 1
                if visited>4096 or time.monotonic()>deadline:raise AXRError('attachment_cache_scan_budget')
                dirs[:] = [d for d in dirs if not (Path(directory)/d).is_symlink()]
                for name in files:
                    visited += 1
                    if visited > 4096 or time.monotonic()>deadline:
                        raise AXRError('attachment_cache_scan_budget')
                    path = Path(directory)/name
                    if path.is_symlink():
                        continue
                    try:
                        s = path.stat()
                        if not stat.S_ISREG(s.st_mode) or s.st_size != metadata['size']:
                            continue
                        bytes_read += s.st_size
                        if bytes_read>32*1024*1024:raise AXRError('attachment_cache_byte_budget')
                        content = self._read(path, root, s)
                    except OSError:
                        continue
                    if hashlib.md5(content).hexdigest() == metadata['md5']:
                        matches.append(content)
        if not matches:
            raise AXRError('attachment_not_cached_or_hash_mismatch')
        if len({hashlib.sha256(x).digest() for x in matches}) != 1:
            raise AXRError('attachment_cache_ambiguous')
        content = matches[0]
        return {'content': content, 'sha256': hashlib.sha256(content).hexdigest(),
                'size': len(content), 'local_content_verified': True}

    @staticmethod
    def _read(path, root, expected):
        # Resolve beneath the canonical cache root and recheck both pathname and
        # original handle. Refuse symlinks at every component, including parents.
        relative = path.relative_to(root)
        for i in range(1, len(relative.parts)+1):
            if root.joinpath(*relative.parts[:i]).is_symlink():
                raise AXRError('attachment_link_rejected')
        if path.resolve(strict=True) != path:
            raise AXRError('attachment_path_changed')
        expected_identity=windows_identity(path=path) if os.name=='nt' else identity(expected)
        current_handle=lambda h:windows_identity(handle=h) if os.name=='nt' else identity(os.fstat(h.fileno()))
        current_path=lambda:windows_identity(path=path) if os.name=='nt' else identity(path.stat())
        with path.open('rb') as handle:
            if current_handle(handle) != expected_identity:
                raise AXRError('attachment_identity_changed')
            data = handle.read(MAX_FILE+1)
            if (len(data) != expected.st_size or len(data) > MAX_FILE or
                    current_handle(handle) != expected_identity or
                    path.is_symlink() or current_path() != expected_identity or
                    path.resolve(strict=True) != path):
                raise AXRError('attachment_identity_changed')
        return data


def extract_text(content, filename):
    """Trusted parser, bounded output; incoming files are data, never commands."""
    if len(content) > MAX_FILE:
        raise AXRError('attachment_file_budget')
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {'.txt', '.md', '.csv', '.json'}:
            value = content.decode('utf-8-sig', errors='strict')
        elif suffix == '.docx':
            from defusedxml import ElementTree
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if (len(entries) > 256 or sum(x.file_size for x in entries) > 8*1024*1024 or
                        any(x.file_size > 2*1024*1024 or x.flag_bits & 1 or
                            x.file_size > max(1, x.compress_size)*100 for x in entries)):
                    raise AXRError('attachment_archive_budget')
                document = archive.read('word/document.xml')
                root = ElementTree.fromstring(document)
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                value = '\n'.join(''.join(p.itertext()) for p in root.iter(ns+'p'))
        elif suffix == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted or len(reader.pages) > 50:
                raise AXRError('attachment_pdf_budget_or_encrypted')
            parts = []; size = 0
            for page in reader.pages:
                part = page.extract_text() or ''
                parts.append(part); size += len(part.encode('utf8'))
                if size > MAX_TEXT:
                    break
            value = '\n'.join(parts)
        else:
            raise AXRError('attachment_format_unsupported')
        encoded = value.encode('utf8')
        return {'text': encoded[:MAX_TEXT].decode('utf8', 'ignore'),
                'truncated': len(encoded) > MAX_TEXT, 'format': suffix[1:]}
    except AXRError:
        raise
    except Exception as exc:
        raise AXRError('attachment_parse_failed') from exc
