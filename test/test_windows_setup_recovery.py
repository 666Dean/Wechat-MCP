# SPDX-License-Identifier: MIT
"""Exact recovery/update challenges with synthetic RSA/attestation, no Hello."""
import io,json,sys,time,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from axr import _axr_native as native
from axr.aet import AXRError,canonical,digest
from axr_applications import wechat,windows_enrollment as enrollment
from test import test_windows_owner_setup as fixtures
from test.test_windows_attestation import Evidence,public
from axr.storage import Vault
from axr.deployment import OwnerDeployment
from test.test_security_authority import ProtectedStore
from test.test_security_authority import FixtureSigner

@unittest.skipUnless(sys.platform=='win32','Windows setup receipt recovery')
class Recovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.e=Evidence()
    def setUp(self):
        self.f=fixtures.OwnerSetup();self.f.e=self.e;self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.key=public(self.e.owner).hex();self.config=self.f.config
        self.approved={'version':2,'application':self.config['application'],'owner_user':self.config['owner_user'],
            'owner_public_key':self.key,'enrollment':'a1'*32}
        self.store=SimpleNamespace(config=lambda:self.approved,close=lambda:None,secrets=object(),vault=object(),
            journal=SimpleNamespace(verify_audit=lambda:True))
        self.build={'version':2,'assets':[],'build':'b2'*32}
        self.deployment=Mock();self.deployment.review.return_value=self.build
    def recover(self,**changes):
        with patch.object(wechat,'resources_root',return_value=self.f.root),patch('axr.initialization.empty_initialization',return_value=True),patch.object(
                wechat,'OwnerStore',return_value=self.store),patch.object(wechat,'OwnerDeployment',return_value=self.deployment),patch.object(
                native,'exchange_windows_owner_setup',side_effect=self.f.native_exchange) as exchange,patch.object(
                native,'HardwareSigningKey',return_value=object()),patch.object(wechat,'finish_initialization') as finish,patch.object(enrollment,'persist_pin') as pin:
            result=wechat._resume_windows_owner_setup({**self.config,**changes})
            return result,exchange,finish,pin
    def test_same_receipt_is_explicitly_reviewed_and_signed_before_finish_and_pin(self):
        result,exchange,finish,pin=self.recover()
        challenge=json.loads(exchange.call_args.args[1]);self.assertEqual(challenge['kind'],'wechat-owner-recovery')
        self.assertEqual(challenge['expected_public_key'],self.key);self.assertEqual(challenge['build_digest'],self.build['build'])
        self.assertEqual(challenge['configuration_digest'],digest(self.config));finish.assert_called_once();pin.assert_called_once_with(self.f.root,self.key)
        self.assertEqual(result['owner_public_key'],self.key)
    def test_changed_configuration_and_owner_cannot_resume_receipt(self):
        for changes in ({'owner_user':'S-1-5-21-1-2-3-4'},{'application':{**self.config['application'],'account_id':'another'}}):
            with self.subTest(changes=changes),self.assertRaisesRegex(AXRError,'approval_changed'):self.recover(**changes)
    def challenge(self,kind='wechat-owner-recovery'):
        return {**self.f.challenge,'kind':kind,'expected_public_key':self.key,'build_digest':self.build['build']}
    def respond(self,challenge):
        with patch.object(wechat,'resources_root',return_value=self.f.root):
            return enrollment.respond(self.f.root,io.BytesIO(canonical(challenge)+b'\n'),lambda value:None)
    def test_cancellation_never_opens_or_creates_an_owner_key(self):
        with patch.object(native,'review_windows_owner',return_value=False),patch.object(native,'WindowsHelloOwnerKey') as key,patch.object(
                native,'provision_windows_hello_owner') as create:
            with self.assertRaisesRegex(AXRError,'recovery_cancelled'):self.respond(self.challenge())
            key.assert_not_called();create.assert_not_called()
    def test_missing_pin_recovery_opens_only_the_receipt_key_and_checks_attestation(self):
        (self.f.root/'owner-key.json').unlink()
        with patch.object(native,'review_windows_owner',return_value=True),patch.object(native,'WindowsHelloOwnerKey',return_value=self.f.f.key()) as key,patch.object(
                native,'provision_windows_hello_owner') as create:
            value=self.respond(self.challenge());self.assertEqual(value['public_key'],self.key)
            key.assert_called_once_with(bytes.fromhex(self.key));create.assert_not_called()
            with self.assertRaisesRegex(AXRError,'pin_required'):self.respond(self.challenge('wechat-owner-build-update'))
            create.assert_not_called()
    def test_malformed_existing_pin_never_falls_back_to_receipt_or_creation(self):
        (self.f.root/'owner-key.json').write_bytes(b'{broken')
        with patch.object(native,'review_windows_owner',return_value=True),patch.object(native,'WindowsHelloOwnerKey') as key,patch.object(
                native,'provision_windows_hello_owner') as create:
            with self.assertRaisesRegex(AXRError,'pin_required'):self.respond(self.challenge())
            key.assert_not_called();create.assert_not_called()
    def test_native_challenge_shape_checks_recovery_fields_before_any_token(self):
        valid=self.challenge()
        for changes in ({'build_digest':'short'},{'expected_public_key':'a1'*65},{'expected_public_key':False},{'kind':'arbitrary'}):
            with self.subTest(changes=changes),self.assertRaisesRegex(RuntimeError,'challenge_invalid'):
                native.exchange_windows_owner_setup(self.config['owner_user'],canonical({**valid,**changes}).decode())
    def test_build_update_revokes_before_review_and_cancellation_never_reenrolls(self):
        self.build_update(cancel=True)
    def test_stopped_build_update_reenrolls_exact_assets_and_clears_only_peer_births(self):
        self.build_update(cancel=False)
    def test_fully_persisted_first_setup_can_publish_bootstrap_without_reinitializing(self):
        self.finalized(previous=False)
    def test_checkpoint_valid_previous_application_state_still_blocks_first_setup_recovery(self):
        self.finalized(previous=True)
    def finalized(self,*,previous):
        from pathlib import Path
        from axr.policy import OwnerStore
        from axr.guard import Guard
        from axr.journal import Journal
        from axr.checkpoint import ProtectedCheckpoint
        from axr.security import SecurityService
        from axr.authority import AuthorityKernel
        area=Path(self.config['state']);area.mkdir()
        store=OwnerStore.__new__(OwnerStore);store.directory=area;store.key=b'g'*32;store.vault=Vault(b'v'*32);store.secrets=ProtectedStore()
        store.guard=Guard(area/'guard.sqlite3',store.key);self.addCleanup(store.guard.close)
        store.journal=Journal(area/'journal.sqlite3',store.vault,checkpoint=ProtectedCheckpoint(store.secrets,store.vault,str(area)));self.addCleanup(store.journal.close)
        store.seal_config(self.approved);store.close=lambda:None
        store.journal.db.execute('CREATE TABLE wechat_state(name TEXT PRIMARY KEY,payload BLOB)')
        security=SecurityService(store,lambda:{},lambda:{},revoke_domain=lambda scope:None)
        kernel=AuthorityKernel(security,FixtureSigner(),bytes.fromhex(self.key),identity=lambda peer:{},environment=lambda peer:{},handler_for=lambda op,r:None,
            development_fixture=True,recovery_verifier=lambda p,s:False,initialize=True,application_tables={'wechat_state':'name'})
        self.addCleanup(kernel.close)
        if previous:
            store.journal.db.execute('INSERT INTO wechat_state VALUES(?,?)',('synthetic-previous',b'fixture'));kernel.integrity.persist()
        self.deployment._load.return_value=self.build
        with patch.object(wechat,'resources_root',return_value=self.f.root),patch.object(wechat,'OwnerStore',return_value=store),patch.object(
                wechat,'OwnerDeployment',return_value=self.deployment),patch.object(native,'exchange_windows_owner_setup',side_effect=self.f.native_exchange) as exchange,patch.object(
                wechat,'finish_initialization') as finish,patch.object(enrollment,'persist_pin') as pin:
            if previous:
                with self.assertRaisesRegex(AXRError,'recovery_requires_review'):wechat._resume_windows_owner_setup(self.config)
                exchange.assert_not_called();pin.assert_not_called()
            else:
                result=wechat._resume_windows_owner_setup(self.config);self.assertEqual(result['owner_public_key'],self.key)
                exchange.assert_called_once();pin.assert_called_once_with(self.f.root,self.key)
            finish.assert_not_called()
    def build_update(self,*,cancel):
        backend=ProtectedStore();vault=Vault(b'v'*32);pins=OwnerDeployment(backend,vault,development_fixture=True)
        store=SimpleNamespace(config=lambda:self.approved,close=lambda:None,secrets=backend,vault=vault,
            journal=SimpleNamespace(security_event=Mock()))
        kernel=Mock();kernel.integrity.verify.return_value=True;kernel.db.execute.return_value.fetchone.return_value=None
        registry=SimpleNamespace(rows=['old-birth'],path=self.f.root/'peer-registry.sealed')
        assets=[{'path':self.f.root.name+'/fixture-helper.exe','roles':['handler']}]
        def reviewed(*args):
            kernel.security.revoke.assert_called_once_with('kernel')
            self.assertEqual(args[3],'wechat-owner-build-update')
            if cancel:raise AXRError('owner_enrollment_recovery_cancelled')
            return {'expires':time.time()+60}
        bootstrap={'state':self.config['state'],'endpoint':self.config['endpoint'],'owner_public_key':self.key}
        with patch.object(wechat,'resources_root',return_value=self.f.root),patch.object(wechat,'OwnerStore',return_value=store),patch.object(
                wechat,'OwnerDeployment',return_value=pins),patch.object(wechat,'_build_assets',return_value=assets),patch.object(
                native,'HardwareSigningKey',return_value=object()),patch.object(wechat,'_windows_kernel',return_value=(kernel,registry)) as factory,patch.object(
                wechat,'_windows_setup_review',side_effect=reviewed):
            if cancel:
                with self.assertRaisesRegex(AXRError,'recovery_cancelled'):wechat.refresh_owner_build(self.config,bootstrap)
                self.assertEqual(backend.values,{});self.assertEqual(registry.rows,['old-birth'])
            else:
                result=wechat.refresh_owner_build(self.config,bootstrap);self.assertTrue(result['updated']);self.assertFalse(result['authority_restored'])
                self.assertEqual(pins._load(),pins.review(self.f.root.parent,assets));self.assertEqual(registry.rows,[])
                self.assertEqual(vault.open(registry.path.read_bytes(),'axr-peer-registry-v2'),[])
                store.journal.security_event.assert_called_once()
            self.assertIs(factory.call_args.kwargs['enroll_current'],False);kernel.close.assert_called_once()
