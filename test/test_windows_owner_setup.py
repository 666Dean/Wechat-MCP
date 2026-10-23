# SPDX-License-Identifier: MIT
"""Windows setup wiring with synthetic certificates and temporary files only.

No LocalSystem token, interactive process, hardware key or service is created.
Native positive pipe I/O is tested separately by AXRWindowsOwnerSetup.
"""
import io
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from axr import _axr_native as native
from axr.aet import AXRError,canonical,digest
from axr_applications import wechat,windows_enrollment as enrollment
import axr_applications
from test import test_windows_enrollment as fixtures
from test.test_windows_attestation import Evidence,public

OWNER='S-1-5-21-100-200-300-1001'


@unittest.skipUnless(sys.platform=='win32','Windows setup and exclusive pin writes')
class OwnerSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.e=Evidence()
    def setUp(self):
        build=patch.object(wechat,'review_windows_build',return_value={'version':2,'assets':[],'build':'b2'*32});build.start();self.addCleanup(build.stop)
        self.f=fixtures.ExistingOwnerEnrollment();self.addCleanup(self.f.doCleanups);self.f.e=self.e;self.f.setUp()
        self.root=self.f.root
        helper=self.root/'fixture-helper.exe';helper.write_bytes(b'synthetic file; never executed')
        self.config={**self.f.config,'owner_user':OWNER,'application':{**self.f.config['application'],
            'navigation_helper':str(helper),'shards':[]}}
        self.challenge={**self.f.challenge,'configuration_digest':digest(self.config)}
        self.f.write('deployment.json',{'version':2,'application_module':'axr_applications.wechat','deployment':self.config})
        self.identity={'platform':'windows','pid':4242,'birth':'1234567','user':OWNER,
            'image':str(self.root.parent/'axr-owner.exe'),'image_sha256':'a1'*32,'app_container':False,
            'signature_valid':False,'signer_sha256':'','hardened_runtime':False}
    def response(self,challenge):
        return {'version':2,'provider':'WindowsHello/RSA2048','public_key':public(self.e.owner).hex(),
            'challenge':challenge,'signature':self.f.key().sign(canonical(challenge)).hex(),'attestation':self.f.evidence}
    def native_exchange(self,sid,raw):
        self.assertEqual(sid,OWNER)
        return json.dumps({'response':self.response(json.loads(raw)),'identity':self.identity})
    def test_exchange_requires_real_proof_in_addition_to_native_birth_metadata(self):
        with patch.object(native,'exchange_windows_owner_setup',side_effect=self.native_exchange) as exchange:
            response,actual=enrollment.exchange(self.config,self.challenge,self.root)
        self.assertEqual(actual,self.identity);self.assertEqual(response['public_key'],public(self.e.owner).hex())
        exchange.assert_called_once_with(OWNER,canonical(self.challenge).decode())
    def test_changed_user_image_birth_or_proof_cannot_be_registered(self):
        for change in ({'user':'S-1-5-18'},{'image':'wrong.exe'},{'birth':''},{'app_container':True}):
            with self.subTest(change=change),patch.object(native,'exchange_windows_owner_setup',return_value=json.dumps(
                    {'response':self.response(self.challenge),'identity':{**self.identity,**change}})):
                with self.assertRaisesRegex(AXRError,'host_identity_required'):enrollment.exchange(self.config,self.challenge,self.root)
        response=self.response(self.challenge);response['signature']='aa'*256
        with patch.object(native,'exchange_windows_owner_setup',return_value=json.dumps({'response':response,'identity':self.identity})):
            with self.assertRaisesRegex(AXRError,'hardware_enrollment_invalid'):enrollment.exchange(self.config,self.challenge,self.root)
    def test_fixed_owner_entry_uses_native_channel_and_closes_it_on_success(self):
        outputs=[];client=SimpleNamespace(challenge=canonical(self.challenge).decode(),closed=False)
        client.respond=lambda raw:outputs.append(json.loads(raw))
        client.close=lambda:setattr(client,'closed',True)
        with patch.object(native,'security_release',True),patch.object(native,'WindowsOwnerSetupClient',return_value=client),patch.object(
                enrollment,'enrollment_key',return_value=self.f.key()),patch.object(wechat,'resources_root',return_value=self.root):
            result=enrollment.main(self.root)
        self.assertEqual(outputs,[result]);self.assertTrue(client.closed)
    def test_channel_failure_is_closed_without_emitting_evidence(self):
        client=SimpleNamespace(challenge=canonical(self.challenge).decode(),closed=False,respond=lambda raw:self.fail('unexpected response'))
        client.close=lambda:setattr(client,'closed',True)
        with patch.object(native,'security_release',True),patch.object(native,'WindowsOwnerSetupClient',return_value=client),patch.object(
                enrollment,'enrollment_key',side_effect=RuntimeError('fixture unavailable')),patch.object(wechat,'resources_root',return_value=self.root):
            with self.assertRaisesRegex(RuntimeError,'fixture unavailable'):enrollment.main(self.root)
        self.assertTrue(client.closed)
    def test_pin_write_is_exclusive_idempotent_and_cannot_replace_another_key(self):
        path=self.root/'owner-key.json';path.unlink();key=public(self.e.owner).hex()
        enrollment.persist_pin(self.root,key);before=path.read_bytes()
        enrollment.persist_pin(self.root,key);self.assertEqual(path.read_bytes(),before)
        with self.assertRaisesRegex(AXRError,'pin_changed'):enrollment.persist_pin(self.root,public(self.e.aik).hex())
        self.assertEqual(path.read_bytes(),before)
    def test_existing_malformed_pin_is_preserved_for_explicit_recovery(self):
        path=self.root/'owner-key.json';path.write_bytes(b'incomplete setup')
        with self.assertRaises(AXRError):enrollment.persist_pin(self.root,public(self.e.owner).hex())
        self.assertEqual(path.read_bytes(),b'incomplete setup')
    def test_windows_initialization_persists_integrity_before_public_key_pin(self):
        (self.root/'owner-key.json').unlink();events=[];sealed=[];assets=[]
        store=SimpleNamespace(secrets=object(),vault=object(),seal_config=lambda value:sealed.append(value),close=lambda:events.append('store.close'))
        store.journal=SimpleNamespace(verify_audit=lambda:True,checkpoint=SimpleNamespace(read=lambda:{'sequence':0}))
        store.config=lambda:sealed[-1]
        deployment=SimpleNamespace(enroll=lambda root,rows,auth:assets.append((root,rows,auth())))
        kernel=SimpleNamespace(integrity=SimpleNamespace(persist=lambda:events.append('integrity')),close=lambda:events.append('kernel.close'))
        real_pin=enrollment.persist_pin
        def pin(root,key):
            self.assertIn('integrity',events);events.append('pin');real_pin(root,key)
        with patch.object(wechat,'resources_root',return_value=self.root),patch.object(native,'exchange_windows_owner_setup',side_effect=self.native_exchange),patch.object(
                wechat,'OwnerStore',return_value=store),patch.object(wechat,'OwnerDeployment',return_value=deployment),patch.object(
                wechat,'_kernel',return_value=(kernel,object())),patch.object(enrollment,'persist_pin',side_effect=pin),patch.object(
                axr_applications,'_wechat_credentials',SimpleNamespace(WeChatConsumer=lambda *args:object()),create=True),patch.object(
                native.CredentialConsumer,'use',return_value=json.dumps([{'rows':[{'username':'wxid_fixture_contact','remark':'','nick_name':'Fixture'}]}])):
            result=wechat.initialize_owner(self.config,object())
        self.assertEqual(result['owner_public_key'],public(self.e.owner).hex())
        self.assertEqual(sealed[0]['owner_user'],OWNER)
        self.assertEqual(assets[0][0],self.root.parent)
        self.assertEqual(assets[0][1][0]['path'],'axr-authority.exe')
        self.assertEqual(assets[0][1][1]['path'],'axr-owner.exe')
        self.assertLess(events.index('integrity'),events.index('pin'))
        self.assertTrue((self.root/'owner-key.json').exists())
    def test_invalid_setup_identity_never_opens_a_new_ledger(self):
        def changed(sid,raw):return json.dumps({'response':self.response(json.loads(raw)),'identity':{**self.identity,'user':'wrong'}})
        with patch.object(wechat,'resources_root',return_value=self.root),patch.object(native,'exchange_windows_owner_setup',side_effect=changed),patch.object(wechat,'OwnerStore') as store:
            with self.assertRaisesRegex(AXRError,'host_identity_required'):wechat.initialize_owner(self.config,object())
            store.assert_not_called()
    def test_unsupported_windows_legacy_import_does_not_fall_back_to_system_credentials(self):
        store=SimpleNamespace(close=lambda:None,journal=SimpleNamespace(verify_audit=lambda:True,checkpoint=SimpleNamespace(read=lambda:{'sequence':0})))
        with patch.object(wechat,'resources_root',return_value=self.root),patch.object(native,'exchange_windows_owner_setup',side_effect=self.native_exchange),patch.object(
                wechat,'OwnerStore',return_value=store),patch.object(axr_applications,'_wechat_credentials',SimpleNamespace(),create=True),patch.object(enrollment,'persist_pin') as pin:
            with self.assertRaisesRegex(AXRError,'credential_migration_required'):
                wechat.initialize_owner({**self.config,'legacy_namespace':'synthetic-old-owner'},object())
            pin.assert_not_called()
    def test_missing_owner_or_helper_outside_install_is_rejected_before_launch(self):
        with patch.object(native,'exchange_windows_owner_setup') as exchange:
            missing={k:v for k,v in self.config.items() if k!='owner_user'}
            with self.assertRaisesRegex(AXRError,'owner_user_required'):enrollment.exchange(missing,self.challenge,self.root)
            with patch.object(wechat,'resources_root',return_value=self.root):
                for helper in ['outside.exe',str(self.root.parent/'..'/'outside.exe')]:
                    with self.assertRaisesRegex(AXRError,'native_helper_required'):
                        wechat.initialize_owner({**self.config,'application':{**self.config['application'],'navigation_helper':helper}},object())
            exchange.assert_not_called()

    def test_response_to_another_challenge_is_rejected(self):
        other={**self.challenge,'nonce':'ff'*32}
        with patch.object(native,'exchange_windows_owner_setup',return_value=json.dumps({'response':self.response(other),'identity':self.identity})):
            with self.assertRaisesRegex(AXRError,'hardware_enrollment_invalid'):enrollment.exchange(self.config,self.challenge,self.root)

    def test_supplied_enrollment_is_revalidated_before_opening_ledger(self):
        response={**self.response(self.challenge),'identity':{**self.identity,'user':'S-1-5-18'}}
        with patch.object(wechat,'resources_root',return_value=self.root),patch.object(wechat,'OwnerStore') as store:
            with self.assertRaisesRegex(AXRError,'host_identity_required'):wechat.initialize_owner(self.config,object(),response)
            store.assert_not_called()

    def test_windows_interrupted_setup_does_not_use_mac_receipt_recovery(self):
        state=Path(self.config['state']);state.mkdir();(state/'policy.sealed.json').write_bytes(b'synthetic unfinished receipt')
        with patch.object(wechat,'resources_root',return_value=self.root),patch.object(wechat,'OwnerStore') as store:
            with self.assertRaisesRegex(AXRError,'recovery_requires_review'):wechat.resume_owner_setup(self.config)
            store.assert_not_called()

    def test_shared_bootstrap_uses_windows_hardware_hook_and_writes_key_last(self):
        from axr import authority_setup
        writes=[];authenticated={**self.response(self.challenge),'identity':self.identity}
        def missing(name):raise AXRError('owner_secret_not_provisioned')
        backend=SimpleNamespace(get=missing,provision=lambda name,value:writes.append(name))
        def initialize(configuration,signer,enrollment):
            self.assertEqual(enrollment,authenticated)
            return {'state':configuration['state'],'owner_public_key':enrollment['public_key']}
        registration=SimpleNamespace(owner_setup_review=lambda value:{},resume_owner_setup=lambda value:None,
            authenticate_owner_setup=lambda value:authenticated,initialize_owner=initialize)
        with patch.object(native,'security_release',True),patch.object(authority_setup,'AuthoritySecretStore',return_value=backend),patch.object(
                authority_setup.importlib,'import_module',return_value=registration),patch.object(native,'HardwareSigningKey',return_value=SimpleNamespace(public_key=b'synthetic-root')),patch.object(
                authority_setup,'authenticate') as generic,patch.object(wechat,'resources_root',return_value=self.root):
            authority_setup.initialize(self.root)
        generic.assert_not_called()
        self.assertEqual(writes,['root-public-key','configuration','bootstrap-key'])


@unittest.skipUnless(sys.platform=='win32','native bootstrap host checks')
class NativeSetupRefusal(unittest.TestCase):
    def test_normal_python_cannot_query_tokens_or_launch_the_interactive_owner(self):
        challenge={'version':2,'kind':'wechat-owner-enrollment','nonce':'a1'*32,
            'configuration_digest':'b2'*32,'expires':time.time()+60}
        with self.assertRaisesRegex(RuntimeError,'authority_host_required'):
            native.exchange_windows_owner_setup(OWNER,canonical(challenge).decode())
        with self.assertRaisesRegex(RuntimeError,'owner_host_required'):native.WindowsOwnerSetupClient()
    def test_invalid_challenge_is_rejected_before_any_host_or_token_operation(self):
        valid={'version':2,'kind':'wechat-owner-enrollment','nonce':'a1'*32,'configuration_digest':'b2'*32,'expires':time.time()+60}
        for changes in ({'version':True},{'kind':False},{'nonce':'short'},{'expires':0},{'expires':time.time()+1000}):
            with self.assertRaisesRegex(RuntimeError,'challenge_invalid'):
                native.exchange_windows_owner_setup(OWNER,canonical({**valid,**changes}).decode())
