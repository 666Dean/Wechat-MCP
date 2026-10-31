# SPDX-License-Identifier: MIT
"""Import a signed review into the fixed data directory, never install trust."""
import hashlib,json
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,canonical
from axr.rooted import RootedDirectory
from axr_applications.windows_admission import review_context,verify
from axr_applications.windows_navigation import decode_json
from .install_authority_windows import administrator,protect
from .windows_service import ServiceController
from .configure_windows_navigation import metadata_lease

def import_material(envelope,owner,expected_configuration):
    administrator()
    with metadata_lease():return _import_material(envelope,owner,expected_configuration)

def _import_material(envelope,owner,expected_configuration):
    administrator();service=ServiceController();service.register()
    if service.status()['state']!='Stopped':raise AXRError('windows_service_must_be_stopped')
    path=Path(native.windows_deployment_configuration());directory=RootedDirectory(path.parent)
    try:
        raw=directory.read(path.name,32768);registration=json.loads(raw)
        if registration['deployment']['owner_user']!=owner or hashlib.sha256(raw).hexdigest()!=expected_configuration:
            raise AXRError('windows_admission_configuration_changed')
        keys,expected=review_context(registration);review=verify(envelope,keys,expected)
        material=canonical(envelope)
        if len(material)>16000:raise AXRError('windows_admission_material_budget')
        def unchanged():
            if directory.read(path.name,32768)!=raw or service.status()['state']!='Stopped':
                raise AXRError('windows_admission_configuration_changed')
            keys_now,subject_now=review_context(registration);verify(envelope,keys_now,subject_now)
        # Replaces evidence only, never deployment trust, credentials or grants.
        target=Path(native.windows_data_root())/'windows-admission.json'
        if target.parent!=path.parent:raise AXRError('windows_admission_fixed_path_required')
        try:previous=directory.read(target.name,16000)
        except FileNotFoundError:previous=None
        if previous is not None:
            old=decode_json(previous)
            try:old_review=verify(old,keys,old['body']['subject'],clock=lambda:old['body']['created'])
            except (AXRError,KeyError,TypeError):raise AXRError('windows_admission_prior_material_invalid') from None
            if (review['sequence']<old_review['sequence'] or
                review['sequence']==old_review['sequence'] and review['evidence_digest']!=old_review['evidence_digest']):
                raise AXRError('windows_admission_rollback_or_equivocation')
        with directory.parent(target.name) as (parent,name):directory.replace_at(parent,name,material,unchanged)
        protect(target,reader=owner)
        return {**{k:review[k] for k in ('material_valid','stage','code_stage_complete','evidence_digest')},
            'imported':True,'service_started':False,'authorization_restored':False,'runtime_qualified':False}
    finally:directory.close()
