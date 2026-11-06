# SPDX-License-Identifier: MIT
"""Bounded advisory errors; synthetic files only, never starts a real service."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from scripts.windows_service import ServiceController


@unittest.skipUnless(sys.platform == 'win32', 'Windows service result reader')
class ServiceDiagnostics(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        self.path = self.root / 'service-last-result.json'
        root = patch('scripts.windows_service.native.windows_data_root', return_value=str(self.root))
        root.start()
        self.addCleanup(root.stop)
        clock = patch('scripts.windows_service.time.time', return_value=200.0)
        clock.start()
        self.addCleanup(clock.stop)
        self.controller = ServiceController()
        self.record = {'version': 2, 'operation': 'initialize', 'result': 'Failed',
            'error_code': 'windows_owner_setup_launch_failed', 'finished': 150.0, 'pid': 42}

    def read(self, **changes):
        self.path.write_text(json.dumps({**self.record, **changes}), encoding='utf-8')
        return self.controller._last_error('initialize', 100.0)

    def test_current_failed_mode_returns_only_the_bounded_machine_code(self):
        self.assertEqual(self.read(), 'windows_owner_setup_launch_failed')
        for code in ('protected_store_access_denied', 'credential_import_failed',
                'hardware_signing_failed', 'integrity_check_failed',
                'identity_token_unavailable', 'ipc_peer_unavailable', 'hello_provider_unavailable'):
            with self.subTest(code=code):
                self.assertEqual(self.read(error_code=code), code)

    def test_success_stale_other_mode_and_invalid_process_cannot_explain_this_failure(self):
        for changes in ({'result': 'Completed'}, {'operation': 'refresh'}, {'finished': 99.0},
                {'finished': 201.0}, {'finished': float('nan')}, {'finished': True}, {'pid': 0},
                {'pid': True}, {'pid': 2**32}, {'version': True}, {'private': 'must not return'}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.read(**changes))

    def test_paths_message_text_hex_keys_and_oversized_codes_are_never_returned(self):
        for value in ('C:\\private\\credential.key', 'private message', 'ab' * 32,
                'wxid_private_account', 'windows_error\nprivate', 'owner_' + 'a' * 100):
            with self.subTest(value=value):
                self.assertIsNone(self.read(error_code=value))

    def test_missing_malformed_or_over_budget_file_has_no_diagnostic(self):
        self.assertIsNone(self.controller._last_error('initialize', 100.0))
        for raw in (b'{', b'[]', b'x' * 4097):
            self.path.write_bytes(raw)
            self.assertIsNone(self.controller._last_error('initialize', 100.0))
