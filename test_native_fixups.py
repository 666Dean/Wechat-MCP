# SPDX-License-Identifier: MIT
import struct
import unittest
from test_native_image import BASE, NativeImage, AXRError, fixture, fat


def chained_fixture():
    data = bytearray(fixture()) + bytearray(0x1000)
    old_bytes = struct.unpack_from('<I', data, 20)[0]
    segment = struct.pack('<II16sQQQQiiII', 0x19, 72, b'__DATA_CONST',
                          BASE + 0x1000, 0x1000, 0x1000, 0x1000, 3, 3, 0, 0)
    commands = segment + struct.pack('<IIII', 0x80000034, 16, 0x800, 64)
    data[32 + old_bytes:32 + old_bytes + len(commands)] = commands
    struct.pack_into('<II', data, 16, 5, old_bytes + len(commands))
    struct.pack_into('<7I', data, 0x800, 0, 28, 64, 64, 0, 1, 0)
    struct.pack_into('<III', data, 0x81c, 2, 0, 12)
    struct.pack_into('<IHHQIH', data, 0x828, 24, 4096, 6, 0x1000, 0, 1)
    struct.pack_into('<H', data, 0x83e, 0x100)
    struct.pack_into('<QQ', data, 0x1100, 0x200 | (2 << 51), 0x220)
    return bytes(data)


class NativeFixupTests(unittest.TestCase):
    def test_nonzero_base_and_fat_offsets_are_offline_addresses(self):
        thin = chained_fixture()
        for data in (thin, fat([(0x100000c, thin)], True)):
            image = NativeImage(data)
            self.assertEqual(image.chained_rebase(BASE + 0x1100), BASE + 0x200)
            self.assertEqual(image.chained_rebase(BASE + 0x1108), BASE + 0x220)
            self.assertEqual(image.function(image.chained_rebase(BASE + 0x1108))['start'], BASE + 0x220)

    def test_unlisted_word_cannot_masquerade_as_function_pointer(self):
        data = bytearray(chained_fixture())
        struct.pack_into('<Q', data, 0x1120, 0x220)
        for address in (BASE + 0x1120, BASE + 0x200, BASE + 0x1104):
            with self.subTest(address=address), self.assertRaises(AXRError):
                NativeImage(bytes(data)).chained_rebase(address)
        with self.assertRaises(AXRError):
            NativeImage(fixture()).chained_rebase(BASE + 0x200)

    def test_import_tag_reserved_bits_and_unmapped_target_are_rejected(self):
        for value, error in ((1 << 63, 'import_denied'),
                             (0x220 | (0x80 << 36), 'tagged_denied'),
                             (0x220 | (1 << 44), 'chain_invalid'),
                             (0x3000, 'outside_image')):
            data = bytearray(chained_fixture())
            struct.pack_into('<Q', data, 0x1108, value)
            with self.subTest(error=error), self.assertRaisesRegex(AXRError, error):
                NativeImage(bytes(data)).chained_rebase(BASE + 0x1108)

    def test_page_crossing_and_overlapping_chain_are_rejected(self):
        for jump in (1, 0xfff):
            data = bytearray(chained_fixture())
            struct.pack_into('<Q', data, 0x1100, 0x200 | (jump << 51))
            with self.subTest(jump=jump), self.assertRaisesRegex(AXRError, 'chain_invalid'):
                NativeImage(bytes(data)).chained_rebase(BASE + 0x1108)

    def test_malformed_metadata_and_unsupported_formats_fail_closed(self):
        cases = ((0x800, '<I', 1), (0x804, '<I', 0xffffff00),
                 (0x81c, '<I', 0xffffffff), (0x824, '<I', 4),
                 (0x828, '<I', 23), (0x82c, '<H', 8192),
                 (0x82e, '<H', 2), (0x830, '<Q', 0x2000),
                 (0x838, '<I', 1), (0x83c, '<H', 65535),
                 (0x83e, '<H', 0x8000), (0x83e, '<H', 0xffff))
        for at, fmt, value in cases:
            data = bytearray(chained_fixture())
            struct.pack_into(fmt, data, at, value)
            with self.subTest(at=at, value=value), self.assertRaises(AXRError):
                NativeImage(bytes(data)).chained_rebase(BASE + 0x1100)

    def test_invalid_requests_do_not_escape_parser_errors(self):
        image = NativeImage(chained_fixture())
        for address in (True, None, '0x1100', -4, BASE + 0x1101, BASE + 0x2000):
            with self.subTest(address=address), self.assertRaises(AXRError):
                image.chained_rebase(address)


if __name__ == '__main__':
    unittest.main()
