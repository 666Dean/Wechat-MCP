# SPDX-License-Identifier: AGPL-3.0-only
import hashlib,hmac,json,unittest
from axr.aet import canonical,wire_canonical,digest,AXRError
from axr import _axr_native as native
from axr.host import FrameCodec
from axr.authority import AuthorityKernel
from test.test_security_authority import FixtureSigner

class WireCanonicalTests(unittest.TestCase):
    value={'expires':1792386868.1760375,'label':'Synthetic protocol 数据'}
    def test_float_decimal_witness_uses_native_signature_representation(self):
        raw=canonical(self.value);wire=wire_canonical(self.value)
        self.assertNotEqual(raw,wire)
        self.assertEqual(json.loads(raw),json.loads(wire))
        self.assertEqual(wire_canonical(json.loads(wire)),wire)
        key=FixtureSigner();old=key.sign(raw)
        self.assertTrue(native.verify_root_signature(key.public_key,raw,old))
        self.assertFalse(native.verify_root_signature(key.public_key,wire,old))
        self.assertTrue(native.verify_root_signature(key.public_key,wire,key.sign(wire)))
        self.assertEqual(digest(self.value),hashlib.sha256(raw).hexdigest())
    def test_wire_mac_matches_native_client_and_rejects_changed_semantics(self):
        key=b'k'*32;sender=FrameCodec(key,'synthetic-epoch');receiver=FrameCodec(key,'synthetic-epoch')
        encoded=sender.encode(self.value);frame=json.loads(encoded)
        expected=native.hmac(key,wire_canonical(frame['body']).decode())
        self.assertEqual(frame['mac'],expected);self.assertEqual(receiver.decode(encoded),self.value)
        frame['body']['sequence']=2;frame['body']['payload']['expires']+=1
        with self.assertRaises(AXRError):receiver.decode(canonical(frame)+b'\n')
    def test_legacy_signature_is_receipt_only_never_a_current_execution_proof(self):
        root=object.__new__(AuthorityKernel);root.signer=FixtureSigner();root.root_public_key=root.signer.public_key
        root.root_id='synthetic-root';root.epoch='current-epoch'
        body={**self.value,'root_id':root.root_id,'epoch':root.epoch}
        self.assertEqual(root._verify(root._signed(body)),body)
        old={'body':body,'signature':root.signer.sign(canonical(body)).hex()}
        with self.assertRaises(AXRError):root._verify(old)
        self.assertEqual(root._verify(old,historical_receipt=True),body)
