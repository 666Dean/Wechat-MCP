# SPDX-License-Identifier: MIT
"""Authentication failures never open privileged work or disclose helper text."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from axr.owner import authenticate
    from axr.aet import AXRError
except ModuleNotFoundError as exc:
    if exc.name=='axr':raise unittest.SkipTest('AXR optional dependency') from exc
    raise

class OwnerAuthentication(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.helper=Path(self.temp.name)/'helper';self.helper.touch()
    def tearDown(self):self.temp.cleanup()
    def call(self,result):
        with patch('axr.owner.sys.stdin.isatty',return_value=True),patch('axr.owner.sys.stdout.isatty',return_value=True),\
             patch('axr.owner.Supervisor.invoke',return_value={'result':result}) as invoke:
            authenticate(self.helper)
            self.assertEqual(invoke.call_args.args[1],{'op':'owner_auth'})
    def test_only_unambiguous_boolean_success_is_accepted(self):
        self.call({'verified':True})
        for value in ('true',1,False,None):
            with self.subTest(value=value),self.assertRaisesRegex(AXRError,'owner_os_authentication_failed'):
                self.call({'verified':value})
        with self.assertRaisesRegex(AXRError,'owner_os_authentication_failed'):
            self.call({'verified':True,'error':'owner_auth_denied'})
    def test_system_cancellation_is_distinct_from_timeout(self):
        with self.assertRaisesRegex(AXRError,'owner_auth_denied:os_error_-4'):
            self.call({'verified':False,'error':'owner_auth_denied','os_error_code':-4})
        with self.assertRaisesRegex(AXRError,'owner_auth_timed_out$'):
            self.call({'verified':False,'error':'owner_auth_timed_out'})
    def test_untrusted_descriptions_and_invalid_error_codes_are_not_exposed(self):
        for result in ({'error':'private_secret_text','description':'private_secret_text'},
                       {'error':'owner_auth_denied','os_error_code':'private_secret_text'},
                       {'error':'owner_auth_denied','os_error_code':True},
                       {'error':['private_secret_text']},[],None):
            with self.subTest(result=result),self.assertRaises(AXRError) as failure:self.call(result)
            self.assertNotIn('private_secret_text',str(failure.exception))
            self.assertNotIn('os_error_True',str(failure.exception))
    def test_noninteractive_caller_never_starts_authentication(self):
        with patch('axr.owner.sys.stdin.isatty',return_value=False),patch('axr.owner.Supervisor.invoke') as invoke:
            with self.assertRaisesRegex(AXRError,'owner_interactive_terminal_required'):authenticate(self.helper)
            invoke.assert_not_called()
