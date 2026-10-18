# SPDX-License-Identifier: MIT
"""Owner UI reports preconditions without retrying or granting authority."""
import subprocess
import unittest
from unittest.mock import patch
from axr.aet import AXRError
from desktop import authority_client


class DesktopAuthorityTests(unittest.TestCase):
    def test_missing_system_permission_is_distinct_from_disconnected_service(self):
        result=subprocess.CompletedProcess([],1,b'',b'{"error_code":"wechat_accessibility_required"}\n')
        with patch.object(authority_client.subprocess,'run',return_value=result) as run:
            with self.assertRaisesRegex(AXRError,'^wechat_accessibility_required$'):
                authority_client.control('start',{'targets':['fixture-peer']})
            self.assertEqual(run.call_count,1)

    def test_native_stderr_content_is_never_shown_as_an_error(self):
        result=subprocess.CompletedProcess([],1,b'',b'{"error_code":"private message or file path"}\n')
        with patch.object(authority_client.subprocess,'run',return_value=result):
            with self.assertRaisesRegex(AXRError,'^independent_authority_control_unavailable$'):
                authority_client.control('snapshot')

    def test_idle_installed_service_is_supported_but_not_ready_or_authorized(self):
        snapshot={'status':{'automatic_reply':False,'reply_count':0,'permissions':{'database':True,'accessibility':False}},'grants':[]}
        with patch.object(authority_client,'control',return_value=snapshot),patch.object(authority_client.sys,'platform','darwin'):
            value=authority_client.call('unused','control.snapshot',owner=True)
        self.assertEqual(value['grants'],[])
        self.assertTrue(value['status']['automatic_reply']['supported'])
        self.assertFalse(value['status']['automatic_reply']['ready'])
        self.assertFalse(value['status']['automatic_reply']['active'])
