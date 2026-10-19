#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install reviewed native code with the owner's macOS administrator approval.

No credentials are imported and no service permissions are granted by install.
The source file inventory is compared again AFTER the protected copy is made.
An existing installation is refused; updates require explicit stop/re-enrollment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid
from contextlib import ExitStack

BASE=Path('/Library/Application Support/Stellaria AXR')
BUNDLES=('AXR Authority.app','AXR Owner.app','AXR MCP.app')

def installed_configuration():
    from axr.deployment_configuration import read
    return read(BASE/'AXR Authority.app/Contents/Resources')['deployment']

def install(package,*,replace_uninitialized=False,replace_stopped=False,configuration=None,local_assets=None):
    if replace_uninitialized and replace_stopped:raise RuntimeError('choose one update workflow')
    with ExitStack() as stack:
        if replace_stopped:
            current=installed_configuration()
            from axr.host import Lease
            stack.enter_context(Lease(Path.home()/'.stellaria-axr'/'leases',['journal',str(Path(current['state']))]))
        return _install(package,replace_uninitialized=replace_uninitialized,replace_stopped=replace_stopped,
                        configuration=configuration,local_assets=local_assets)

def _install(package,*,replace_uninitialized=False,replace_stopped=False,configuration=None,local_assets=None):
    if sys.platform!='darwin':raise RuntimeError('macOS required')
    package=Path(package).resolve(strict=True)
    manifest=json.loads((package/'package-review.json').read_bytes())['files']
    marker=json.loads((package/'AXR Authority.app/Contents/Resources/deployment.json').read_bytes())
    external=marker.get('deployment_source')=='installation'
    if external:
        from axr.deployment_configuration import MARKER
        if configuration is None and (replace_uninitialized or replace_stopped):
            configuration={'version':2,'application_module':'axr_applications.wechat','deployment':installed_configuration()}
            provider=configuration['deployment']['application']['codex_provider']
            if Path(provider['binary'])!=BASE/'Codex Provider/codex' or Path(provider['tls_bundle'])!=BASE/'ca-bundle.pem':
                raise RuntimeError('legacy_deployment_requires_explicit_migration')
            local_assets={'codex':Path(provider['binary']),'ca':Path(provider['tls_bundle'])}
        if marker!=MARKER or type(configuration) is not dict or set(configuration)!={'version','application_module','deployment'} or configuration.get('application_module')!='axr_applications.wechat' or configuration.get('version')!=2:
            raise RuntimeError('setup_configuration_required')
        if set(local_assets or {})!={'codex','ca'}:raise RuntimeError('setup_local_components_required')
        if len(json.dumps(configuration).encode())>32768:raise RuntimeError('setup_configuration_budget')
    elif configuration is not None or local_assets:raise RuntimeError('setup_configuration_not_expected')
    files={}
    for name in BUNDLES:
        for path in (package/name).rglob('*'):
            if path.is_symlink():raise RuntimeError('package links denied')
            if path.is_file():
                relative=str(path.relative_to(package))
                if '\n' in relative or '\\' in relative:raise RuntimeError('package filename rejected')
                expected=manifest.get(relative)
                if expected!=hashlib.sha256(path.read_bytes()).hexdigest():raise RuntimeError('package changed since review')
                files[relative]=expected
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(package/name)],check=True,capture_output=True)
    if BASE.exists():
        if not (replace_uninitialized or replace_stopped):raise RuntimeError('existing installation requires explicit update workflow')
        current=installed_configuration()
        proposed=configuration['deployment'] if external else marker['deployment']
        from axr.initialization import empty_initialization
        endpoint=Path(current['endpoint'])
        from axr_applications.wechat import provider_build_update
        same={k:v for k,v in current.items() if k!='application'}=={k:v for k,v in proposed.items() if k!='application'}
        same=same and provider_build_update(current['application'],proposed['application'],bundled_path='@resources/CodexCLI.app/Contents/MacOS/codex')
        if (current!=proposed and (not replace_stopped or not same)) or endpoint.exists() or endpoint.is_symlink():
            raise RuntimeError('initialized deployment requires stop and authenticated re-enrollment')
        if replace_uninitialized and not empty_initialization(current['state']):
            raise RuntimeError('initialized deployment requires stop and authenticated re-enrollment')
        if replace_stopped and not (Path(current['state'])/'policy.sealed.json').is_file():
            raise RuntimeError('initialized deployment required for stopped update')
    temporary=BASE.with_name('Stellaria AXR.install-'+uuid.uuid4().hex)
    q=shlex.quote
    lines=['set -eu','umask 022']
    if not (replace_uninitialized or replace_stopped):lines.append('/bin/test ! -e '+q(str(BASE)))
    lines.append('/bin/mkdir '+q(str(temporary)))
    for name in BUNDLES:lines.append('/usr/bin/ditto '+q(str(package/name))+' '+q(str(temporary/name)))
    if external:
        config=json.dumps(configuration,ensure_ascii=False,separators=(',',':'))
        lines.append('(umask 077; /usr/bin/printf %s '+q(config)+' > '+q(str(temporary/'deployment.json'))+')')
        lines.append('/bin/chmod +a '+q('user:'+str(__import__('os').getuid())+' allow read')+' '+q(str(temporary/'deployment.json')))
        provider=configuration['deployment']['application']['codex_provider']
        # Only a local user's explicitly selected, verified signed runtime is
        # copied here. It is never redistributed in the public installer.
        lines.append('/bin/mkdir '+q(str(temporary/'Codex Provider')))
        for kind,relative,expected in [('codex','Codex Provider/codex',provider['sha256']),('ca','ca-bundle.pem',provider['tls_sha256'])]:
            source=Path(local_assets[kind]).resolve(strict=True)
            if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise RuntimeError('setup_local_component_changed')
            lines.append('/usr/bin/ditto '+q(str(source))+' '+q(str(temporary/relative)))
            lines.append('/bin/chmod '+('755' if kind=='codex' else '644')+' '+q(str(temporary/relative)))
            files[relative]=expected
        lines.append('/usr/bin/codesign --verify --strict '+q(str(temporary/'Codex Provider/codex')))
    lines+=['/usr/sbin/chown -R root:wheel '+q(str(temporary)), '/bin/chmod -R go-w '+q(str(temporary))]
    for name in BUNDLES:lines.append('/usr/bin/codesign --verify --deep --strict '+q(str(temporary/name)))
    inventory=''.join(sha+'  '+str(temporary/relative)+'\n' for relative,sha in sorted(files.items()))
    lines.append('/usr/bin/printf %s '+q(inventory)+' | /usr/bin/shasum -a 256 -c - >/dev/null')
    if replace_uninitialized or replace_stopped:
        previous=BASE.with_name('Stellaria AXR.previous-'+uuid.uuid4().hex)
        lines.append('/bin/mv '+q(str(BASE))+' '+q(str(previous)))
    lines.append('/bin/mv '+q(str(temporary))+' '+q(str(BASE)))
    # The complete fixed script is embedded in the OS approval request. It is
    # not executed from a user-writable script file after authentication.
    script='do shell script '+json.dumps('\n'.join(lines),ensure_ascii=False)+' with administrator privileges'
    result=subprocess.run(['/usr/bin/osascript','-e',script],capture_output=True,text=True)
    if result.returncode:raise RuntimeError('installation_not_completed')
    from axr.platform.macos_application import register_bundle
    for name in BUNDLES:register_bundle(BASE/name)
    return {'installed':True,'owner_enrolled':False,'wechat_authorized':False,
            'build_reenrollment_required':replace_stopped,'state_retained':replace_stopped}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--package',required=True,type=Path)
    parser.add_argument('--replace-uninitialized',action='store_true')
    parser.add_argument('--replace-stopped',action='store_true',help='Preserve initialized state; requires stopped service and subsequent hardware build re-enrollment')
    args=parser.parse_args();print(json.dumps(install(args.package,replace_uninitialized=args.replace_uninitialized,replace_stopped=args.replace_stopped)))
