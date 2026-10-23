# SPDX-License-Identifier: MIT
"""Explicit desktop lifecycle preparation; no raw credential contents or grants."""
import json
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError
from axr.rooted import RootedDirectory
from .windows_setup import invoke
from .windows_provisioning import credential_source,native_provider
from .provisioning import fingerprint

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

def update_components(package,provider=None):
    config=installed_configuration();root=Path(native.windows_installation_root())
    program=native_provider(provider or root/'runtime/provider/codex.exe')
    app=config['deployment']['application'];current=app['codex_provider']
    app['codex_provider']={**current,'sha256':fingerprint(program,512*1024**2)}
    return invoke('update',{'package':str(package),'configuration':config,'local_assets':{
        'codex':str(program),'ca':str(root/'runtime/provider/ca-bundle.pem'),'hello_trust':str(root/'runtime/hello-trust.json')}})
