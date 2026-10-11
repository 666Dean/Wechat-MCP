# SPDX-License-Identifier: MIT
import hashlib
import os
import plistlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from axr.aet import AXRError
    from axr.native_image import NativeImage
except ModuleNotFoundError as exc:
    if exc.name == 'axr':
        raise unittest.SkipTest('AXR optional: install SDK for native image tests') from exc
    raise

BASE = 0x100000000


def section(name, address, size, offset):
    return struct.pack('<16s16sQQIIIIIIII', name.encode(), b'__TEXT', address, size, offset,
                       2, 0, 0, 0, 0, 0, 0)


def fixture():
    data = bytearray(0x1000)
    segments = struct.pack('<II16sQQQQiiII', 0x19, 232, b'__TEXT', BASE, len(data), 0, len(data), 5, 5, 2, 0)
    segments += section('__text', BASE + 0x200, 0x40, 0x200)
    segments += section('__cstring', BASE + 0x300, 0x40, 0x300)
    commands = segments + struct.pack('<II16s', 0x1b, 24, b'U' * 16) + struct.pack('<IIII', 0x26, 16, 0x380, 0x10)
    data[:32] = struct.pack('<IIIIIIII', 0xfeedfacf, 0x100000c, 0, 6, 3, len(commands), 0, 0)
    data[32:32 + len(commands)] = commands
    # ADRP x8,page ; ADD x3,x8,#0x300 ; BL next-function ; RET.
    struct.pack_into('<IIII', data, 0x200, 0x90000008, 0x91000000 | (0x300 << 10) | (8 << 5) | 3, 0x94000006, 0xd65f03c0)
    data[0x300:0x30c] = b'MMStartTask\0'
    data[0x380:0x384] = b'\x80\x04\x20\0'
    return bytes(data)


def fat(slices, wide=False):
    stride = 32 if wide else 20
    data = bytearray(0x1000 * (len(slices) + 1))
    struct.pack_into('>II', data, 0, 0xcafebabf if wide else 0xcafebabe, len(slices))
    for i, (cpu, value) in enumerate(slices):
        off = 0x1000 * (i + 1)
        args = (cpu, 0, off, len(value), 12, 0) if wide else (cpu, 0, off, len(value), 12)
        struct.pack_into('>IIQQII' if wide else '>IIIII', data, 8 + stride * i, *args)
        data[off:off + len(value)] = value
    return bytes(data)


