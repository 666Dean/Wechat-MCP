#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Register the initialized fixed authority as a per-user macOS service.

Registration starts no authorization, restores no consent and never launches a
model. Normal incoming scheduling starts only after an owner hardware approval.
"""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

BASE=Path('/Library/Application Support/Stellaria AXR')
LABEL='org.stellaria.axr.authority'

def register():
    if sys.platform!='darwin':raise RuntimeError('macOS required')
    from axr.platform.macos_application import register_bundle
    register_bundle(BASE/'AXR Authority.app')
    config=json.loads((BASE/'AXR Authority.app/Contents/Resources/deployment.json').read_bytes())['deployment']
    state=Path(config['state']);endpoint=Path(config['endpoint'])
    if not (state/'policy.sealed.json').is_file():raise RuntimeError('owner_initialization_required')
    endpoint.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    st=endpoint.parent.lstat()
    if endpoint.parent.is_symlink() or st.st_uid!=os.getuid() or st.st_mode&0o077:raise RuntimeError('private_endpoint_required')
    runtime=state/'service-runtime';runtime.mkdir(mode=0o700,exist_ok=True)
    agent=Path.home()/'Library/LaunchAgents'/ (LABEL+'.plist');agent.parent.mkdir(parents=True,exist_ok=True)
    if agent.is_symlink():raise RuntimeError('launch_agent_link_rejected')
    value={'Label':LABEL,'ProgramArguments':[str(BASE/'AXR Authority.app/Contents/MacOS/axr-authority'),'--serve'],
        'RunAtLoad':False,'KeepAlive':False,'ProcessType':'Interactive','LimitLoadToSessionType':'Aqua',
        'StandardOutPath':str(runtime/'service.out'),'StandardErrorPath':str(runtime/'service.err'),
        'Umask':0o077}
    raw=plistlib.dumps(value)
    if agent.exists() and agent.read_bytes()!=raw:raise RuntimeError('existing_launch_agent_requires_review')
    agent.write_bytes(raw);agent.chmod(0o600)
    domain='gui/'+str(os.getuid())
    probe=subprocess.run(['/bin/launchctl','print',domain+'/'+LABEL],capture_output=True)
    if probe.returncode:subprocess.run(['/bin/launchctl','bootstrap',domain,str(agent)],check=True,capture_output=True)
    subprocess.run(['/bin/launchctl','kickstart',domain+'/'+LABEL],check=True,capture_output=True)
    return {'registered':True,'authorization_restored':False}

if __name__=='__main__':print(json.dumps(register()))
