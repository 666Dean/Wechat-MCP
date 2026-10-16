# SPDX-License-Identifier: MIT
import hashlib,tempfile,unittest
from pathlib import Path
from axr.aet import AXRError
from axr.deployment import OwnerDeployment
from axr.storage import Vault
from test.test_security_authority import ProtectedStore
class OwnerBuildTrust(unittest.TestCase):
    def test_self_deployed_binary_uses_exact_os_protected_pin_without_vendor_pki(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'agent';binary.write_bytes(b'owner-built fixed agent')
            deployment=OwnerDeployment(ProtectedStore(),Vault(b'v'*32),development_fixture=True)
            result=deployment.enroll(root,[{'path':'agent','roles':['client']}],lambda:'owner')
            self.assertFalse(result['vendor_certificate_required']);self.assertFalse(result['authority_restored'])
            actual={'image':str(root.resolve()/'agent'),'image_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'signature_valid':False}
            self.assertTrue(deployment.verify_process(actual,'client'))
            self.assertFalse(deployment.verify_process(actual,'owner'))
            self.assertFalse(deployment.verify_process({**actual,'image_sha256':'0'*64},'client'))
    def test_owner_pin_cannot_be_installed_by_a_message_or_ordinary_keyring(self):
        with self.assertRaisesRegex(AXRError,'native_authority_store_required'):OwnerDeployment(ProtectedStore(),Vault(b'v'*32))
        with tempfile.TemporaryDirectory() as tmp:
            deployment=OwnerDeployment(ProtectedStore(),Vault(b'v'*32),development_fixture=True)
            with self.assertRaisesRegex(AXRError,'authentication_required'):deployment.enroll(tmp,[],lambda:False)
    def test_changing_owner_build_requires_revocation_before_new_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'agent').write_bytes(b'one');backend=ProtectedStore();deployment=OwnerDeployment(backend,Vault(b'v'*32),development_fixture=True)
            deployment.enroll(root,[{'path':'agent','roles':['client']}],lambda:'owner');(root/'agent').write_bytes(b'two')
            with self.assertRaisesRegex(AXRError,'requires_revocation'):deployment.enroll(root,[{'path':'agent','roles':['client']}],lambda:'owner')
            events=[];deployment.revoke_for_update=lambda:events.append('revoke') or True
            deployment.enroll(root,[{'path':'agent','roles':['client']}],lambda:'owner');self.assertEqual(events,['revoke'])