class NativeImageTests(unittest.TestCase):
    def test_nonzero_vm_base_fat_offsets_and_only_proven_refs(self):
        thin = fixture()
        for data in (thin, fat([(0x1000007, thin), (0x100000c, thin)]), fat([(0x100000c, thin)], True)):
            image = NativeImage(data)
            self.assertEqual(image.starts, (BASE + 0x200, BASE + 0x220))
            self.assertEqual(image.function(BASE + 0x208), {'start': BASE + 0x200, 'end': BASE + 0x220,
                'sha256': hashlib.sha256(thin[0x200:0x220]).hexdigest()})
            self.assertEqual(image.adjacent_string_refs(BASE + 0x200),
                [{'site': BASE + 0x200, 'address': BASE + 0x300, 'text': 'MMStartTask'}])
            self.assertEqual(image.direct_calls(BASE + 0x200),
                [{'site': BASE + 0x208, 'target': BASE + 0x220, 'section': '__text'}])
            self.assertEqual(image.file_sha256, hashlib.sha256(data).hexdigest())
        changed = bytearray(thin)
        struct.pack_into('<I', changed, 0x204, 0x91000000 | (0x300 << 10) | (9 << 5) | 3)
        self.assertEqual(NativeImage(bytes(changed)).adjacent_string_refs(BASE + 0x200), [])

    def test_fat_wrong_arch_ambiguous_overlap_and_out_of_file_rejected(self):
        data = fixture()
        for bad in (fat([(0x1000007, data)]), fat([(0x100000c, data), (0x100000c, data)])):
            with self.assertRaisesRegex(AXRError, 'missing_or_ambiguous'):
                NativeImage(bad)
        bad = bytearray(fat([(0x100000c, data), (0x1000007, data)]))
        struct.pack_into('>I', bad, 8 + 20 + 8, 0x1000)
        with self.assertRaisesRegex(AXRError, 'overlap'):
            NativeImage(bytes(bad))
        for offset, value in ((16, 0xffff0000), (24, 31)):
            bad = bytearray(fat([(0x100000c, data)]))
            struct.pack_into('>I', bad, offset, value)
            with self.assertRaises(AXRError):
                NativeImage(bytes(bad))

    def test_malformed_headers_sections_and_uleb_never_escape(self):
        values = []
        for offset, value in ((16, 9999), (20, 0xfffffff0), (36, 0), (32 + 72 + 48, 0xf000),
                              (32 + 232, 0), (32 + 232 + 24 + 8, 0xfffffff0)):
            data = bytearray(fixture())
            struct.pack_into('<I', data, offset, value)
            values.append(bytes(data))
        for sequence in (b'\x80' * 16, b'\xff\x7f\0', b'\x81\x04\0', b'\x80\0', b'\x80\x04\0\x01'):
            data = bytearray(fixture())
            data[0x380:0x390] = sequence.ljust(16, b'\0')
            values.append(bytes(data))
        values.extend([fixture()[:10], fixture()[:120], b'X' * 32])
        for data in values:
            with self.subTest(header=data[:24]), self.assertRaises(AXRError):
                NativeImage(data)
        image = NativeImage(fixture())
        for address, size in ((BASE + 0x300, 1), (True, 1), (BASE + 0x200, -1), (BASE + 0x23f, 2)):
            with self.assertRaisesRegex(AXRError, 'outside_section'):
                image.read(address, size)
        with self.assertRaisesRegex(AXRError, 'entry_required'):
            image.direct_calls(BASE + 0x204)
        data = bytearray(fixture())
        struct.pack_into('<I', data, 0x208, 0x9400007e)  # into data, not executable text
        with self.assertRaisesRegex(AXRError, 'outside_code'):
            NativeImage(bytes(data)).direct_calls(BASE + 0x200)

    def test_sample_match_cannot_become_send_or_runtime_identity(self):
        from adapters.macos import native_qualification as qualification
        from types import SimpleNamespace
        functions = qualification.FUNCTIONS
        def function(start):
            _, lo, hi, sha = next(item for item in functions if item[1] == start)
            return {'start': lo, 'end': hi, 'sha256': sha}
        def refs(start):
            return [{'text': 'Req2Buf' if start == functions[2][1] else 'MMStartTask'}] * (3 if start == functions[2][1] else 2 if start == functions[0][1] else 1)
        image = SimpleNamespace(uuid=qualification.UUID, file_sha256=qualification.CORE_SHA256,
            function=function, adjacent_string_refs=refs, direct_calls=lambda _: [{'target': functions[1][1]}])
        with patch.object(qualification, 'NativeImage', return_value=image), \
                patch.object(qualification, 'verify_contract', return_value={'native_request_abi_verified': False}):
            result = qualification.qualify_image(b'not-loaded')
            self.assertFalse(result['native_send_available'])
            self.assertFalse(result['runtime_identity_verified'])
            self.assertEqual(result['evidence'], 'offline_layout_and_ownership_only')
            self.assertFalse(result['contract']['native_request_abi_verified'])
            for field in ('uuid', 'file_sha256'):
                original = getattr(image, field)
                setattr(image, field, 'different-image')
                with self.assertRaisesRegex(AXRError, 'sample_mismatch'):
                    qualification.qualify_image(b'not-loaded')
                setattr(image, field, original)
            with patch.object(image, 'function', return_value={'start': 0, 'end': 1, 'sha256': 'bad'}):
                with self.assertRaisesRegex(AXRError, 'function_mismatch'):
                    qualification.qualify_image(b'not-loaded')
            for field in ('adjacent_string_refs', 'direct_calls'):
                with patch.object(image, field, return_value=[]), self.assertRaises(AXRError):
                    qualification.qualify_image(b'not-loaded')

    def test_fixed_bundle_check_redacts_errors_and_denies_links(self):
        from adapters.macos import native_qualification as qualification
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / 'fixture'
            path.write_bytes(b'public-binary-fixture')
            self.assertEqual(qualification.read_regular(path, 32), b'public-binary-fixture')
            with self.assertRaises(AXRError):
                qualification.read_regular(path, 3)
            from types import SimpleNamespace
            before = path.stat()
            fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_nlink')
            changed = SimpleNamespace(**{field: getattr(before, field) for field in fields})
            changed.st_nlink = 2
            with patch.object(qualification.os, 'fstat', side_effect=[before, changed]):
                with self.assertRaisesRegex(AXRError, 'bundle_changed'):
                    qualification.read_regular(path, 32)
            # Reopening must detect path replacement and every metadata field,
            # even when the original descriptor's before/after views agree.
            for field in fields:
                replacement = SimpleNamespace(**{f: getattr(before, f) for f in fields})
                setattr(replacement, field, getattr(before, field) + 1)
                with self.subTest(field=field), \
                        patch.object(qualification.os, 'fstat', side_effect=[before, before, replacement]), \
                        self.assertRaisesRegex(AXRError, 'bundle_changed'):
                    qualification.read_regular(path, 32)
            link = path.with_name('link')
            try:
                link.symlink_to(path)
            except OSError:
                pass  # Some Windows runners lack symlink privilege.
            else:
                with self.assertRaisesRegex(AXRError, 'link_denied'):
                    qualification.read_regular(link, 32)
            other = path.with_name('hardlink')
            os.link(path, other)
            with self.assertRaisesRegex(AXRError, 'file_invalid'):
                qualification.read_regular(other, 32)
        from io import StringIO
        error = StringIO()
        with patch.object(sys, 'argv', ['qualification']), patch.object(sys, 'stderr', error), \
                patch.object(qualification, 'installed_report', side_effect=OSError('private-path-and-identity')):
            with self.assertRaises(SystemExit) as status:
                qualification.main()
            self.assertEqual(status.exception.code, 1)
            self.assertNotIn('private-path', error.getvalue())
        with patch.object(sys, 'argv', ['qualification', '--send']), patch.object(sys, 'stderr', StringIO()):
            with self.assertRaises(SystemExit):
                qualification.main()

    def test_installed_signature_build_and_post_read_identity_are_required(self):
        from adapters.macos import native_qualification as qualification
        signature = b'Identifier=com.tencent.xinWeChat\nTeamIdentifier=5A4RE8SF68\nCDHash=fixture\n'
        info = {'CFBundleIdentifier': 'com.tencent.xinWeChat', 'CFBundleVersion': '270134',
                'CFBundleShortVersionString': '4.1.15'}
        report = {'native_send_available': False}
        with patch.object(sys, 'platform', 'darwin'), patch.object(qualification, 'installed_signature', return_value=signature), \
                patch.object(qualification, 'read_regular', side_effect=[plistlib.dumps(info), b'fixture']) as read, \
                patch.object(qualification, 'qualify_image', return_value=report):
            self.assertTrue(qualification.installed_report()['vendor_signature_verified'])
            self.assertEqual(read.call_args_list[1].args[0].parts[-3:], ('Contents', 'Resources', 'wechat.dylib'))
        bad = dict(info, CFBundleVersion='270133')
        with patch.object(sys, 'platform', 'darwin'), patch.object(qualification, 'installed_signature', return_value=signature), \
                patch.object(qualification, 'read_regular', return_value=plistlib.dumps(bad)) as read:
            with self.assertRaisesRegex(AXRError, 'build_unqualified'):
                qualification.installed_report()
            self.assertEqual(read.call_count, 1)
        with patch.object(sys, 'platform', 'darwin'), \
                patch.object(qualification, 'installed_signature', side_effect=[signature, signature.replace(b'fixture', b'changed')]), \
                patch.object(qualification, 'read_regular', side_effect=[plistlib.dumps(info), b'fixture']), \
                patch.object(qualification, 'qualify_image', return_value=report):
            with self.assertRaisesRegex(AXRError, 'vendor_identity_changed'):
                qualification.installed_report()
        with patch.object(sys, 'platform', 'win32'), patch.object(qualification, 'installed_signature') as verify:
            with self.assertRaisesRegex(AXRError, 'macos_only'):
                qualification.installed_report()
            verify.assert_not_called()
