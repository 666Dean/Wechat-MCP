# SPDX-License-Identifier: MIT
"""Owner enrollment requires both challenge possession and hardware evidence.

Keys/certificates are software fixtures. Runtime files use temporary directories;
no protected install, hardware credential or WeChat data is touched.
"""
import copy
import io
import json
from pathlib import Path
import tempfile
import time
import sys
import unittest
from unittest.mock import patch
from axr.aet import AXRError, canonical, digest
from test.test_windows_attestation import Evidence, public
from axr_applications import windows_enrollment as enrollment
from axr_applications import wechat


class ExistingOwnerEnrollment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.e=Evidence()
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve();self.outputs=[]
        self.config={'state':str(self.root/'new-state'),'endpoint':r'\\.\pipe\Stellaria.AXR.fixture' if sys.platform=='win32' else '/tmp/axr-fixture.sock',
            'application':{'account_id':'fixture-self','resources':[{'platform':'wechat',
                'account_id':'fixture-self','conversation_id':'fixture-peer'}]}}
        self.challenge={'version':2,'kind':'wechat-owner-enrollment','configuration_digest':digest(self.config),
            'nonce':'a1'*32,'expires':time.time()+150}
        self.evidence={'statement':self.e.statement().hex(),'certificate_chain':self.e.chain().hex()}
        self.write('deployment.json',{'version':2,'application_module':'axr_applications.wechat','deployment':self.config})
        self.write('hello-trust.json',{'version':2,'roots':[r.hex() for r in self.e.roots]})
    def write(self,name,value):(self.root/name).write_bytes(canonical(value))
    def key(self):
        fixture=self
        class Key:
            public_key=public(fixture.e.owner)
            def attestation(self):return json.dumps(fixture.evidence)
            def sign(self,message):
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.asymmetric import padding
                return fixture.e.owner.sign(message,padding.PKCS1v15(),hashes.SHA256())
        return Key()
    def respond(self,challenge=None,**options):
        with patch.object(enrollment,'enrolled_key',return_value=self.key()) as factory,patch.object(
                wechat,'resources_root',return_value=self.root):
            result=enrollment.respond(self.root,io.BytesIO(canonical(challenge or self.challenge)+b'\n'),self.outputs.append,**options)
            return result,factory
    @unittest.skipUnless(sys.platform=='win32','native Windows evidence verifier')
    def test_existing_key_response_requires_complete_native_evidence(self):
        response,factory=self.respond()
        self.assertEqual(len(self.outputs),1);factory.assert_called_once_with(self.root)
        self.assertEqual(enrollment.validate_response(self.challenge,response,self.e.roots),public(self.e.owner))
        self.assertFalse((self.root/'new-state').exists())
    def test_changed_scope_or_invalid_challenge_cannot_open_key(self):
        for changed in ({'configuration_digest':'b2'*32},{'nonce':'c3'*31},{'version':True},{'expires':time.time()+1000}):
            challenge={**self.challenge,**changed}
            with patch.object(enrollment,'enrolled_key') as key,patch.object(wechat,'resources_root',return_value=self.root):
                with self.assertRaisesRegex(AXRError,'challenge_invalid'):
                    enrollment.respond(self.root,io.BytesIO(canonical(challenge)+b'\n'),self.outputs.append)
                key.assert_not_called()
        self.assertEqual(self.outputs,[])
    def test_trust_roots_are_fixed_bounded_unique_and_not_a_peer_flag(self):
        for value in ({'version':2,'roots':[]},{'version':True,'roots':['aa']},
                      {'version':2,'roots':['aa']*2},{'version':2,'roots':['aA']},
                      {'version':2,'roots':['aa'],'trusted':True}):
            self.write('hello-trust.json',value)
            with self.assertRaisesRegex(AXRError,'trust_roots_required'):enrollment.trust_roots(self.root)
        (self.root/'hello-trust.json').write_bytes(b'{"version":2,"version":2,"roots":[]}')
        with self.assertRaisesRegex(AXRError,'trust_roots_required'):enrollment.trust_roots(self.root)
    @unittest.skipUnless(sys.platform=='win32','native Windows evidence verifier')
    def test_hardware_failure_emits_no_enrollment(self):
        self.evidence['statement']=self.e.statement(name=b'wrong').hex()
        with self.assertRaisesRegex(AXRError,'hardware_enrollment_invalid'):self.respond()
        self.assertEqual(self.outputs,[])
    @unittest.skipUnless(sys.platform=='win32','native Windows evidence verifier')
    def test_changed_challenge_proof_or_claim_only_cannot_enroll(self):
        response,_=self.respond()
        changed=copy.deepcopy(response);changed['signature']='aa'*256
        cases=[changed,{**response,'provider':'TPM'},{**response,'hardware':True},
               {**response,'attestation':{'hardware':True}},{**response,'challenge':{**self.challenge,'nonce':'b1'*32}}]
        for value in cases:
            with self.assertRaisesRegex(AXRError,'hardware_enrollment_invalid'):
                enrollment.validate_response(self.challenge,value,self.e.roots)
        with self.assertRaisesRegex(AXRError,'hardware_enrollment_invalid'):
            enrollment.validate_response(self.challenge,response,self.e.roots,clock=lambda:self.challenge['expires']+1)
