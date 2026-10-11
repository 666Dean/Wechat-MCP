# SPDX-License-Identifier: MIT
"""270134 offline object and ownership evidence; contains no callable transport.

These addresses identify analyzed code. They must never be treated as process
pointers, an approved private ABI, or authority to dispatch a message.
"""
import struct
from axr.aet import AXRError

PROFILE = (
    ('message_default_constructor', 0x4d560dc, 0x4d561b8, '60f08ceddaf6a1755ffc51efbf970d854db885b04d4b457725dcaa9d6d8c52f7'),
    ('message_conversion', 0x4cbcbd8, 0x4cbd5f0, '975f97f4f6dfe2f36dffdbfc7d363e5cbad82d875db66f31b7d40ce3b72bd4fc'),
    ('message_copy', 0x393574, 0x393f24, '0cd61a17fe6b056ed02dfbeabcf7bba569ba4eba7b713e793392ca7c517632ad'),
    ('message_destructor', 0x394770, 0x394b90, '812fb41fcf2f70046ed036168f10ad0153e3a217ae29232ab926cc5f8797c14b'),
    ('forward_entry', 0x186f544, 0x186ff40, '152f6bf492aae9b962e5184aedb18a2fd2513a6930565ced6b84abc010236b7e'),
    ('target_insert_candidate', 0x17b4d68, 0x17b5000, 'fb53fabf5361ec9ec07c28bca0eedcd1a4be019a836f485c7cf883aeeb95fe18'),
    ('target_lookup', 0x17b5000, 0x17b51d4, '631d0d1c8be324037a3bd3114c1c961b7d39e012b531d1ef868dfea4fcc50ddc'),
    ('recipient_fanout', 0x418b078, 0x418bafc, '048a5c00262b444087b14031910de296ad438fd95069d09ef064dbe76a890c8a'),
    ('normal_task_factory', 0x4123510, 0x41237c0, '021a4235e8bd859571852b7cfe4b60dc9c7b4805e6d75e7afc1485eff2e1c978'),
    ('task_subscription', 0x186e00c, 0x186e35c, 'c0580d5654b5b68c68cf1b359bed38c8b818359547dee1b47489d31329c4173f'),
    ('subscription_core', 0x2ba25c, 0x2ba4f4, '685f74d79b94585e9cffd71765ec8f9344cfadd0d3794c3d9e7b8a11c462094c'),
    ('app_context_getter', 0x4666bd4, 0x4666be0, 'f60ff16260fb8680732d617c1d67118d1482d68791fc10cbb36add0355d00790'),
    ('account_getter', 0x466dae0, 0x466dbe8, '1895b4dd6eb97d5dc696e32a6b323fb8b0cee69d9e010458361d240c268ff216'),
    ('account_context_getter', 0x466775c, 0x4667778, '96e45da226e1edc3bf2dfb68cbbdda43d6d70b111d8de7424038b8e637cfc8ae'),
    ('login_state_getter', 0x466e3c4, 0x466e3dc, 'eab1df0d033dabb3d98d2a8aa053cd2008def1bd6fa0699514b61ff44d280da5'),
)

# Actual call sites on the ordinary WeChat target branch, not the wxwork branch.
EDGES = (
    (0x186f544, 0x186f698, 0x393574),
    (0x186f544, 0x186f938, 0x17b5000),
    (0x186f544, 0x186f954, 0x418b078),
    (0x186f544, 0x186fa08, 0x4666bd4),
    (0x186f544, 0x186fb24, 0x4123510),
    (0x186f544, 0x186fb34, 0x186e00c),
    (0x186e00c, 0x186e208, 0x2ba25c),
)


def word(image, address):
    return struct.unpack('<I', image.read(address, 4))[0]


def movz_w(value, register):
    # Reject MOVK, shifted immediates, a different destination or 64-bit width.
    if value & 0xffe0001f != 0x52800000 | register:
        raise AXRError('wechat_native_layout_instruction_mismatch')
    return (value >> 5) & 0xffff


def add_x(value, destination, source):
    if value & 0xffc003ff != 0x91000000 | (source << 5) | destination:
        raise AXRError('wechat_native_layout_instruction_mismatch')
    return (value >> 10) & 0xfff


def verify_contract(image):
    for _, start, end, sha in PROFILE:
        if image.function(start) != {'start': start, 'end': end, 'sha256': sha}:
            raise AXRError('wechat_native_object_function_mismatch')
    calls = {start: {(c['site'], c['target']) for c in image.direct_calls(start)}
             for start in {edge[0] for edge in EDGES}}
    if any((site, target) not in calls[start] for start, site, target in EDGES):
        raise AXRError('wechat_native_ownership_chain_mismatch')
    # Decode semantic operands separately from matching whole function bytes.
    size = movz_w(word(image, 0x4cbcc08), 2)
    body = add_x(word(image, 0x4cbcd8c), 0, 19)
    copied_body = add_x(word(image, 0x3936a8), 0, 19)
    shared_allocation = movz_w(word(image, 0x186f670), 0)
    ordinary_target_kind = movz_w(word(image, 0x186f934), 1)
    if (size, body, copied_body, shared_allocation, ordinary_target_kind) != (0x350, 0xb8, 0xb8, 0x368, 2):
        raise AXRError('wechat_native_message_layout_mismatch')
    # Constructor initializes body; destructor accesses the same field.
    checks = {0x4d56144: 0x3902e01f, 0x394b04: 0xf9405e60,
              0x186fb2c: 0xaa1303e8, 0x186e200: 0xaa1403e8,
              0x466db00: 0xf9403509, 0x466db60: 0xf9400d08,
              0x466775c: 0xa946a40a, 0x466e3c4: 0xf9403400}
    if any(word(image, site) != expected for site, expected in checks.items()):
        raise AXRError('wechat_native_lifetime_instruction_mismatch')
    return {'object_functions_verified': len(PROFILE), 'ordinary_branch_edges_verified': len(EDGES),
            'message_object': {'bytes': size, 'body_string_offset': body,
                               'shared_allocation_bytes': shared_allocation},
            'account_code_path_verified': True,
            'native_request_abi_verified': False, 'runtime_recipient_verified': False}
