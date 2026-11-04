# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Stellaria-Commercial-1.0
"""Windows maintenance-only qualification; never a fallback from normal serve."""
import importlib,os,re
from . import _axr_native as native
from .aet import AXRError
from .storage import AuthoritySecretStore,Vault


def main():
    if os.name!='nt' or native.security_release is not True:raise AXRError('formal_windows_qualification_host_required')
    backend=AuthoritySecretStore('Stellaria.AXR.Bootstrap')
    config=Vault(backend.get('bootstrap-key')).open(backend.get('configuration'),'authority-bootstrap-v2')
    if (type(config) is not dict or set(config)!={'version','application_module','deployment'} or
        type(config['version']) is not int or config['version']!=2 or
        type(config['application_module']) is not str or
        re.fullmatch(r'axr_applications\.[a-z][a-z0-9_]{0,63}',config['application_module']) is None):
        raise AXRError('authority_bootstrap_invalid')
    run=getattr(importlib.import_module(config['application_module']),'qualify_once',None)
    if not callable(run):raise AXRError('authority_qualification_not_registered')
    return run(config['deployment'])
