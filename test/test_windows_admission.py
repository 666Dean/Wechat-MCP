# SPDX-License-Identifier: MIT
"""Real signatures on synthetic evidence, never device/release qualification."""
import copy,hashlib,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from axr.aet import AXRError,canonical,digest
from axr.release import CATEGORIES
from axr_applications import windows_admission as admission,wechat
from test.test_security_authority import FixtureSigner

class EvidenceFixture(unittest.TestCase):
    def setUp(self):
        self.signer=FixtureSigner();self.key_id=hashlib.sha256(self.signer.public_key).hexdigest();self.keys={self.key_id:self.signer.public_key}
        self.expected={'configuration':'a1'*32,'build':'b2'*32,'owner_key':'c3'*32,'navigation':'d4'*32,'os_build':[10,0,99999],'platform':'windows-x64'}
        self.body={'version':2,'product':'wechat-codex-mcp/windows','sequence':1,'subject':copy.deepcopy(self.expected),'created':time.time()-1,'expires':time.time()+100,
            'stage':'software','code_audit':{'complete':False,'record_sha256':'e5'*32},
            'evidence':{c:{'result':'pass','kind':'software','record_sha256':'f6'*32} for c in CATEGORIES}}
    def signed(self,body=None):
        body=copy.deepcopy(self.body if body is None else body)
        return {'body':body,'key_id':self.key_id,'signature':self.signer.sign(canonical(body)).hex()}

