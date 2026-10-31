# SPDX-License-Identifier: MIT
"""Offline selector import and owner-reviewed updates; no UI or Hello."""
import copy,hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from axr.aet import AXRError,canonical,digest
from axr_applications import windows_navigation as nav,wechat

def document(account='fixture-self'):
    paths={name:[i] for i,name in enumerate(sorted(nav.PATHS))}
    return {'version':2,'account_id':account,'attribution_prefix':'AI: ','attribution_required':True,
        'profiles':{cid:{'label':label,'visual_binding':{**copy.deepcopy(paths),'executable_hash':'a1'*32,
            'expected_title':label,'search_result_title':label,'expected_identity':cid}}
            for cid,label in ((account,'本人'),('fixture-peer','合成联系人'))}}

class NavigationSchema(unittest.TestCase):
    def setUp(self):
        self.doc=document();self.args={'account':'fixture-self','helper':'fixed-helper','helper_sha':'b2'*32,'endpoint':'fixed-pipe'}
    def test_preparation_copies_metadata_and_supplies_only_fixed_install_assets(self):
        value=nav.prepare(self.doc,**self.args);self.assertEqual(value['helper'],'fixed-helper');self.assertEqual(value['endpoint'],'fixed-pipe')
        self.doc['profiles'].clear();self.assertEqual(len(value['profiles']),2)
        self.assertFalse(nav.review(value)['device_verified']);self.assertFalse(nav.review(value)['authorization_granted'])
    def test_injected_assets_authority_or_wrong_account_are_rejected(self):
        for change in ({'helper':'attacker.exe'},{'endpoint':'remote'},{'resources':[]},{'version':True},{'account_id':'other'}):
            with self.subTest(change=change),self.assertRaises(AXRError):nav.prepare({**self.doc,**change},**self.args)
    def test_non_private_alias_empty_and_unbounded_selector_profiles_are_rejected(self):
        changes=[lambda d:d['profiles'].pop('fixture-peer'),
            lambda d:d['profiles'].__setitem__('filehelper',d['profiles'].pop('fixture-peer')),
            lambda d:d['profiles']['fixture-peer'].__setitem__('label','bad\nheading'),
            lambda d:d['profiles']['fixture-peer']['visual_binding'].__setitem__('expected_identity','other'),
            lambda d:d['profiles']['fixture-peer']['visual_binding'].__setitem__('executable_hash','c3'*32),
            lambda d:d['profiles']['fixture-peer']['visual_binding'].__setitem__('path',[]),
            lambda d:d['profiles']['fixture-peer']['visual_binding'].__setitem__('path',[True]),
            lambda d:d['profiles']['fixture-peer']['visual_binding'].__setitem__('path',[500]),
            lambda d:d['profiles']['fixture-peer']['visual_binding'].__setitem__('path',[1]*17),
            lambda d:d['profiles']['fixture-peer']['visual_binding'].__setitem__('path',d['profiles']['fixture-peer']['visual_binding']['account_path'])]
        for change in changes:
            d=copy.deepcopy(self.doc);change(d)
            with self.subTest(document=d),self.assertRaises(AXRError):nav.prepare(d,**self.args)
    def test_duplicate_members_nonfinite_and_file_budget_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'selectors.json'
            for raw in (b'{"version":2,"version":2}',b'{"value":NaN}',b'[]',b'{"value":'+b' '*40000+b'2}'):
                path.write_bytes(raw)
                with self.assertRaises((AXRError,OSError)):nav.read_json(path)
    def test_review_update_cannot_alter_provider_secrets_account_or_catalog(self):
        old={'account_id':'fixture-self','navigation_helper':'fixed-helper','codex_provider':{'binary':'fixed-cli','sha256':'00'*32,'auth_file':'fixed-auth'}}
        new={**old,'reply_navigation':nav.prepare(self.doc,**self.args)}
        self.assertTrue(nav.build_update(old,new,bundled_path='fixed-cli',identities=self.doc['profiles']))
        for changes in ({'account_id':'other'},{'codex_provider':{**old['codex_provider'],'auth_file':'other'}},{'resources':[]}):
            self.assertFalse(nav.build_update(old,{**new,**changes},bundled_path='fixed-cli',identities=self.doc['profiles']))
        self.assertFalse(nav.build_update(old,new,bundled_path='fixed-cli',identities={'fixture-self'}))
        self.assertFalse(nav.build_update(new,old,bundled_path='fixed-cli',identities=self.doc['profiles']))

