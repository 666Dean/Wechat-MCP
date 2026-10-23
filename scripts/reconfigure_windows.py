# SPDX-License-Identifier: MIT
"""Stage one fixed credential-reference correction for the System authority."""
import hashlib,json,secrets
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,canonical
from axr.rooted import RootedDirectory
from .install_authority_windows import administrator,protect
from .windows_service import ServiceController

def correct(source,owner):
    administrator()
    if type(source) is not dict or set(source) not in ({'credential_import'},{'legacy_namespace'}):raise AXRError('windows_setup_source_request_invalid')
    root=Path(native.windows_installation_root());native.verify_windows_installation(str(root))
    path=Path(native.windows_deployment_configuration());directory=RootedDirectory(path.parent)
    try:
        previous=directory.read(path.name,32768);configuration=json.loads(previous)
        if configuration['deployment']['owner_user']!=owner:raise AXRError('windows_setup_owner_invalid')
        service=ServiceController()
        service.register()
        if service.status()['state']!='Stopped':raise AXRError('windows_service_must_be_stopped')
        nonce=secrets.token_hex(16)
        request=canonical({'version':2,'owner':owner,'nonce':nonce,'expected_configuration':hashlib.sha256(previous).hexdigest(),'source':source})
        if len(request)>8192:raise AXRError('windows_setup_source_request_invalid')
        name='setup-source-request.json'
        with directory.parent(name) as (parent,base):directory.replace_at(parent,base,request,lambda:None)
        protect(path.parent/name,reader=owner)
        # Only the native System entry can decide whether bootstrap, MAC
        # receipt and authenticated history are genuinely absent.
        service.run('reconfigure')
        try:result=json.loads(directory.read('setup-source-result.json',8192))
        except Exception:raise AXRError('windows_setup_outcome_unknown_no_retry') from None
        expected={'version','nonce','configuration','source_updated','initialized','authorization_restored'}
        if (type(result) is not dict or set(result)!=expected or type(result['version']) is not int or result['version']!=2 or
            result['nonce']!=nonce or result['source_updated'] is not True or result['initialized'] is not False or
            result['authorization_restored'] is not False or result['configuration']!=hashlib.sha256(directory.read(path.name,32768)).hexdigest()):
            raise AXRError('windows_setup_outcome_unknown_no_retry')
        return {'source_updated':True,'initialized':False,'authorization_restored':False}
    finally:directory.close()
