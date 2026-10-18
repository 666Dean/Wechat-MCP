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

def install(package,*,replace_uninitialized=False,replace_stopped=False):
    if replace_uninitialized and replace_stopped:raise RuntimeError('choose one update workflow')
    with ExitStack() as stack:
        if replace_stopped:
            current=json.loads((BASE/'AXR Authority.app/Contents/Resources/deployment.json').read_bytes())['deployment']
            from axr.host import Lease
            stack.enter_context(Lease(Path.home()/'.stellaria-axr'/'leases',['journal',str(Path(current['state']))]))
        return _install(package,replace_uninitialized=replace_uninitialized,replace_stopped=replace_stopped)

def _install(package,*,replace_uninitialized=False,replace_stopped=False):
    if sys.platform!='darwin':raise RuntimeError('macOS required')
    package=Path(package).resolve(strict=True)
    manifest=json.loads((package/'package-review.json').read_bytes())['files']
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
        current=json.loads((BASE/'AXR Authority.app/Contents/Resources/deployment.json').read_bytes())['deployment']
        proposed=json.loads((package/'AXR Authority.app/Contents/Resources/deployment.json').read_bytes())['deployment']
        from axr.initialization import empty_initialization
        endpoint=Path(current['endpoint'])
        if current!=proposed or endpoint.exists() or endpoint.is_symlink():
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
