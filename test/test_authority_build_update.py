# SPDX-License-Identifier: MIT
"""Stopped build updates retain history and cannot restore operation grants."""
import json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from axr.aet import AXRError
from axr.deployment import OwnerDeployment
from axr.storage import Vault
from axr_applications import wechat
from test.test_security_authority import ProtectedStore

class BuildUpdate(unittest.TestCase):
    def test_public_build_review_is_read_only_and_changed_assets_need_new_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'host').write_bytes(b'old')
            backend=ProtectedStore();pins=OwnerDeployment(backend,Vault(b'v'*32),development_fixture=True)
            assets=[{'path':'host','roles':['server']}]
            old=pins.review(root,assets);self.assertEqual(backend.values,{})
            (root/'host').write_bytes(b'new')
            self.assertNotEqual(pins.review(root,assets)['build'],old['build'])
    def test_running_endpoint_and_changed_configuration_fail_before_owner_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            config={'state':tmp,'endpoint':str(Path(tmp)/'sock'),'application':{}}
            bootstrap={'state':tmp,'endpoint':config['endpoint'],'owner_public_key':'approved'}
            Path(config['endpoint']).touch()
            with patch.object(wechat,'_configuration',return_value=config),patch.object(wechat,'_hardware_enrollment') as auth:
                with self.assertRaisesRegex(AXRError,'stopped_service'):wechat.refresh_owner_build(config,bootstrap)
                auth.assert_not_called()
            Path(config['endpoint']).unlink()
            store=Mock();store.config.return_value={'application':{'different':'settings'},'owner_user':'u','owner_public_key':'approved'}
            with patch.object(wechat,'_configuration',return_value=config),patch.object(wechat,'OwnerStore',return_value=store), \
                 patch.object(wechat,'process_identity',return_value={'user':'u'}),patch.object(wechat,'_hardware_enrollment') as auth:
                with self.assertRaisesRegex(AXRError,'configuration_changed'):wechat.refresh_owner_build(config,bootstrap)
                auth.assert_not_called()
    def test_different_hardware_owner_cannot_replace_pin_after_revocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'host').write_bytes(b'new build')
            config={'state':tmp,'endpoint':str(root/'sock'),'application':{}}
            bootstrap={'state':tmp,'endpoint':config['endpoint'],'owner_public_key':'approved'}
            store=Mock();store.config.return_value={'application':{},'owner_user':'u','owner_public_key':'approved'}
            kernel=Mock();pins=OwnerDeployment(ProtectedStore(),Vault(b'v'*32),development_fixture=True)
            with patch.object(wechat,'_configuration',return_value=config),patch.object(wechat,'BASE',root), \
                 patch.object(wechat,'OwnerStore',return_value=store),patch.object(wechat,'process_identity',return_value={'user':'u'}), \
                 patch.object(wechat.native,'HardwareSigningKey'),patch.object(wechat,'_kernel',return_value=(kernel,None)), \
                 patch.object(wechat,'OwnerDeployment',return_value=pins),patch.object(wechat,'_build_assets',return_value=[{'path':'host','roles':['server']}]), \
                 patch.object(wechat,'_hardware_enrollment',return_value={'public_key':'foreign','identity':{'user':'u'},'challenge':{'expires':time.time()+60}}):
                with self.assertRaisesRegex(AXRError,'authentication_required'):wechat.refresh_owner_build(config,bootstrap)
            kernel.security.revoke.assert_called_once_with('kernel');kernel.close.assert_called_once()
            self.assertEqual(pins.backend.values,{})
