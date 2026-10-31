# SPDX-License-Identifier: MIT
"""Stage fixed navigation metadata; the System refresh performs owner review."""
import hashlib,json
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,canonical
from axr.rooted import RootedDirectory
from axr.host import Lease
from axr_applications.windows_navigation import prepare
from .install_authority_windows import administrator,protect
from .windows_service import ServiceController

def metadata_lease():
    from .install_authority_windows import unredirected
    data=unredirected(native.windows_data_root())
    if not data.is_dir():raise AXRError('windows_installation_required')
    area=unredirected(data/'metadata-leases');area.mkdir(exist_ok=True);unredirected(area)
    return Lease(area,'windows-metadata-update-v2')

def configure(document,owner,expected_configuration):
    administrator()
    with metadata_lease():return _configure(document,owner,expected_configuration)

def _configure(document,owner,expected_configuration):
    administrator();root=Path(native.windows_installation_root());native.verify_windows_installation(str(root))
    path=Path(native.windows_deployment_configuration());directory=RootedDirectory(path.parent)
    try:
        previous=directory.read(path.name,32768);registration=json.loads(previous);config=registration['deployment']
        if config['owner_user']!=owner or hashlib.sha256(previous).hexdigest()!=expected_configuration:
            raise AXRError('windows_navigation_configuration_changed')
        service=ServiceController();service.register()
        if service.status()['state']!='Stopped':raise AXRError('windows_service_must_be_stopped')
        helper=root/'wechat-uia.exe';assets=RootedDirectory(root)
        try:helper_sha=hashlib.sha256(assets.read(helper.name,128*1024**2)).hexdigest()
        finally:assets.close()
        navigation=prepare(document,account=config['application']['account_id'],helper=helper,helper_sha=helper_sha,endpoint=config['endpoint'])
        candidate={**registration,'deployment':{**config,'application':{**config['application'],'reply_navigation':navigation}}}
        raw=canonical(candidate)
        if len(raw)>32768:raise AXRError('windows_navigation_configuration_budget')
        def unchanged():
            if directory.read(path.name,32768)!=previous or service.status()['state']!='Stopped':
                raise AXRError('windows_navigation_configuration_changed')
        with directory.parent(path.name) as (parent,name):directory.replace_at(parent,name,raw,unchanged)
        protect(path,reader=owner)
        # The candidate is not the sealed, effective configuration. No rollback
        # after an ambiguous owner response, and no automatic service start.
        reviewed=False
        if (Path(config['state'])/'policy.sealed.json').exists():
            service.run('refresh');reviewed=True
        if directory.read(path.name,32768)!=raw:raise AXRError('windows_setup_outcome_unknown_no_retry')
        return {'navigation_staged':True,'owner_reviewed':reviewed,'initialization_required':not reviewed,
            'authorization_restored':False,'device_verified':False,'service_started':False}
    finally:directory.close()
