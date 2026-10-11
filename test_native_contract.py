# SPDX-License-Identifier: MIT
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from adapters.macos import native_contract as contract
from axr.aet import AXRError


def fixture():
    words = {0x4cbcc08: 0x52806a02, 0x4cbcd8c: 0x9102e260,
             0x3936a8: 0x9102e260, 0x186f670: 0x52806d00, 0x186f934: 0x52800041,
             0x4d56144: 0x3902e01f, 0x394b04: 0xf9405e60,
             0x186fb2c: 0xaa1303e8, 0x186e200: 0xaa1403e8,
             0x466db00: 0xf9403509, 0x466db60: 0xf9400d08,
             0x466775c: 0xa946a40a, 0x466e3c4: 0xf9403400}
    def function(address):
        _, start, end, sha = next(p for p in contract.PROFILE if p[1] == address)
        return {'start': start, 'end': end, 'sha256': sha}
    def read(address, size):
        assert size == 4
        return struct.pack('<I', words[address])
    image = SimpleNamespace(function=function, read=read,
        direct_calls=lambda start: [{'site': s, 'target': t} for a, s, t in contract.EDGES if a == start])
    return image, words


class NativeContractTests(unittest.TestCase):
    def test_offline_contract_never_qualifies_dispatch_or_recipient(self):
        image, words = fixture()
        result = contract.verify_contract(image)
        self.assertEqual(result['message_object'], {'bytes': 0x350, 'body_string_offset': 0xb8,
                                                   'shared_allocation_bytes': 0x368})
        self.assertFalse(result['native_request_abi_verified'])
        self.assertFalse(result['runtime_recipient_verified'])
        # A different branch or call site cannot substitute for the ordinary branch.
        with patch.object(image, 'direct_calls', return_value=[]), self.assertRaisesRegex(AXRError, 'ownership_chain'):
            contract.verify_contract(image)
        with patch.object(image, 'function', return_value={}), self.assertRaisesRegex(AXRError, 'object_function'):
            contract.verify_contract(image)

    def test_old_body_size_kind_and_lifetime_are_rejected(self):
        image, words = fixture()
        for site, changed in ((0x4cbcc08, 0x52806802),  # old 0x340 storage
                              (0x4cbcd8c, 0x9102c260),  # old +0xb0 body
                              (0x186f934, 0x52800061),  # other target kind
                              (0x394b04, 0xf9405a60)):  # destructor reads different field
            with self.subTest(site=site):
                original = words[site]
                words[site] = changed
                with self.assertRaises(AXRError):
                    contract.verify_contract(image)
                words[site] = original

    def test_immediate_decoders_reject_wrong_width_register_shift_and_opcode(self):
        for value in (0xd2806a02, 0x52806a01, 0x52a06a02, 0x72806a02):
            with self.assertRaises(AXRError):
                contract.movz_w(value, 2)
        for value in (0x9142e260, 0x9102e261, 0x9102e240, 0x1102e260):
            with self.assertRaises(AXRError):
                contract.add_x(value, 0, 19)


if __name__ == '__main__':
    unittest.main()
