# SPDX-License-Identifier: MIT
"""Offline provider refusal and protected-pin routing, with no Hello UI/keys."""
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import tempfile
import unittest
from unittest.mock import patch
from axr import _axr_native as native
from axr.aet import AXRError, canonical
from axr_applications.windows_owner import enrolled_key, control
from test import test_windows_owner_control as fixtures


class EnrolledHelloRouting(unittest.TestCase):
    def test_missing_malformed_or_unbounded_pin_never_opens_provider(self):
        with tempfile.TemporaryDirectory() as root, patch.object(native,'WindowsHelloOwnerKey') as provider:
            with self.assertRaisesRegex(AXRError,'enrolled_key_pin_required'):enrolled_key(root)
            path=Path(root)/'owner-key.json'
            for raw in (b'{}\n',b'{"version":2,"version":2}\n',b'x'*32769,
                        canonical({'version':True,'provider':'WindowsHello/RSA2048','public_key':'aa'*294})+b'\n',
                        canonical({'version':2,'provider':'WindowsHello/RSA2048','public_key':'AA'*294})+b'\n',
                        canonical({'version':2,'provider':'WindowsHello/RSA2048','public_key':'aa'*294,'hardware':True})+b'\n'):
                path.write_bytes(raw)
                with self.assertRaisesRegex(AXRError,'enrolled_key_pin_required'):enrolled_key(root)
            provider.assert_not_called()
    def test_fixed_pin_is_forwarded_exactly_without_creation_options(self):
        with tempfile.TemporaryDirectory() as root, patch.object(native,'WindowsHelloOwnerKey') as provider:
            public=bytes(range(256))+bytes(range(38))
            (Path(root)/'owner-key.json').write_bytes(canonical({'version':2,
                'provider':'WindowsHello/RSA2048','public_key':public.hex()})+b'\n')
            self.assertIs(enrolled_key(root),provider.return_value)
            provider.assert_called_once_with(public)
    def test_missing_provider_never_falls_back_to_background_tpm(self):
        fixture=fixtures.OwnerControl();fixture.setUp();self.addCleanup(fixture.doCleanups)
        source=fixtures.LocalInput(False)
        with patch.object(native,'HardwareSigningKey') as background:
            with self.assertRaisesRegex(AXRError,'enrolled_key_pin_required'):
                control({'endpoint':'fixture','server':{}},source,source.emit,connect=fixture.connect)
            background.assert_not_called()
        self.assertEqual(fixture.f.saved_settings,[])
        self.assertTrue(fixture.channels[0].closed)


@unittest.skipUnless(sys.platform=='win32','Windows native host refusal')
class NativeHelloRefusal(unittest.TestCase):
    def test_first_creation_review_and_deadline_are_bounded_before_os_requests(self):
        for review,expires in (('',time.time()+60),('x'*65537,time.time()+60),('x\0y',time.time()+60),
                              ('review',0),('review',float('inf')),('review',float('nan')),('review',time.time()+1000)):
            with self.assertRaisesRegex(RuntimeError,'hello_enrollment_review_invalid'):
                native.provision_windows_hello_owner(review,expires)
    def test_normal_python_cannot_review_or_create_a_key(self):
        script="import time\nfrom axr import _axr_native as n\ntry:n.provision_windows_hello_owner('synthetic review',time.time()+60)\nexcept RuntimeError as e:\n assert str(e)=='hello_protected_owner_host_required',str(e)\nelse:raise AssertionError('ordinary Python provisioned Hello')"
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
    def test_public_key_pin_is_bounded_before_any_os_request(self):
        for public in (b'',b'a'*293,b'a'*295,b'a'*(1024*1024)):
            with self.assertRaisesRegex(RuntimeError,'hello_enrolled_public_key_required'):
                native.WindowsHelloOwnerKey(public)
    def test_normal_python_cannot_open_even_a_correct_size_pin(self):
        # Child timeout additionally ensures an accidental Hello/UI wait cannot
        # block the suite. No WinRT calls may precede this native host refusal.
        script="from axr import _axr_native as n\ntry:n.WindowsHelloOwnerKey(b'a'*294)\nexcept RuntimeError as e:\n assert str(e)=='hello_protected_owner_host_required',str(e)\nelse:raise AssertionError('ordinary Python opened Hello')"
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
