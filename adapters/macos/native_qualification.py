# SPDX-License-Identifier: MIT
"""Fixed-build offline evidence, not a transport and not an MCP tool.

No process attach, image loading, memory/code patching, database/credential
access, screen capture, account grants, or send calls. No caller-supplied offsets.
"""
import argparse
import json
import os
import plistlib
import stat
import sys
from pathlib import Path
from axr.aet import AXRError
from axr.native_image import NativeImage
from adapters.wcdb_owner import installed_signature, signature_identity
from .native_contract import verify_contract

BUILD = '270134'
UUID = '8acf7a2f-517c-32b4-9dfb-47e8849cd444'
CORE_SHA256 = 'a1709ba62cae1b8b2705137980e23983ed42dc88affe774c4442488b82b007fe'
# These are analyzed task/serialization functions, not a qualified send ABI.
FUNCTIONS = (
    ('task_entry', 0x59708f8, 0x5970a40, 'da67c7339c2fc685e8024314b95eab02f8d255600c764f4d9fc411efd89e2cbd'),
    ('task_manager', 0x597bd60, 0x597be14, '0f677d1a756d6aa0fc88b47f55add6c60f27efff220e1a90d373bb0032ea6c69'),
    ('request_serializer_candidate', 0x597da2c, 0x597dd34, '4b919c3965f608198753f997e0eb0b4f28e3f46f94835f663c0200e2fe8285aa'),
)


def qualify_image(data):
    image = NativeImage(data)
    if image.uuid != UUID or image.file_sha256 != CORE_SHA256:
        raise AXRError('wechat_native_sample_mismatch')
    for _, start, end, sha in FUNCTIONS:
        if image.function(start) != {'start': start, 'end': end, 'sha256': sha}:
            raise AXRError('wechat_native_function_mismatch')
    entry = image.adjacent_string_refs(FUNCTIONS[0][1])
    manager = image.adjacent_string_refs(FUNCTIONS[1][1])
    serializer = image.adjacent_string_refs(FUNCTIONS[2][1])
    if (sum(r['text'] == 'MMStartTask' for r in entry) != 2 or
            sum(r['text'] == 'MMStartTask' for r in manager) != 1 or
            sum(r['text'] == 'Req2Buf' for r in serializer) != 3):
        raise AXRError('wechat_native_anchor_mismatch')
    if not any(c['target'] == FUNCTIONS[1][1] for c in image.direct_calls(FUNCTIONS[0][1])):
        raise AXRError('wechat_native_task_chain_mismatch')
    contract = verify_contract(image)
    return {'build': BUILD, 'architecture': 'arm64', 'sample_identity_verified': True,
            'function_fingerprints_verified': len(FUNCTIONS), 'task_chain_verified': True,
            'contract': contract,
            'evidence': 'offline_layout_and_ownership_only', 'native_send_available': False,
            'runtime_identity_verified': False,
            'remaining': ['wire_request_and_cancellation_contract', 'calling_thread_and_private_abi',
                          'runtime_account_and_exact_private_recipient', 'one_shot_submission_and_record_observation']}


def read_regular(path, maximum):
    """Reject links and concurrent replacement; only caller's fixed bundle files."""
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise AXRError('wechat_native_bundle_link_denied')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 1 <= before.st_size <= maximum:
            raise AXRError('wechat_native_bundle_file_invalid')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(maximum + 1)
        after = os.fstat(descriptor)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_nlink')
        if (len(data) != before.st_size or
                any(getattr(before, f) != getattr(after, f) for f in fields)):
            raise AXRError('wechat_native_bundle_changed')
        # Reopen the exact path while the first handle remains alive. Compare
        # handle snapshots using the same API, not stat/fstat timestamp views
        # that can differ on Windows. All seven identity/change fields remain.
        current_descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            current = os.fstat(current_descriptor)
            if (any(p.is_symlink() for p in (path, *path.parents)) or
                    any(getattr(before, f) != getattr(current, f) for f in fields)):
                raise AXRError('wechat_native_bundle_changed')
        finally:
            os.close(current_descriptor)
        return data
    finally:
        os.close(descriptor)


def installed_report():
    if sys.platform != 'darwin':
        raise AXRError('wechat_installed_native_qualification_macos_only')
    app = Path('/Applications/WeChat.app')
    before = signature_identity(installed_signature(app))
    info = plistlib.loads(read_regular(app / 'Contents/Info.plist', 1024 * 1024))
    if (info.get('CFBundleIdentifier') != 'com.tencent.xinWeChat' or info.get('CFBundleVersion') != BUILD or
            info.get('CFBundleShortVersionString') != '4.1.15'):
        raise AXRError('wechat_native_build_unqualified')
    report = qualify_image(read_regular(app / 'Contents/Resources/wechat.dylib', NativeImage.MAXIMUM_BYTES))
    if signature_identity(installed_signature(app)) != before:
        raise AXRError('wechat_native_vendor_identity_changed')
    return {**report, 'vendor_signature_verified': True}


def main():
    parser = argparse.ArgumentParser(description='Offline fixed-build WeChat native qualification; never sends')
    parser.parse_args()
    try:
        print(json.dumps(installed_report(), sort_keys=True))
    except Exception:
        # No bundle paths, account identifiers or subprocess diagnostics.
        parser.exit(1, 'Native sample qualification failed; sending remains unavailable.\n')


if __name__ == '__main__':
    main()
