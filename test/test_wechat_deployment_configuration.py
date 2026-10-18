# SPDX-License-Identifier: MIT
"""Platform configuration and asset containment, without setup or credentials."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from axr.aet import AXRError
from axr_applications import wechat


class DeploymentConfiguration(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.resources=self.root/'runtime';self.resources.mkdir()
        (self.resources/'helper').write_bytes(b'synthetic helper, never executed')
        self.config={'state':str(self.root/'state'),
            'endpoint':r'\\.\pipe\Stellaria.AXR.fixture' if os.name=='nt' else '/tmp/axr-fixture.sock',
            'application':{'account_id':'fixture-self','navigation_helper':'@resources/helper',
                'resources':[{'platform':'wechat','account_id':'fixture-self','conversation_id':'fixture-peer'}]}}
        replacement=patch.object(wechat,'resources_root',return_value=self.resources)
        replacement.start();self.addCleanup(replacement.stop)
    def test_resolves_bundled_helper_and_preserves_platform_endpoint_without_initializing(self):
        result=wechat._configuration(self.config)
        self.assertEqual(result['endpoint'],self.config['endpoint'])
        self.assertEqual(result['application']['navigation_helper'],str(self.resources/'helper'))
        self.assertFalse((self.root/'state').exists())
    def test_relative_state_traversal_duplicate_resource_and_wrong_account_are_rejected(self):
        with self.assertRaisesRegex(AXRError,'state_invalid'):
            wechat._configuration({**self.config,'state':'relative-state'})
        for name in ('@resources/../helper','@resources//helper','@resources/folder\\helper'):
            with self.subTest(name=name),self.assertRaises(AXRError):
                wechat._configuration({**self.config,'application':{**self.config['application'],'navigation_helper':name}})
        app=self.config['application']
        with self.assertRaisesRegex(AXRError,'resource_mismatch'):
            wechat._configuration({**self.config,'application':{**app,'resources':app['resources']*2}})
        with self.assertRaisesRegex(AXRError,'resource_mismatch'):
            wechat._configuration({**self.config,'application':{**app,'account_id':'other'}})
    def test_reply_helper_and_endpoint_must_match_the_owner_deployment(self):
        app=self.config['application']
        navigation={'helper':'@resources/helper','endpoint':self.config['endpoint']}
        value={**self.config,'application':{**app,'reply_navigation':navigation}}
        self.assertEqual(wechat._configuration(value)['application']['reply_navigation']['helper'],str(self.resources/'helper'))
        for changes in ({'endpoint':'untrusted'},{'helper':'untrusted'}):
            with self.subTest(changes=changes),self.assertRaisesRegex(AXRError,'navigation_mismatch'):
                wechat._configuration({**value,'application':{**value['application'],'reply_navigation':{**navigation,**changes}}})
    @unittest.skipUnless(os.name=='nt','Windows named pipe configuration')
    def test_network_pipe_arbitrary_name_and_path_endpoint_are_rejected(self):
        for endpoint in (r'\\remote\pipe\Stellaria.AXR.fixture',r'\\.\pipe\other',str(self.root/'socket')):
            with self.subTest(endpoint=endpoint),self.assertRaisesRegex(AXRError,'endpoint_invalid'):
                wechat._configuration({**self.config,'endpoint':endpoint})