@unittest.skipUnless(sys.platform=='win32','Windows stopped navigation import')
class NavigationStaging(unittest.TestCase):
    def setUp(self):
        from scripts import configure_windows_navigation as admin
        self.admin=admin;tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.install=self.root/'install';self.install.mkdir();(self.install/'wechat-uia.exe').write_bytes(b'synthetic non-executable helper')
        self.data=self.root/'data';self.data.mkdir();self.path=self.data/'deployment.json';self.state=self.data/'state'
        self.owner='S-1-5-21-1-2-3-4';self.config={'version':2,'application_module':'axr_applications.wechat','deployment':{
            'owner_user':self.owner,'state':str(self.state),'endpoint':r'\\.\pipe\Stellaria.AXR.fixture',
            'application':{'account_id':'fixture-self','resources':[]}}}
        self.raw=canonical(self.config);self.path.write_bytes(self.raw);self.service=Mock();self.service.status.return_value={'state':'Stopped'}
        for p in (patch.object(admin,'administrator'),patch.object(admin,'protect'),patch.object(admin,'ServiceController',return_value=self.service),
            patch.object(admin.native,'windows_data_root',return_value=str(self.data)),
            patch.object(admin.native,'windows_installation_root',return_value=str(self.install)),patch.object(admin.native,'verify_windows_installation'),
            patch.object(admin.native,'windows_deployment_configuration',return_value=str(self.path))):p.start();self.addCleanup(p.stop)
    def configure(self,**changes):
        return self.admin.configure(document(),changes.get('owner',self.owner),changes.get('sha',hashlib.sha256(self.raw).hexdigest()))
    def test_first_setup_stages_without_key_service_start_or_grant(self):
        value=self.configure();self.assertTrue(value['initialization_required']);self.assertFalse(value['owner_reviewed'])
        self.service.run.assert_not_called();self.assertFalse(self.state.exists())
        app=json.loads(self.path.read_bytes())['deployment']['application'];self.assertEqual(set(app),{'account_id','resources','reply_navigation'})
    def test_running_service_changed_owner_or_digest_cannot_write(self):
        for changes in ({'owner':'other'},{'sha':'00'*32}):
            with self.assertRaises(AXRError):self.configure(**changes)
            self.assertEqual(self.path.read_bytes(),self.raw)
        self.service.status.return_value={'state':'Running'}
        with self.assertRaisesRegex(AXRError,'must_be_stopped'):self.configure()
        self.assertEqual(self.path.read_bytes(),self.raw);self.service.run.assert_not_called()
    def test_existing_config_runs_one_fixed_review_cancellation_never_retries_or_starts(self):
        self.state.mkdir();sealed=self.state/'policy.sealed.json';sealed.write_bytes(b'prior sealed config sentinel')
        self.service.run.side_effect=AXRError('owner_enrollment_recovery_cancelled')
        with self.assertRaisesRegex(AXRError,'cancelled'):self.configure()
        self.service.run.assert_called_once_with('refresh');self.assertEqual(sealed.read_bytes(),b'prior sealed config sentinel')

@unittest.skipUnless(sys.platform=='win32','Windows signed refresh')
class ReviewedNavigationUpdate(unittest.TestCase):
    def test_signed_refresh_seals_only_navigation_after_revoke_and_preserves_ledger(self):
        from test.test_windows_setup_recovery import Recovery
        # Use the existing real synthetic owner/crypto fixture.
        from test.test_windows_attestation import Evidence
        f=Recovery();f.e=Evidence();f.setUp();self.addCleanup(f.doCleanups)
        config=copy.deepcopy(f.config);config['application']['reply_navigation']=nav.prepare(document(config['application']['account_id']),
            account=config['application']['account_id'],helper=config['application']['navigation_helper'],
            helper_sha=hashlib.sha256(Path(config['application']['navigation_helper']).read_bytes()).hexdigest(),endpoint=config['endpoint'])
        approved={**f.approved,'application':{**f.approved['application'],'resources':[
            {'conversation_id':cid} for cid in config['application']['reply_navigation']['profiles']]}}
        store=Mock();store.config.return_value=approved;store.close=lambda:None
        kernel=Mock();kernel.integrity.verify.return_value=True;kernel.db.execute.return_value.fetchone.return_value=None
        registry=SimpleNamespace(rows=['old'],path=f.f.root/'peers');store.vault.seal.return_value=b'fixture'
        pins=Mock();pins.review.return_value=f.build;pins.enroll.side_effect=lambda root,assets,auth:({'build':f.build['build'],'authority_restored':False} if auth() else self.fail('not authenticated'))
        def reviewed(*args):
            kernel.security.revoke.assert_called_once_with('kernel');store.seal_config.assert_not_called()
            return {'expires':time.time()+60}
        import time
        with patch.object(wechat,'resources_root',return_value=f.f.root),patch.object(wechat,'OwnerStore',return_value=store),patch.object(
            wechat,'OwnerDeployment',return_value=pins),patch.object(wechat,'_windows_kernel',return_value=(kernel,registry)),patch.object(
            wechat.native,'HardwareSigningKey',return_value=object()),patch.object(wechat,'_windows_setup_review',side_effect=reviewed),patch.object(
            wechat.native,'durable_write',return_value=True):
            result=wechat.refresh_owner_build(config,{'state':config['state'],'endpoint':config['endpoint'],'owner_public_key':f.key})
        self.assertTrue(result['ledger_retained']);self.assertFalse(result['authority_restored']);self.assertEqual(registry.rows,[])
        sealed=store.seal_config.call_args.args[0];self.assertEqual(sealed['application']['reply_navigation'],config['application']['reply_navigation'])
        self.assertEqual(sealed['owner_public_key'],approved['owner_public_key'])
