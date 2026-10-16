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
        if os.name!='nt':
            # Walk every component relative to held directory descriptors.
            # A parent swapped for a symlink cannot redirect the final open.
            fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
            try:
                for part in root.parts[1:]+relative.parts[:-1]:
                    child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                    os.close(fd);fd=child
                leaf=os.open(relative.parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                handle=os.fdopen(leaf,'rb')
            finally:os.close(fd)
        else:
            from axr.rooted import RootedDirectory
            from axr.windows_files import child,close
            import msvcrt
            directory=RootedDirectory(root)
            try:
                with directory.parent(relative.as_posix()) as (parent,name):
                    native_handle=child(parent,name)
                    try:fd=msvcrt.open_osfhandle(int(native_handle),os.O_RDONLY|os.O_BINARY)
                    except BaseException:close(native_handle);raise
                    handle=os.fdopen(fd,'rb')
            finally:directory.close()
        with handle:
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
    """Compatibility pure-data helper; product consumption uses ContentQuarantine."""
    from axr.quarantine_parser import extract_safe_text,ContentError
    try:return extract_safe_text(content,filename)
    except ContentError as exc:raise AXRError(str(exc)) from None
    except Exception:raise AXRError('attachment_parse_failed') from None
