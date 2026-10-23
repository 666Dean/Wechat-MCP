# SPDX-License-Identifier: MIT
"""Explicit orphaned-key setup, using only temporary software certificates."""
import io,json,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
from axr import _axr_native as native
from axr.aet import AXRError,canonical
from axr_applications import wechat,windows_enrollment as enrollment
from test import test_windows_owner_setup as fixtures
from test.test_windows_attestation import Evidence,public

@unittest.skipUnless(sys.platform=='win32','Windows explicit orphan recovery')
class OrphanRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.e=Evidence()
    def setUp(self):
        self.f=fixtures.OwnerSetup();self.addCleanup(self.f.doCleanups);self.f.e=self.e;self.f.setUp()
        self.root=self.f.root;self.pin=self.root/'owner-key.json';self.pin.unlink()
        self.challenge={**self.f.challenge,'kind':'wechat-owner-orphan-recovery','build_digest':'b2'*32}
    def respond(self):return enrollment.respond(self.root,io.BytesIO(canonical(self.challenge)+b'\n'),lambda value:None)
    def test_explicit_flow_only_opens_existing_key_then_verifies_hardware_and_signature(self):
        with patch.object(native,'recover_windows_hello_owner',return_value=self.f.f.key()) as recover,patch.object(native,'provision_windows_hello_owner') as create,patch.object(
                enrollment,'enrolled_key') as enrolled:
            value=self.respond();self.assertEqual(value['public_key'],public(self.e.owner).hex());self.assertEqual(value['challenge'],self.challenge)
            self.assertIn('不会创建或替换密钥',recover.call_args.args[0]);self.assertIn(self.challenge['build_digest'],recover.call_args.args[0])
            recover.assert_called_once();create.assert_not_called();enrolled.assert_not_called();self.assertFalse(self.pin.exists())
    def test_failed_recovery_never_falls_back_to_creation_or_writes_pin(self):
        with patch.object(native,'recover_windows_hello_owner',side_effect=RuntimeError('hello_enrolled_credential_unavailable')),patch.object(native,'provision_windows_hello_owner') as create:
            with self.assertRaisesRegex(RuntimeError,'credential_unavailable'):self.respond()
            create.assert_not_called();self.assertFalse(self.pin.exists())
    def test_any_existing_pin_including_malformed_pin_blocks_orphan_recovery_before_os(self):
        for raw in (b'{broken',b'{}'):
            self.pin.write_bytes(raw)
            with patch.object(native,'recover_windows_hello_owner') as recover,patch.object(native,'provision_windows_hello_owner') as create:
                with self.assertRaisesRegex(AXRError,'requires_missing_pin'):self.respond()
                recover.assert_not_called();create.assert_not_called();self.assertEqual(self.pin.read_bytes(),raw)
    def test_changed_build_is_rejected_before_owner_key_operation(self):
        self.challenge['build_digest']='c3'*32
        with patch.object(native,'recover_windows_hello_owner') as recover:
            with self.assertRaisesRegex(AXRError,'challenge_invalid'):self.respond()
            recover.assert_not_called()
    def test_bad_attestation_cannot_be_used_even_when_local_recovery_returned_a_key(self):
        key=self.f.f.key();key.attestation=lambda:json.dumps({'statement':'aa','certificate_chain':'bb'})
        with patch.object(native,'recover_windows_hello_owner',return_value=key):
            with self.assertRaisesRegex(AXRError,'hardware_enrollment_invalid'):self.respond()
        self.assertFalse(self.pin.exists())
    def test_installed_authority_requires_no_receipt_and_no_history_for_orphan_challenge(self):
        with patch.object(wechat,'resources_root',return_value=self.root),patch.object(native,'exchange_windows_owner_setup',side_effect=self.f.native_exchange) as exchange:
            response=wechat.authenticate_owner_recovery(self.f.config)
            self.assertEqual(response['challenge']['kind'],'wechat-owner-orphan-recovery');exchange.assert_called_once()
            state=Path(self.f.config['state']);state.mkdir();(state/'policy.sealed.json').write_bytes(b'receipt must use authenticated receipt recovery')
            with self.assertRaisesRegex(AXRError,'requires_empty_setup'):wechat.authenticate_owner_recovery(self.f.config)
            self.assertEqual(exchange.call_count,1)
    def test_missing_hardware_key_does_not_turn_normal_initialization_into_recovery(self):
        ordinary={**self.challenge,'kind':'wechat-owner-enrollment'}
        with patch.object(native,'provision_windows_hello_owner',side_effect=RuntimeError('hello_existing_credential_requires_explicit_recovery')) as create,patch.object(
                native,'recover_windows_hello_owner') as recover:
            with self.assertRaisesRegex(RuntimeError,'explicit_recovery'):
                enrollment.respond(self.root,io.BytesIO(canonical(ordinary)+b'\n'),lambda value:None)
            create.assert_called_once();recover.assert_not_called()
    def test_fixed_explicit_bootstrap_entry_selects_recovery_hook_and_publishes_key_last(self):
        from axr import authority_setup
        writes=[]
        def missing(name):raise AXRError('owner_secret_not_provisioned')
        backend=SimpleNamespace(get=missing,provision=lambda name,value:writes.append(name))
        proof={**self.f.response(self.challenge),'identity':self.f.identity}
        registration=SimpleNamespace(owner_setup_review=lambda value:{},resume_owner_setup=lambda value:None,
            authenticate_owner_setup=Mock(),authenticate_owner_recovery=Mock(return_value=proof),
            initialize_owner=Mock(return_value={'state':self.f.config['state'],'endpoint':self.f.config['endpoint'],'owner_public_key':proof['public_key']}))
        with patch.object(native,'security_release',True),patch.object(authority_setup,'AuthoritySecretStore',return_value=backend),patch.object(
                authority_setup.importlib,'import_module',return_value=registration),patch.object(native,'HardwareSigningKey',return_value=SimpleNamespace(public_key=b'synthetic-root')):
            authority_setup.initialize(self.root,recover=True)
        registration.authenticate_owner_setup.assert_not_called();registration.authenticate_owner_recovery.assert_called_once_with(self.f.config)
        self.assertEqual(registration.initialize_owner.call_args.args[2],proof);self.assertEqual(writes[-1],'bootstrap-key')
    def test_native_orphan_challenge_checks_shape_before_any_os_user_token(self):
        with self.assertRaisesRegex(RuntimeError,'authority_host_required'):
            native.exchange_windows_owner_setup(self.f.config['owner_user'],canonical(self.challenge).decode())
        for changes in ({'build_digest':'short'},{'nonce':False},{'expected_public_key':'a1'*294}):
            with self.subTest(changes=changes),self.assertRaisesRegex(RuntimeError,'challenge_invalid'):
                native.exchange_windows_owner_setup(self.f.config['owner_user'],canonical({**self.challenge,**changes}).decode())
