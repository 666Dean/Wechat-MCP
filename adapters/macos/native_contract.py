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

# Execution closures and the outgoing Message are not the final wire request.
PIPELINE = (
    ('task_closure_execute', 0x414ecf0, 0x414f0c8, 'cf68d2972522d8b3f0f8d9613aee939d4bfdefc28dd57b12e9ddddc2cd413eef'),
    ('owned_callback_execute', 0x414f258, 0x414f5dc, 'e54bc2b2990edbf850798366bf1ffa44ae28c5f407bb4de57e08dae1973093d8'),
    ('owned_callback_release', 0x414f22c, 0x414f258, '1d7d51cb8f940ce079213a2c73c18bc14784a725a520a915c578446bca833d82'),
    ('session_shared_getter', 0x46681d4, 0x46681f4, '55c3556b46bad272d477672743cc684172630b7dd6b7c881cff14d19a27a1851'),
    ('session_dispatch', 0x453a2d0, 0x453a5fc, 'ca21815d3890b635668bc99a21b742955f73237341d53925389cebda940af66c'),
    ('session_dispatch_core', 0x45397f4, 0x4539ab8, '63e510b1dccd57ca73eed2a41a8a0b44ae9f5ab701ed5bc2397f239b75793cc0'),
    ('send_service', 0x317ba00, 0x317c654, '5874acdac47b11149349137dd0533ad58343e95765f106c6bb164ca0f905b224'),
    ('single_item_submit', 0x317b554, 0x317b774, '8fea989096257e680fd0e0dcb8d2b4fe67ba6776b4ffff0a0373d4cbe44f05f4'),
    ('queue_item_constructor', 0x30ecfd0, 0x30ed2d4, 'ec8cd4744c16edc05a07c5d91bc6c83196c2a8f7af9208d71b5223ab3576aabb'),
    ('queue_item_constructor_thunk', 0x30ef24c, 0x30ef250, '164e9ffe47b0d019ab7082965ab79d81b1899dffb0a4cf265e5b1705b10679e2'),
    ('outgoing_message_builder', 0x30ed2d4, 0x30ef24c, 'a6a0d81596279b38699dff50ab3c4b0909675eae6e5f9310f5e395abe196f3c5'),
    ('outgoing_message_constructor', 0xac4188, 0xac43e0, '96f8099edde6b7e2b9464b0346e27fc61b192079dea4402b00f989b8e4035fda'),
    ('outgoing_body_setter', 0x4cb86d0, 0x4cb8c30, 'd3365a2f0d283c276ac3dc7e58c99ade63e5c43e774adb28b2d91e283f5f0673'),
    ('queue_payload_release', 0x2ebc708, 0x2ebc714, '4caa9087dcdcb8911b760f0ede6682d0ee58d671e06fe2de2efe90b3430ab0ea'),
    ('queue_item_destructor_thunk', 0x30f1644, 0x30f1648, '75afa1436b2cd1accd6f9713466e78e7033fc94974968ddba7cfe0b3c4f2fe72'),
    ('queue_item_destructor', 0x30f0ae8, 0x30f0d3c, 'a48b9e5c6ed5f034b8951fdac566ee29abb70a083c15df78241f500a6861c79d'),
)

REBASE_EDGES = (
    (0x9e5aa10, 0x414ecf0),
    (0x9e5aa80, 0x414f258),
    (0x9e5aa78, 0x414f22c),
    (0x9dd6ba8, 0x2ebc708),
    (0x9de5528, 0x30f1644),
    (0x9e8e428, 0x466dae0),
    (0x9e8e468, 0x466775c),
    (0x9e8e470, 0x466e3c4),
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
    (0x414ecf0, 0x414ed2c, 0x46681d4),
    (0x414ecf0, 0x414ef3c, 0x453a2d0),
    (0x453a2d0, 0x453a52c, 0x45397f4),
    (0x414f258, 0x414f318, 0x317ba00),
    (0x317ba00, 0x317bb60, 0x317b554),
    (0x317b554, 0x317b5d4, 0x30ef24c),
    (0x30ecfd0, 0x30ed09c, 0x30ed2d4),
    (0x30ed2d4, 0x30ed368, 0xac4188),
    (0x30ed2d4, 0x30ed3b0, 0x4cb86d0),
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
    for _, start, end, sha in PROFILE + PIPELINE:
        if image.function(start) != {'start': start, 'end': end, 'sha256': sha}:
            raise AXRError('wechat_native_object_function_mismatch')
    calls = {start: {(c['site'], c['target']) for c in image.direct_calls(start)}
             for start in {edge[0] for edge in EDGES}}
    if any((site, target) not in calls[start] for start, site, target in EDGES):
        raise AXRError('wechat_native_ownership_chain_mismatch')
    if any(image.chained_rebase(site) != target for site, target in REBASE_EDGES):
        raise AXRError('wechat_native_vtable_chain_mismatch')
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
    # These are separate native objects. The outgoing Message still is not the
    # network request; sender selection and serialization remain downstream.
    layout = (movz_w(word(image, 0x414ee8c), 0),
              movz_w(word(image, 0x317b588), 0),
              add_x(word(image, 0x317b5ac), 22, 0),
              movz_w(word(image, 0x30ed338), 0),
              add_x(word(image, 0x30ed354), 22, 0),
              movz_w(word(image, 0x30ed35c), 1),
              add_x(word(image, 0x30ed384), 0, 23),
              add_x(word(image, 0x30ed390), 0, 23),
              add_x(word(image, 0x4cb8778), 0, 19),
              add_x(word(image, 0x418b3dc), 0, 8),
              add_x(word(image, 0x418b3e0), 1, 23),
              add_x(word(image, 0x30ed38c), 21, 27))
    if layout != (0xa8, 0xf8, 0x18, 0x290, 0x18, 0x278, 0x30, 0x48, 0x48, 0x90, 0x20, 0x90):
        raise AXRError('wechat_native_pipeline_layout_mismatch')
    # Verified tail calls: the constructor thunk and queued-payload destructor
    # cannot be substituted with unrelated same-sized functions.
    if word(image, 0x30ef24c) != 0x17fff761 or word(image, 0x30f1644) != 0x17fffd29:
        raise AXRError('wechat_native_pipeline_tail_mismatch')
    return {'object_functions_verified': len(PROFILE), 'ordinary_branch_edges_verified': 7,
            'pipeline_direct_edges_verified': len(EDGES) - 7,
            'pipeline_functions_verified': len(PIPELINE), 'chained_vtable_edges_verified': len(REBASE_EDGES),
            'message_object': {'bytes': size, 'body_string_offset': body,
                               'shared_allocation_bytes': shared_allocation},
            'pipeline_objects': {'owned_callback_bytes': layout[0], 'queued_item_allocation_bytes': layout[1],
                'outgoing_message_bytes': layout[5], 'outgoing_message_allocation_bytes': layout[3],
                'from_string_offset': layout[6] - layout[4], 'target_string_offset': layout[7] - layout[4],
                'body_string_offset': layout[8], 'recipient_code_flow_verified': True,
                'final_wire_request_verified': False, 'thread_and_cancellation_verified': False},
            'account_code_path_verified': True,
            'native_request_abi_verified': False, 'runtime_recipient_verified': False}
