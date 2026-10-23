# SPDX-License-Identifier: MIT
"""Fresh-setup correction with real rooted temp I/O and no native credentials."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from axr.aet import AXRError,canonical
from axr import authority_reconfigure as entry
from axr_applications import wechat
from scripts import reconfigure_windows as admin
from scripts import install_authority_windows as installer

@unittest.skipUnless(sys.platform=='win32','Windows first-setup correction')
class SourceCorrection(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name).resolve()
        self.runtime=self.root/'runtime';self.runtime.mkdir();self.data=self.root/'data';self.data.mkdir();self.state=self.data/'state'
        self.path=self.data/'deployment.json';self.owner='S-1-5-21-1-2-3-4'
        self.old={'version':2,'application_module':'axr_applications.wechat','deployment':{'owner_user':self.owner,
            'state':str(self.state),'endpoint':r'\\.\pipe\Stellaria.AXR.fixture',
            'credential_import':{'path':str(self.root/'old.key'),'sha256':'a1'*32},
            'application':{'account_id':'fixture-owner','resources':[{'platform':'wechat','account_id':'fixture-owner','conversation_id':'fixture-owner'}]}}}
        self.original=canonical(self.old);self.path.write_bytes(self.original)
        self.source={'credential_import':{'path':str(self.root/'new.key'),'sha256':'b2'*32,'key_mode':'password'}}
        self.request={'version':2,'owner':self.owner,'nonce':'c3'*16,'expected_configuration':hashlib.sha256(self.original).hexdigest(),'source':self.source}
        self.write_request()
        self.backend=Mock();self.backend.get.side_effect=AXRError('owner_secret_not_provisioned')
        for item in (patch.object(entry,'AuthoritySecretStore',return_value=self.backend),
                     patch('axr.deployment_configuration.path',return_value=self.path),patch.object(wechat,'resources_root',return_value=self.runtime)):
            item.start();self.addCleanup(item.stop)
    def write_request(self):(self.data/'setup-source-request.json').write_bytes(canonical(self.request))
    def test_exact_reference_only_roundtrip_preserves_account_assets_and_files(self):
        result=entry.replace_source(self.runtime)
        expected={**self.old,'deployment':{**self.old['deployment'],**self.source}}
        self.assertEqual(json.loads(self.path.read_bytes()),expected)
        self.assertEqual(result,{'source_updated':True,'initialized':False,'authorization_restored':False})
        self.assertEqual(json.loads((self.data/'setup-source-result.json').read_bytes())['nonce'],self.request['nonce'])
        self.assertFalse(self.state.exists());self.assertFalse((self.root/'new.key').exists());self.backend.provision.assert_not_called()
    def test_existing_bootstrap_blocks_before_any_configuration_read(self):
        self.backend.get.side_effect=None;self.backend.get.return_value=b'existing synthetic bootstrap'
        with patch('axr.deployment_configuration.path') as read:
            with self.assertRaisesRegex(AXRError,'already_enrolled'):entry.replace_source(self.runtime)
            read.assert_not_called()
        self.assertEqual(self.path.read_bytes(),self.original)
    def test_missing_secret_is_distinct_from_permission_or_malformed_storage_failure(self):
        self.backend.get.side_effect=AXRError('owner_secret_access_denied')
        with self.assertRaisesRegex(AXRError,'access_denied'):entry.replace_source(self.runtime)
        self.assertEqual(self.path.read_bytes(),self.original)
    def test_approved_receipt_or_even_malformed_public_pin_prevents_correction(self):
        self.state.mkdir()
        for marker in (self.state/'policy.sealed.json',self.runtime/'owner-key.json'):
            marker.write_bytes(b'synthetic malformed existing approval; never replace')
            with self.assertRaisesRegex(AXRError,'already_reviewed'):entry.replace_source(self.runtime)
            self.assertEqual(self.path.read_bytes(),self.original);self.assertTrue(marker.exists());marker.unlink()
    def test_unknown_history_or_failed_protected_audit_is_not_treated_as_empty(self):
        self.state.mkdir();file=self.state/'history';file.write_bytes(b'synthetic prior history')
        with self.assertRaisesRegex(AXRError,'history_present'):entry.replace_source(self.runtime)
        file.unlink();(self.state/'guard.sqlite3').write_bytes(b'fixture shape is mocked only for audit-negative branch')
        store=Mock();store.journal.verify_audit.return_value=False
        with patch('axr.initialization.empty_initialization',return_value=True),patch.object(wechat,'OwnerStore',return_value=store):
            with self.assertRaisesRegex(AXRError,'history_present'):entry.replace_source(self.runtime)
        self.assertEqual(self.path.read_bytes(),self.original);store.seal_config.assert_not_called()
    def test_changed_owner_old_digest_or_replayed_request_cannot_mutate(self):
        for field,value in (('owner','S-1-5-21-5-6-7-8'),('expected_configuration','00'*32),('nonce','wrong')):
            original=self.request[field];self.request[field]=value;self.write_request()
            with self.assertRaisesRegex(AXRError,'request_changed'):entry.replace_source(self.runtime)
            self.assertEqual(self.path.read_bytes(),self.original);self.request[field]=original
        self.write_request();entry.replace_source(self.runtime)
        with self.assertRaisesRegex(AXRError,'request_changed'):entry.replace_source(self.runtime)
    def test_source_cannot_change_state_account_or_introduce_inline_secret(self):
        for source in ({'state':str(self.root/'elsewhere')},{'credential_import':{'path':str(self.root/'key'),'sha256':'a1'*32,'key':'never-accepted'}},
                       {'legacy_namespace':'unrelated-space'},{'credential_import':self.source['credential_import'],'legacy_namespace':'Stellaria.AXR.fixture'}):
            self.request['source']=source;self.write_request()
            with self.assertRaises(AXRError):entry.replace_source(self.runtime)
            self.assertEqual(self.path.read_bytes(),self.original)
    def test_admin_unknown_result_never_retries_or_claims_authority(self):
        service=Mock();service.status.return_value={'state':'Stopped'}
        with patch.object(admin,'administrator'),patch.object(admin,'protect'),patch.object(admin.native,'verify_windows_installation'),patch.object(
                admin.native,'windows_installation_root',return_value=str(self.root/'installed')),patch.object(
                admin.native,'windows_deployment_configuration',return_value=str(self.path)),patch.object(admin,'ServiceController',return_value=service):
            with self.assertRaisesRegex(AXRError,'unknown_no_retry'):admin.correct(self.source,self.owner)
        service.run.assert_called_once_with('reconfigure');self.assertEqual(self.path.read_bytes(),self.original)
    def test_active_fixed_client_blocks_update_before_any_code_or_state_change(self):
        service=Mock();service.status.return_value={'state':'Stopped'}
        with patch.object(installer,'administrator'),patch.object(installer,'review',return_value={}),patch.object(
                installer,'validate_configuration',return_value=(self.runtime,self.data,self.owner)),patch.object(
                installer,'running_fixed_hosts',return_value=[1234]),patch('scripts.windows_service.ServiceController',return_value=service):
            with self.assertRaisesRegex(AXRError,'close_fixed_clients_required'):
                installer.install(self.root,configuration={},local_assets={},replace_stopped=True)
        self.assertEqual(self.path.read_bytes(),self.original);self.assertEqual(list(self.runtime.iterdir()),[])
