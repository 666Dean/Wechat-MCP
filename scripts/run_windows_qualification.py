# SPDX-License-Identifier: MIT
"""Stage one signed experiment and run only the fixed qualification SCM entry."""
import hashlib
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,canonical,digest
from axr.rooted import RootedDirectory
from axr_applications.windows_admission import review_context
from axr_applications.windows_navigation import decode_json
from axr_applications.windows_qualification import verify
from .configure_windows_navigation import metadata_lease
from .install_authority_windows import administrator,protect
from .windows_service import ServiceController


def run(envelope,owner,expected_configuration):
    administrator()
    with metadata_lease():
        service=ServiceController();service.register()
        if service.status()['state']!='Stopped':raise AXRError('windows_service_must_be_stopped')
        path=Path(native.windows_deployment_configuration());directory=RootedDirectory(path.parent)
        try:
            raw=directory.read(path.name,32768);registration=decode_json(raw)
            if registration['deployment']['owner_user']!=owner or hashlib.sha256(raw).hexdigest()!=expected_configuration:
                raise AXRError('windows_qualification_configuration_changed')
            keys,expected=review_context(registration);verify(envelope,keys,expected)
            material=canonical(envelope)
            if len(material)>20000:raise AXRError('windows_qualification_permit_budget')
            target=Path(native.windows_data_root())/'windows-qualification.json'
            if target.parent!=path.parent:raise AXRError('windows_qualification_fixed_path_required')
            def unchanged():
                if directory.read(path.name,32768)!=raw or service.status()['state']!='Stopped':raise AXRError('windows_qualification_configuration_changed')
                current_keys,current=review_context(registration);verify(envelope,current_keys,current)
            with directory.parent(target.name) as (parent,name):directory.replace_at(parent,name,material,unchanged)
            protect(target,reader=owner)
            service.run('qualify',timeout=600)
            result=decode_json(directory.read('windows-qualification-result.json',16000))
            if (result.get('permit_digest')!=digest(envelope) or result.get('retry') is not False or
                result.get('runtime_qualified') is not False or result.get('authorization_restored') is not False):
                raise AXRError('windows_qualification_outcome_unknown_no_retry')
            return result
        finally:directory.close()