class EvidenceVerification(EvidenceFixture):
    def test_valid_software_signature_never_satisfies_device_gate_even_with_all_tests_passed(self):
        result=admission.verify(self.signed(),self.keys,self.expected)
        self.assertTrue(result['material_valid']);self.assertFalse(result['qualified']);self.assertFalse(any(result['checks'].values()))
        self.body['code_audit']['complete']=True
        self.assertFalse(admission.verify(self.signed(),self.keys,self.expected)['qualified'])
    def test_device_statement_requires_complete_code_audit_and_device_records_for_every_category(self):
        self.body['stage']='device'
        for row in self.body['evidence'].values():row['kind']='device'
        self.assertFalse(admission.verify(self.signed(),self.keys,self.expected)['qualified'])
        self.body['code_audit']['complete']=True
        self.assertTrue(admission.verify(self.signed(),self.keys,self.expected)['qualified'])
        for category in CATEGORIES:
            self.body['evidence'][category]['result']='unknown'
            self.assertFalse(admission.verify(self.signed(),self.keys,self.expected)['qualified'])
            self.body['evidence'][category]['result']='pass'
    def test_tampering_unknown_key_self_asserted_trust_and_other_platform_are_rejected(self):
        envelope=self.signed();envelope['body']['code_audit']['complete']=True
        with self.assertRaises(AXRError):admission.verify(envelope,self.keys,self.expected)
        for change in ({'key_id':'00'*32},{'public_key':self.signer.public_key.hex()},{'signature':'00'*70}):
            with self.subTest(change=change),self.assertRaises(AXRError):admission.verify({**self.signed(),**change},self.keys,self.expected)
        self.body['subject']['platform']='darwin'
        with self.assertRaises(AXRError):admission.verify(self.signed(),self.keys,self.expected)
    def test_every_subject_field_is_bound_including_os_build_and_navigation(self):
        for field in self.expected:
            changed={**self.expected,field:'changed'}
            with self.subTest(field=field),self.assertRaises(AXRError):admission.verify(self.signed(),self.keys,changed)
    def test_expired_future_nonfinite_long_lifetime_bool_version_and_missing_category_are_rejected(self):
        for change in ({'expires':time.time()-1},{'created':time.time()+50},{'expires':time.time()+admission.MAX_AGE+10},
            {'version':True},{'sequence':True},{'sequence':0},{'evidence':{}},{'stage':'accepted'}):
            body={**self.body,**change}
            with self.subTest(change=change),self.assertRaises(AXRError):admission.verify(self.signed(body),self.keys,self.expected)
        envelope=self.signed();envelope['body']['expires']=float('inf')
        with self.assertRaises(AXRError):admission.verify(envelope,self.keys,self.expected)
    def test_trust_file_uses_pinned_uncompressed_p256_keys_without_envelope_supplied_roots(self):
        value={'version':2,'keys':{self.key_id:self.signer.public_key.hex()}}
        self.assertEqual(admission.trust_keys(value),self.keys)
        for keys in ({},{'00'*32:self.signer.public_key.hex()},{self.key_id:'04'+'00'*64}):
            with self.assertRaises(AXRError):admission.trust_keys({'version':2,'keys':keys})
    def test_gate_rechecks_expiry_and_host_every_snapshot_and_never_uses_mac_identity_provider(self):
        self.body['stage']='device';self.body['code_audit']['complete']=True
        for row in self.body['evidence'].values():row['kind']='device'
        envelope=self.signed()
        with patch.object(admission,'installed_context',return_value=(self.keys,self.expected)) as context,patch.object(
            admission,'read_json',return_value=envelope),patch.object(admission.native,'windows_data_root',return_value='/synthetic',create=sys.platform!='win32'):
            gate=admission.gate({});self.assertTrue(gate.status()['qualified'])
            envelope['signature']='00'*70;self.assertFalse(gate.status()['qualified']);self.assertEqual(context.call_count,2)
            with self.assertRaisesRegex(AXRError,'not_qualified'):gate.require()
        if sys.platform=='win32':
            with patch.object(admission,'installed_context',side_effect=AXRError('synthetic_missing_trust')):
                self.assertFalse(wechat.release_gate({}).status()['qualified'])
    def test_installed_trust_pin_cannot_be_replaced_or_mutated(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'runtime').mkdir();path=root/'runtime/admission-trust.json'
            path.write_bytes(canonical({'version':2,'keys':{self.key_id:self.signer.public_key.hex()}}))
            app={'admission_trust_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            self.assertEqual(admission.installed_trust(root,app),self.keys)
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(AXRError,'trust_changed'):admission.installed_trust(root,app)
    def test_unsigned_request_contains_no_completed_facts_and_no_private_configuration(self):
        from test.test_windows_navigation_configuration import document
        expected=admission.subject({'application':{'reply_navigation':document(),'private':'never-exported'}},'a1'*32,'public-key',[10,0,99999])
        value=admission.request(expected)
        self.assertNotIn('never-exported',str(value));self.assertNotIn('evidence',value);self.assertFalse(value['authorization_granted'])
        self.assertTrue(value['device_review_required']);self.assertEqual(value['required_categories'],list(CATEGORIES))

@unittest.skipUnless(sys.platform=='win32','Windows bounded admission import')
class MaterialImport(EvidenceFixture):
    def setUp(self):
        super().setUp()
        from scripts import import_windows_admission as admin
        self.admin=admin;tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.path=self.root/'deployment.json';self.owner='S-1-5-21-1-2-3-4'
        self.raw=canonical({'deployment':{'owner_user':self.owner}});self.path.write_bytes(self.raw)
        self.service=Mock();self.service.status.return_value={'state':'Stopped'}
        for p in (patch.object(admin,'administrator'),patch.object(admin,'protect'),patch.object(admin,'ServiceController',return_value=self.service),
            patch.object(admin,'review_context',return_value=(self.keys,self.expected)),patch.object(admin.native,'windows_data_root',return_value=str(self.root)),
            patch.object(admin.native,'windows_deployment_configuration',return_value=str(self.path))):p.start();self.addCleanup(p.stop)
    def import_material(self,envelope=None):
        return self.admin.import_material(self.signed() if envelope is None else envelope,self.owner,hashlib.sha256(self.raw).hexdigest())
    def test_software_import_does_not_start_service_restore_grants_or_modify_configuration(self):
        result=self.import_material();self.assertTrue(result['imported']);self.assertFalse(result['runtime_qualified'])
        self.assertFalse(result['authorization_restored']);self.assertEqual(self.path.read_bytes(),self.raw);self.service.run.assert_not_called()
        self.assertEqual(json.loads((self.root/'windows-admission.json').read_bytes())['body'],self.body)
    def test_replay_is_idempotent_but_rollback_equivocation_or_malformed_prior_material_refuses(self):
        self.body['sequence']=2;self.import_material();self.import_material()
        existing=(self.root/'windows-admission.json').read_bytes();self.body['sequence']=1
        with self.assertRaisesRegex(AXRError,'rollback'):self.import_material()
        self.body['sequence']=2;self.body['code_audit']['complete']=True
        with self.assertRaisesRegex(AXRError,'equivocation'):self.import_material()
        self.assertEqual((self.root/'windows-admission.json').read_bytes(),existing)
        (self.root/'windows-admission.json').write_bytes(b'{}')
        with self.assertRaisesRegex(AXRError,'prior_material_invalid'):self.import_material()
    def test_bad_signature_stale_config_and_running_service_never_write(self):
        envelope=self.signed();envelope['signature']='00'*70
        with self.assertRaises(AXRError):self.import_material(envelope)
        with self.assertRaisesRegex(AXRError,'configuration_changed'):self.admin.import_material(self.signed(),self.owner,'00'*32)
        self.service.status.return_value={'state':'Running'}
        with self.assertRaisesRegex(AXRError,'must_be_stopped'):self.import_material()
        self.assertFalse((self.root/'windows-admission.json').exists())

@unittest.skipUnless(sys.platform=='win32','Windows synthetic installed admission context')
class InstalledContext(EvidenceFixture):
    def setUp(self):
        super().setUp()
        from test.test_windows_navigation_configuration import document
        from axr_applications.windows_navigation import prepare
        from types import SimpleNamespace
        import axr_applications
        from axr import deployment
        from axr_applications import windows_enrollment
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve();runtime=self.root/'runtime';runtime.mkdir()
        (runtime/'provider').mkdir();(runtime/'provider/codex.exe').write_bytes(b'synthetic CLI, never executed');(runtime/'provider/ca-bundle.pem').write_bytes(b'synthetic CA')
        (self.root/'wechat-uia.exe').write_bytes(b'synthetic UIA, never executed')
        trust=runtime/'admission-trust.json';trust.write_bytes(canonical({'version':2,'keys':{self.key_id:self.signer.public_key.hex()}}))
        self.key=(b'k'*294).hex();self.config={'state':str(self.root/'state'),'endpoint':r'\\.\pipe\Stellaria.AXR.fixture','owner_user':'S-1-5-21-1-2-3-4',
            'application':{'account_id':'fixture-self','navigation_helper':str(self.root/'wechat-uia.exe'),'resources':[
                {'conversation_id':'fixture-self'},{'conversation_id':'fixture-peer'}],
                'admission_trust_sha256':hashlib.sha256(trust.read_bytes()).hexdigest(),
                'codex_provider':{'binary':str(runtime/'provider/codex.exe'),'sha256':hashlib.sha256((runtime/'provider/codex.exe').read_bytes()).hexdigest(),
                    'tls_bundle':str(runtime/'provider/ca-bundle.pem'),'tls_sha256':hashlib.sha256((runtime/'provider/ca-bundle.pem').read_bytes()).hexdigest()}}}
        app=self.config['application'];app['reply_navigation']=prepare(document(),account=app['account_id'],helper=self.root/'wechat-uia.exe',
            helper_sha=hashlib.sha256((self.root/'wechat-uia.exe').read_bytes()).hexdigest(),endpoint=self.config['endpoint'])
        self.approved={'application':copy.deepcopy(app),'owner_public_key':self.key,'owner_user':self.config['owner_user']}
        self.anchor={k:self.config[k] for k in ('state','endpoint')};self.anchor['owner_public_key']=self.key
        self.build={'build':'b2'*32,'assets':[]};self.store=Mock();self.store.config.side_effect=lambda:self.approved
        self.pins=Mock();self.pins._load.return_value=self.build;self.pins.verify_process.return_value=True
        self.actual={'platform':'windows','user':'S-1-5-18','app_container':False,'image':str(self.root/'axr-authority.exe')}
        for p in (patch.object(admission.native,'windows_installation_root',return_value=str(self.root)),patch.object(admission.native,'security_release',True),
            patch.object(admission.native,'verify_windows_installation'),patch.object(axr_applications,'_wechat_credentials',SimpleNamespace(import_owner_credentials=lambda:None),create=True),
            patch.object(wechat,'process_identity',side_effect=lambda _:self.actual),patch('axr.deployment_configuration.read',return_value={'application_module':'axr_applications.wechat','deployment':self.config}),
            patch.object(wechat,'_configuration',side_effect=lambda c:c),patch.object(wechat,'OwnerStore',return_value=self.store),
            patch.object(deployment,'OwnerDeployment',return_value=self.pins),patch.object(wechat,'review_windows_build',return_value=self.build),
            patch.object(windows_enrollment,'enrolled_public_key',return_value=bytes.fromhex(self.key))):p.start();self.addCleanup(p.stop)
    def test_minimal_bootstrap_anchors_current_fixed_config_and_signed_mutable_setting_is_independent(self):
        keys,expected=admission.installed_context(self.anchor)
        self.assertEqual(keys,self.keys);self.assertEqual(expected['configuration'],digest(self.config))
        self.approved['application']['manual_approval_required']=False
        self.assertEqual(admission.installed_context(self.anchor)[1],expected)
    def test_wrong_host_owner_pin_build_or_pending_navigation_cannot_reach_a_valid_context(self):
        for changes in ({'user':'S-1-5-21-1-2-3-4'},{'app_container':True},{'image':'wrong.exe'}):
            saved=self.actual.copy();self.actual.update(changes)
            with self.assertRaises(AXRError):admission.installed_context(self.anchor)
            self.actual=saved
        self.pins._load.return_value={'build':'wrong'}
        with self.assertRaises(AXRError):admission.installed_context(self.anchor)
        self.pins._load.return_value=self.build
        self.config['application']['reply_navigation']['attribution_prefix']='changed'
        with self.assertRaisesRegex(AXRError,'configuration_changed'):admission.installed_context(self.anchor)
    def test_cli_hash_changes_and_bootstrap_owner_changes_invalidate_admission(self):
        with self.assertRaisesRegex(AXRError,'owner_changed'):admission.installed_context({**self.anchor,'owner_public_key':'other'})
        (self.root/'runtime/provider/codex.exe').write_bytes(b'mutated synthetic image')
        with self.assertRaisesRegex(AXRError,'provider_changed'):admission.installed_context(self.anchor)
