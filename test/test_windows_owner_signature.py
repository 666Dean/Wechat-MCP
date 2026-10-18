# SPDX-License-Identifier: MIT
"""Windows Hello owner signature format, with ephemeral software fixtures only.

These tests exercise real native verification and the signed challenge paths.
They never create a hardware key, show Hello UI, or qualify an installation.
"""
import sys
import unittest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from axr import _axr_native as native
from axr.aet import AXRError, canonical
from test import test_security_authority as fixtures
from test.test_authority_mcp import application_fixture


class RSAFixtureSigner:
    def __init__(self):
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.public_key=self.key.public_key().public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
    def sign(self,message):return self.key.sign(message,padding.PKCS1v15(),hashes.SHA256())


@unittest.skipUnless(sys.platform=='win32','Windows Hello owner signature profile')
class WindowsOwnerSignature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signer=RSAFixtureSigner()
        cls.message=canonical({'kind':'synthetic-owner-challenge','nonce':'fixture-once','required':False})
        cls.signature=cls.signer.sign(cls.message)
    def test_hello_format_verifies_only_at_owner_boundary(self):
        self.assertEqual(len(self.signer.public_key),294)
        self.assertEqual(len(self.signature),256)
        self.assertTrue(native.verify_owner_signature(self.signer.public_key,self.message,self.signature))
        self.assertFalse(native.verify_root_signature(self.signer.public_key,self.message,self.signature))
    def test_existing_p256_owner_format_is_preserved(self):
        key=fixtures.FixtureSigner()
        signature=key.sign(self.message)
        self.assertTrue(native.verify_owner_signature(key.public_key,self.message,signature))
        self.assertTrue(native.verify_root_signature(key.public_key,self.message,signature))
    def test_changed_challenge_wrong_key_and_broken_signature_are_rejected(self):
        wrong=RSAFixtureSigner()
        for key,message,signature in ((self.signer.public_key,self.message+b' ',self.signature),
                (wrong.public_key,self.message,self.signature),
                (self.signer.public_key,self.message,self.signature[:-1]+bytes([self.signature[-1]^1])),
                (self.signer.public_key,self.message,self.signature[:-1])):
            self.assertFalse(native.verify_owner_signature(key,message,signature))
    def test_no_padding_hash_or_algorithm_negotiation(self):
        for signature in (self.signer.key.sign(self.message,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256()),
                self.signer.key.sign(self.message,padding.PKCS1v15(),hashes.SHA384())):
            self.assertFalse(native.verify_owner_signature(self.signer.public_key,self.message,signature))
        keys=[rsa.generate_private_key(public_exponent=65537,key_size=size) for size in (1024,3072)]
        keys.append(rsa.generate_private_key(public_exponent=3,key_size=2048))
        for key in keys:
            public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
            self.assertFalse(native.verify_owner_signature(public,self.message,key.sign(self.message,padding.PKCS1v15(),hashes.SHA256())))
        der_ec=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.assertFalse(native.verify_owner_signature(der_ec,self.message,self.signature))
    def test_malformed_trailing_and_oversized_inputs_are_rejected(self):
        for key in (b'',b'\0'*294,self.signer.public_key+b'\0',self.signer.public_key[:-1],
                    b'\x31'+self.signer.public_key[1:]):
            self.assertFalse(native.verify_owner_signature(key,self.message,self.signature))
        self.assertFalse(native.verify_owner_signature(self.signer.public_key,b'x'*(1024*1024+1),self.signature))
    def test_rsa_owner_contract_authorization_keeps_signed_challenge_single_use(self):
        fixture=fixtures.AuthorityTests('test_owner_presence_task_access_handler_claim_and_unknown_no_retry')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.ownerkey=self.signer
        fixture.k.owner_public_key=self.signer.public_key
        review=fixture.call(fixture.owner,'Authorize',phase='review',contract=fixture.c.body())
        values={'contract':fixture.c.body(),'challenge_id':review['challenge']['nonce'],
                'owner_signature':self.signer.sign(canonical(review['challenge'])).hex()}
        capability=fixture.call(fixture.owner,'Authorize',**values)
        self.assertEqual(fixture.k._task(fixture.client,capability)['id'],fixture.c.id)
        with self.assertRaisesRegex(AXRError,'expired_or_changed'):
            fixture.call(fixture.owner,'Authorize',**values)
    def test_rsa_owner_can_change_approval_setting_but_client_cannot(self):
        fixture=application_fixture();self.addCleanup(fixture.doCleanups)
        fixture.k.owner_public_key=self.signer.public_key
        with self.assertRaisesRegex(AXRError,'owner_channel_required'):
            fixture.call(fixture.client,'Authorize',phase='review-approval-setting',manual_approval_required=False)
        review=fixture.call(fixture.owner,'Authorize',phase='review-approval-setting',manual_approval_required=False)
        result=fixture.call(fixture.owner,'Authorize',phase='approve-approval-setting',manual_approval_required=False,
            challenge_id=review['challenge']['nonce'],owner_signature=self.signer.sign(canonical(review['challenge'])).hex())
        self.assertIs(result['manual_approval_required'],False)
        self.assertEqual(fixture.saved_settings,[(False,1)])
