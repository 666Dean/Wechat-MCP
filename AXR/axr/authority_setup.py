# SPDX-License-Identifier: AGPL-3.0-only
"""Owner-only first setup inside the fixed installed native authority host."""
import hashlib,importlib,json,os,re,sys
from pathlib import Path
from .aet import AXRError,canonical,digest
from .storage import AuthoritySecretStore,Vault
from .owner import authenticate
from . import _axr_native as native

def main(runtime_root):
    if not getattr(native,'security_release',False):raise AXRError('authority_formal_build_required')
    root=Path(runtime_root);path=root/'deployment.json'
    if path.is_symlink() or path.stat().st_size>32768:raise AXRError('authority_deployment_configuration_invalid')
    data=path.read_bytes();configuration=json.loads(data)
    if set(configuration)!={'version','application_module','deployment'} or configuration['version']!=2:raise AXRError('authority_deployment_configuration_invalid')
    module=configuration['application_module']
    if not isinstance(module,str) or not re.fullmatch(r'axr_applications\.[a-z][a-z0-9_]{0,63}',module):raise AXRError('authority_application_registration_invalid')
    backend=AuthoritySecretStore('Stellaria.AXR.Bootstrap')
    try:backend.get('bootstrap-key')
    except AXRError as e:
        if str(e)!='owner_secret_not_provisioned':raise
    else:raise AXRError('authority_already_initialized')
    registration=importlib.import_module(module)
    review=registration.owner_setup_review(configuration['deployment'])
    # The application review is data on the trusted local owner surface; not a
    # model prompt. It must include deployment owner, resources and entry points.
    print(json.dumps({'operation':'Initialize owner-deployed AXR authority','build_review':review,'configuration_digest':digest(configuration)},ensure_ascii=False))
    helper=root/'bin'/('axr-owner-auth.exe' if sys.platform=='win32' else 'axr-helper')
    authenticate(helper)
    if path.read_bytes()!=data:raise AXRError('authority_deployment_changed_during_authentication')
    signer=native.HardwareSigningKey('Stellaria.AXR.Root.v2',create=True)
    # Application enrollment handles the owner-presence key and managed peers;
    # it cannot obtain a software fallback or automatic legacy authority restore.
    deployment=registration.initialize_owner(configuration['deployment'],signer)
    if type(deployment) is not dict:raise AXRError('authority_owner_enrollment_invalid')
    vault_key=os.urandom(32);vault=Vault(vault_key)
    value={**configuration,'deployment':deployment}
    sealed=vault.seal(value,'authority-bootstrap-v2')
    if len(sealed)>4096:raise AXRError('authority_bootstrap_budget')
    backend.provision('root-public-key',signer.public_key)
    backend.provision('configuration',sealed)
    # Key last: any earlier interrupted setup never becomes a usable bootstrap.
    backend.provision('bootstrap-key',vault_key)
    print(json.dumps({'initialized':True,'authority_restored':False,'vendor_certificate_required':False}))
