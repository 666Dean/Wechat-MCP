# SPDX-License-Identifier: MIT
"""Synthetic TPM2 statements and private certificate stores; no device access."""
from datetime import datetime, timedelta, timezone
import hashlib
import struct
import sys
import unittest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID, ObjectIdentifier
from axr import _axr_native as native


AIK_OID=ObjectIdentifier('2.23.133.8.3')
def public(key):
    return key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
def b2(value):return struct.pack('>H',len(value))+value
def der(tag,value):
    size=len(value);length=bytes([size]) if size<128 else bytes([0x80+(size.bit_length()+7)//8])+size.to_bytes((size.bit_length()+7)//8,'big')
    return bytes([tag])+length+value
def certificate_buffer(certificates,crls):
    # Degenerate PKCS#7 SignedData carries certificates/CRLs, with no signer.
    signed_data=(b'\x02\x01\x01\x31\x00'+der(0x30,bytes.fromhex('06092a864886f70d010701'))+
        der(0xa0,b''.join(c.public_bytes(serialization.Encoding.DER) for c in certificates))+
        der(0xa1,b''.join(c.public_bytes(serialization.Encoding.DER) for c in crls))+b'\x31\x00')
    return der(0x30,bytes.fromhex('06092a864886f70d010702')+der(0xa0,der(0x30,signed_data)))


class Evidence:
    def __init__(self):
        self.owner=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.aik=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.root_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.now=datetime.now(timezone.utc)
        self.root_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic AXR test root')])
        self.root=(x509.CertificateBuilder().subject_name(self.root_name).issuer_name(self.root_name)
            .public_key(self.root_key.public_key()).serial_number(1).not_valid_before(self.now-timedelta(days=1))
            .not_valid_after(self.now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=1),critical=True)
            .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(self.root_key.public_key()),critical=False)
            .sign(self.root_key,hashes.SHA256()))
    def statement(self,*,attributes=0x00040072,name=None,modulus=None):
        numbers=self.owner.public_key().public_numbers()
        area=struct.pack('>HHI',1,0xb,attributes)+b2(b'')+struct.pack('>HHHI',0x10,0x10,2048,65537)+b2(
            modulus if modulus is not None else numbers.n.to_bytes(256,'big'))
        attest=(struct.pack('>IH',0xff544347,0x8017)+b2(b'')+b2(b'')+bytes(25)+
                b2(name if name is not None else b'\x00\x0b'+hashlib.sha256(area).digest())+b2(b''))
        signature=self.aik.sign(attest,padding.PKCS1v15(),hashes.SHA1())
        key=struct.pack('<13I',0x4d504350,52,2,1,len(area)+2,*([0]*8))+b2(area)
        return struct.pack('<6I',0x5344414b,2,24,len(attest),len(signature),len(key))+attest+signature+key
    def chain(self,*,revoked=False,expired=False,eku=AIK_OID,crl=True):
        before=self.now-timedelta(days=2 if expired else 1)
        after=self.now-timedelta(days=1) if expired else self.now+timedelta(hours=2)
        leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic AIK')]))
            .issuer_name(self.root_name).public_key(self.aik.public_key()).serial_number(2)
            .not_valid_before(before).not_valid_after(after).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
            .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False),critical=True)
            .add_extension(x509.ExtendedKeyUsage([eku]),critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self.root_key.public_key()),critical=False)
            .sign(self.root_key,hashes.SHA256()))
        builder=(x509.CertificateRevocationListBuilder().issuer_name(self.root_name)
            .last_update(self.now-timedelta(hours=1)).next_update(self.now+timedelta(hours=1)))
        if revoked:builder=builder.add_revoked_certificate(x509.RevokedCertificateBuilder().serial_number(2)
            .revocation_date(self.now-timedelta(minutes=30)).build())
        return certificate_buffer([leaf,self.root],[builder.sign(self.root_key,hashes.SHA256())] if crl else [])
    @property
    def roots(self):return [self.root.public_bytes(serialization.Encoding.DER)]


class TPMStatement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.e=Evidence()
    def verify(self,statement,owner=None,aik=None):
        return native.verify_windows_hello_statement(owner or public(self.e.owner),aik or public(self.e.aik),statement)
    def test_signed_tpm2_name_and_public_key_binding(self):
        self.assertTrue(self.verify(self.e.statement()))
        wrong=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.assertFalse(self.verify(self.e.statement(),owner=public(wrong)))
        self.assertFalse(self.verify(self.e.statement(),aik=public(wrong)))
    def test_signed_but_wrong_name_or_migratable_key_is_rejected(self):
        for options in ({'name':b'\0'*34},{'attributes':0x40070},{'attributes':0x40062},
                        {'attributes':0x50072},{'modulus':b'x'*256}):
            with self.subTest(options=options):self.assertFalse(self.verify(self.e.statement(**options)))
    def test_truncation_size_overflow_version_and_signature_tampering(self):
        good=self.e.statement()
        for value in (b'',good[:-1],good+b'\0',good[:16]+b'\xff'*4+good[20:],
                good[:4]+struct.pack('<I',1)+good[8:],good[:12]+struct.pack('<I',0xffffffff)+good[16:],
                good[:100]+bytes([good[100]^1])+good[101:],b'x'*65537):
            self.assertFalse(self.verify(value))
        self.assertFalse(native.verify_windows_hello_statement(public(self.e.owner)+b'\0',public(self.e.aik),good))


@unittest.skipUnless(sys.platform=='win32','native Windows exclusive-root chain engine')
class AttestationChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.e=Evidence()
    def verify(self,chain,roots=None,statement=None):
        return native.verify_windows_hello_attestation(public(self.e.owner),statement or self.e.statement(),chain,
            self.e.roots if roots is None else roots)
    def test_complete_synthetic_chain_with_supplied_current_crl(self):
        self.assertTrue(self.verify(self.e.chain()))
    def test_revoked_expired_wrong_usage_or_unknown_revocation_is_rejected(self):
        for options in ({'revoked':True},{'expired':True},{'eku':ObjectIdentifier('1.3.6.1.5.5.7.3.1')},{'crl':False}):
            with self.subTest(options=options):self.assertFalse(self.verify(self.e.chain(**options)))
    def test_caller_chain_cannot_supply_its_own_trusted_root(self):
        self.assertFalse(self.verify(self.e.chain(),roots=[]))
        other=Evidence()
        self.assertFalse(self.verify(self.e.chain(),roots=other.roots))
    def test_valid_chain_does_not_replace_statement_verification(self):
        self.assertFalse(self.verify(self.e.chain(),statement=self.e.statement(name=b'x'*34)))
        self.assertFalse(self.verify(b'not a chain'))
