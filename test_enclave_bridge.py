# SPDX-License-Identifier: MIT
"""Explicit local hardware witness, with new disposable keys only."""
import ctypes as C
import os
import sys
import unittest
from axr import _axr_native as native

@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('AXR_TEST_ENCLAVE_BRIDGE'),'explicit local Secure Enclave witness required')
class EnclaveTests(unittest.TestCase):
    def test_device_bound_representation_and_der_signature(self):
        api=C.CDLL(os.environ['AXR_TEST_ENCLAVE_BRIDGE'])
        api.axr_enclave_create.argtypes=[C.c_int32,C.c_void_p,C.c_ssize_t];api.axr_enclave_create.restype=C.c_void_p
        for name in ('axr_enclave_public','axr_enclave_representation'):
            fn=getattr(api,name);fn.argtypes=[C.c_void_p,C.c_void_p,C.c_ssize_t];fn.restype=C.c_ssize_t
        api.axr_enclave_sign.argtypes=[C.c_void_p,C.c_void_p,C.c_ssize_t,C.c_void_p,C.c_ssize_t];api.axr_enclave_sign.restype=C.c_ssize_t
        api.axr_enclave_release.argtypes=[C.c_void_p]
        key=api.axr_enclave_create(0,None,0);self.assertTrue(key)
        try:
            representation=C.create_string_buffer(4096);n=api.axr_enclave_representation(key,representation,4096)
            self.assertTrue(0<n<=4096)
            public=C.create_string_buffer(65);self.assertEqual(api.axr_enclave_public(key,public,65),65)
            restored=api.axr_enclave_create(0,representation,n);self.assertTrue(restored)
            try:
                message=b'synthetic hardware signature, no WeChat data';signature=C.create_string_buffer(80)
                size=api.axr_enclave_sign(restored,message,len(message),signature,80)
                self.assertTrue(0<size<=80)
                self.assertTrue(native.verify_root_signature(public.raw,message,signature.raw[:size]))
            finally:api.axr_enclave_release(restored)
            # CryptoKit validates some internal fields lazily at signing. An
            # arbitrary byte flip can hit non-key metadata; use an invalid
            # serialized object rather than assume every bit is an AEAD tag.
            invalid=api.axr_enclave_create(0,b'\0'*n,n)
            if invalid:api.axr_enclave_release(invalid)
            self.assertFalse(invalid)
        finally:api.axr_enclave_release(key)
