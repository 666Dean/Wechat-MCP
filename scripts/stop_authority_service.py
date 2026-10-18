#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stop the fixed macOS service without credentials or permission expansion."""
import errno,json,os,re,signal,socket,stat,subprocess,sys,time
from pathlib import Path

BASE=Path('/Library/Application Support/Stellaria AXR')
LABEL='org.stellaria.axr.authority'

def stop():
    if sys.platform!='darwin':raise RuntimeError('macOS required')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from axr.ipc import process_identity
    from desktop.authority_client import control
    config=json.loads((BASE/'AXR Authority.app/Contents/Resources/deployment.json').read_bytes())['deployment']
    label='gui/'+str(os.getuid())+'/'+LABEL
    info=subprocess.run(['/bin/launchctl','print',label],capture_output=True,text=True,check=True).stdout
    match=re.search(r'^\s*pid = ([0-9]+)$',info,re.M)
    if not match:raise RuntimeError('registered authority is not running')
    pid=int(match[1]);actual=process_identity(pid)
    if (actual.get('image')!=str(BASE/'AXR Authority.app/Contents/MacOS/axr-authority') or
        actual.get('signature_valid') is not True or actual.get('hardened_runtime') is not True or
        actual.get('signing_id')!=LABEL or actual.get('user')!=process_identity(os.getpid())['user']):
        raise RuntimeError('registered authority identity mismatch')
    control('stop')
    endpoint=Path(config['endpoint']);before=endpoint.lstat()
    if not stat.S_ISSOCK(before.st_mode) or before.st_uid!=os.getuid():raise RuntimeError('private authority socket required')
    if process_identity(pid)!=actual:raise RuntimeError('authority process changed')
    subprocess.run(['/bin/launchctl','kill','SIGTERM',label],capture_output=True,check=True)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        try:os.kill(pid,0)
        except ProcessLookupError:break
        time.sleep(.1)
    else:raise RuntimeError('authority shutdown incomplete; installation refused')
    # Old hosts predate graceful SIGTERM handling. Remove only the same owned
    # socket after its exact server birth has exited and no listener remains.
    if endpoint.exists() or endpoint.is_symlink():
        after=endpoint.lstat()
        if ((after.st_dev,after.st_ino)!=(before.st_dev,before.st_ino) or
            not stat.S_ISSOCK(after.st_mode) or after.st_uid!=os.getuid()):raise RuntimeError('authority endpoint changed')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
            probe.settimeout(.5)
            try:probe.connect(str(endpoint))
            except OSError as exc:
                if exc.errno not in (errno.ECONNREFUSED,errno.ENOENT):raise
            else:raise RuntimeError('authority endpoint still has a listener')
        if endpoint.lstat().st_ino!=before.st_ino:raise RuntimeError('authority endpoint changed')
        endpoint.unlink()
    return {'stopped':True,'authority_revoked':True,'state_retained':True}

if __name__=='__main__':print(json.dumps(stop()))
