# SPDX-License-Identifier: MIT
"""Interactive owner utility. Not an MCP tool and never invoked by the service.

Keys go directly to the initialized AXR owner's OS credential store. The index
contains paths/references/salts only. No plaintext export, process attach or SIP
change. Optional macOS observation uses a disposable, explicitly accepted copy.
"""
import argparse
import getpass
import json
import os
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError, canonical, digest
from axr.host import Lease
from axr.owner import authenticate
from axr.policy import OwnerStore
from .wcdb import CipherConnection
from .wcdb_keys import inventory, provision_verified, qualify_contacts


def save_index(store, root, keys):
    value={'version':1,'account_root':str(root),'namespace':store.secrets.namespace,'keys':keys}
    if not native.durable_write(str(store.directory/'wcdb-local-index.json'),canonical(value)):
        raise AXRError('wcdb_index_durable_write_failed')


def verified_cached(store, root, rows):
    path=store.directory/'wcdb-local-index.json'
    if not path.exists():return {}
    if path.is_symlink() or path.stat().st_size>128*1024:raise AXRError('wcdb_index_invalid')
    value=json.loads(path.read_bytes())
    if value.get('version')!=1 or value.get('account_root')!=str(root) or value.get('namespace')!=store.secrets.namespace:
        raise AXRError('wcdb_index_account_or_owner_mismatch')
    # Index cannot introduce a key into policy: HMAC revalidation is mandatory.
    result={}
    from .wcdb_keys import verified_raw_key
    for rel,item in value['keys'].items():
        row=rows.get(rel)
        if row and row['salt']==item.get('salt'):
            expected='wcdb:'+digest([str(row['path']),row['salt']])
            if item.get('key_reference')!=expected:raise AXRError('wcdb_key_reference_mismatch')
            key=store.secrets.get(expected)
            if verified_raw_key(key,row['page']):
                # Index fields cannot override a qualified shard path/profile.
                result[rel]={'key_reference':expected,'salt':row['salt'],'cipher_profile':'wcdb4-raw'}
    return result


def installed_signature(app):
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True,capture_output=True)
    signature=subprocess.run(['codesign','-dv','--verbose=4',str(app)],check=True,capture_output=True).stderr
    if b'Identifier=com.tencent.xinWeChat\n' not in signature or b'TeamIdentifier=5A4RE8SF68\n' not in signature:
        raise AXRError('installed_vendor_signature_unqualified')
    return signature


