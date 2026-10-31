# SPDX-License-Identifier: MIT
"""Explicit desktop lifecycle preparation; no raw credential contents or grants."""
import hashlib,json
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError
from axr.rooted import RootedDirectory
from .windows_setup import invoke
from .windows_provisioning import credential_source,native_provider
from .provisioning import fingerprint

def configure_navigation(document):
    from axr_applications.windows_navigation import prepare
    path=Path(native.windows_deployment_configuration());directory=RootedDirectory(path.parent)
    try:raw=directory.read(path.name,32768)
    finally:directory.close()
    config=json.loads(raw)['deployment'];helper=Path(native.windows_installation_root())/'wechat-uia.exe'
    prepare(document,account=config['application']['account_id'],helper=helper,
        helper_sha=fingerprint(helper,128*1024**2),endpoint=config['endpoint'])
    return invoke('navigation',{'document':document,'owner':config['owner_user'],
        'expected_configuration':hashlib.sha256(raw).hexdigest()})

def import_admission(envelope):
    from axr_applications.windows_admission import review_context,verify
    path=Path(native.windows_deployment_configuration());directory=RootedDirectory(path.parent)
    try:raw=directory.read(path.name,32768)
    finally:directory.close()
    registration=json.loads(raw);keys,expected=review_context(registration);verify(envelope,keys,expected)
    return invoke('admission',{'envelope':envelope,'owner':registration['deployment']['owner_user'],
        'expected_configuration':hashlib.sha256(raw).hexdigest()})

def admission_request():
    from axr_applications.windows_admission import review_context,request
    registration=installed_configuration();_,expected=review_context(registration)
    return request(expected)

def installed_configuration():
    path=Path(native.windows_deployment_configuration());directory=RootedDirectory(path.parent)
    try:config=json.loads(directory.read(path.name,32768))
    finally:directory.close()
    if config.get('version')!=2 or config.get('application_module')!='axr_applications.wechat':raise AXRError('authority_deployment_configuration_invalid')
    return config

def correct_credential(path,*,index=False,key_mode='file'):
    config=installed_configuration()['deployment'];shards=config['application']['shards']
    if not shards:raise AXRError('setup_account_folder_required')
    # This changes only the source reference. The installed account, shard
    # paths/salts, assets, owner and state cannot be selected by the GUI here.
    root=Path(shards[0]['path']).parent.parent
    source=credential_source(root,shards,path,index=index,key_mode=key_mode)
    return invoke('reconfigure',{'source':source,'owner':config['owner_user']})

def update_components(package,provider=None,admission_trust=None):
    config=installed_configuration();root=Path(native.windows_installation_root())
    program=native_provider(provider or root/'runtime/provider/codex.exe')
    app=config['deployment']['application'];current=app['codex_provider']
    app['codex_provider']={**current,'sha256':fingerprint(program,512*1024**2)}
    assets={'codex':str(program),'ca':str(root/'runtime/provider/ca-bundle.pem'),'hello_trust':str(root/'runtime/hello-trust.json')}
    if admission_trust is not None:
        from axr_applications.windows_admission import trust_keys
        from axr_applications.windows_navigation import read_json
        trust_keys(read_json(admission_trust,4096));pin=fingerprint(admission_trust,4096)
        if 'admission_trust_sha256' in app and pin!=app['admission_trust_sha256']:raise AXRError('windows_admission_trust_rotation_unavailable')
        app['admission_trust_sha256']=pin;assets['admission_trust']=str(admission_trust)
    elif 'admission_trust_sha256' in app:assets['admission_trust']=str(root/'runtime/admission-trust.json')
    return invoke('update',{'package':str(package),'configuration':config,'local_assets':assets})