def observe_mac(store, root, rows, keys, observer, *, timeout=120):
    if sys.platform!='darwin':raise AXRError('startup_observer_macos_only')
    required={rel for rel in rows if rel in {'contact/contact.db','session/session.db'} or
              (Path(rel).parent==Path('message') and Path(rel).stem.removeprefix('message_').isdigit())}
    if not {'contact/contact.db','session/session.db'}<=required:raise AXRError('account_layout_unqualified')
    if required<=keys.keys():return keys
    app=Path('/Applications/WeChat.app')
    before=installed_signature(app)
    if subprocess.run(['pgrep','-x','WeChat'],capture_output=True).returncode==0:
        raise AXRError('quit_installed_wechat_normally_before_owner_capture')
    # Once the original is verified and confirmed quit, restore it even if
    # preparing/signing the disposable copy fails before Popen returns a child.
    try:
        observer=Path(observer).absolute()
        if observer.is_symlink() or not observer.is_file():raise AXRError('owner_built_observer_required')
        child=None
        # Temporary directory is private, copy never becomes the installed application.
        with tempfile.TemporaryDirectory(prefix='wcdb-owner-',dir=store.directory) as temporary:
            stage=Path(temporary);stage.chmod(0o700);copy=stage/'WeChat-owner-copy.app'
            fifo=stage/'keys.fifo';fd=None
            try:
                subprocess.run(['ditto',str(app),str(copy)],check=True,capture_output=True,timeout=180)
                entitlements=stage/'entitlements.plist'
                entitlements.write_text('<?xml version="1.0"?><plist version="1.0"><dict>'
                    '<key>com.apple.security.cs.disable-library-validation</key><true/>'
                    '<key>com.apple.security.cs.allow-dyld-environment-variables</key><true/>'
                    '</dict></plist>');entitlements.chmod(0o600)
                subprocess.run(['codesign','--force','--deep','--sign','-','--entitlements',str(entitlements),str(copy)],
                               check=True,capture_output=True,timeout=180)
                os.mkfifo(fifo,0o600);fd=os.open(fifo,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
                env={k:v for k,v in os.environ.items() if not k.startswith(('DYLD_','AXR_OWNER_'))}
                env.update(DYLD_INSERT_LIBRARIES=str(observer),AXR_OWNER_KEY_FIFO=str(fifo))
                child=subprocess.Popen([str(copy/'Contents/MacOS/WeChat')],env=env,cwd=stage,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                deadline=time.monotonic()+timeout;buffer=b'';frames=0
                while time.monotonic()<deadline and child.poll() is None:
                    select.select([fd],[],[],.2)
                    try:chunk=os.read(fd,4096)
                    except BlockingIOError:chunk=b''
                    if not chunk:time.sleep(.05);continue
                    buffer+=chunk
                    if len(buffer)>8192:raise AXRError('owner_key_channel_budget')
                    while len(buffer)>=52:
                        frame,buffer=buffer[:52],buffer[52:];frames+=1
                        if frames>128 or frame[:4]!=b'AXK1':raise AXRError('owner_key_channel_invalid')
                        salt,key=frame[4:20],frame[20:52]
                        for rel,row in rows.items():
                            if rel not in keys and row['page'][:16]==salt:
                                try:item=provision_verified(root,rel,key,store.secrets,row['salt'])
                                except AXRError as exc:
                                    if str(exc)=='candidate_key_hmac_rejected':continue
                                    raise
                                keys[rel]=item;save_index(store,root,keys)
                        del key,frame
                    if required<=keys.keys():break
                if not required<=keys.keys():raise AXRError('startup_capture_incomplete_keys_preserved')
            finally:
                try:
                    if child is not None and child.poll() is None:
                        child.terminate()
                        try:child.wait(timeout=10)
                        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
                finally:
                    # Retain the reader until its writer exits, avoiding a cleanup
                    # race that could deliver SIGPIPE inside the temporary client.
                    if fd is not None:os.close(fd)
    finally:
        if installed_signature(app)!=before:raise AXRError('installed_application_signature_changed')
        # A person may have restarted the original during setup. Never spawn a
        # duplicate or restore an observer environment into the installed program.
        if subprocess.run(['pgrep','-x','WeChat'],capture_output=True).returncode!=0:
            env={k:v for k,v in os.environ.items() if not k.startswith(('DYLD_','AXR_OWNER_'))}
            subprocess.Popen([str(app/'Contents/MacOS/WeChat')],env=env,stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,start_new_session=True)
    return keys


def main():
    parser=argparse.ArgumentParser(description='Local owner WCDB setup; never use as an MCP tool')
    parser.add_argument('--state',required=True);parser.add_argument('--helper',required=True)
    parser.add_argument('--account-root',required=True,help='Exact owner-selected db_storage directory')
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('import-key');p.add_argument('--database',required=True)
    p=commands.add_parser('observe-mac');p.add_argument('--observer',required=True)
    p.add_argument('--allow-temporary-copy',action='store_true',required=True)
    p=commands.add_parser('qualify');p.add_argument('--sqlcipher-library',required=True)
    p.add_argument('--account-id',required=True);p.add_argument('--contact',action='append',required=True)
    args=parser.parse_args()
    try:
        # Mutations require a real owner terminal and OS authentication, never stdin secrets from an agent.
        if not sys.stdin.isatty() or not sys.stdout.isatty():raise AXRError('owner_interactive_terminal_required')
        root=Path(args.account_root).absolute();rows=inventory(root)
        print(json.dumps({'operation':args.command,'encrypted_databases':len(rows),'keys_to_os_store':True}))
        if args.command=='observe-mac':
            print('A disposable copy will be ad-hoc signed and started with a KDF observer. '
                  'The installed app, SIP and its signature are preserved. Quit installed WeChat normally first.')
        authenticate(args.helper)
        store=OwnerStore(args.state)
        try:
            with Lease(Path.home()/'.stellaria-axr'/'leases',['owner-wcdb',str(root)]):
                keys=verified_cached(store,root,rows)
                if args.command=='import-key':
                    if args.database not in rows:raise AXRError('selected_encrypted_database_missing')
                    raw=getpass.getpass('32-byte hex WCDB key (hidden, local only): ')
                    try:key=bytes.fromhex(raw)
                    except ValueError:raise AXRError('invalid_database_key')
                    keys[args.database]=provision_verified(root,args.database,key,store.secrets,rows[args.database]['salt'])
                    del raw,key;save_index(store,root,keys)
                elif args.command=='observe-mac':
                    # The installed client is shared across account roots.
                    with Lease(Path.home()/'.stellaria-axr'/'leases',['owner-wcdb-macos-client']):
                        keys=observe_mac(store,root,rows,keys,args.observer)
                else:
                    item=keys.get('contact/contact.db')
                    if not item:raise AXRError('verified_contact_key_required')
                    bound=qualify_contacts(rows['contact/contact.db']['path'],args.sqlcipher_library,
                        store.secrets.get(item['key_reference']),args.account_id,args.contact,account_root=root)
                    shards=[]
                    for rel,item in keys.items():
                        if Path(rel).parent==Path('message') and Path(rel).stem.removeprefix('message_').isdigit():
                            db=CipherConnection(rows[rel]['path'],args.sqlcipher_library,
                                store.secrets.get(item['key_reference']).hex(),item['cipher_profile'])
                            db.close();shards.append({'path':str(rows[rel]['path']),**item})
                    if not shards:raise AXRError('verified_message_shard_required')
                    template={'account_id':args.account_id,'conversations':bound,'mode':'wcdb',
                        'database':{'sqlcipher_library':str(Path(args.sqlcipher_library).resolve(strict=True)),'shards':shards}}
                    if not native.durable_write(str(store.directory/'wcdb-qualified-local.json'),canonical(template)):
                        raise AXRError('qualified_binding_durable_write_failed')
                    print(json.dumps({'qualified_private_contacts':len(bound),'readonly_message_shards':len(shards)}))
                print(json.dumps({'hmac_verified_keys':len(keys),'encrypted_databases':len(rows)}))
        finally:store.close()
    except AXRError as exc:
        parser.exit(1,str(exc)+'\n')
    except (OSError,ValueError,subprocess.SubprocessError):
        # Subprocess diagnostics may contain private paths/account console output.
        parser.exit(1,'Local WCDB setup failed; no secret or subprocess output is reported.\n')


if __name__=='__main__':main()
