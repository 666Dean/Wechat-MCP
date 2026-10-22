# SPDX-License-Identifier: MIT
"""First-run local deployment. Never extracts WeChat keys or grants authority.

Only metadata/salts and an explicit credential-file fingerprint are prepared by
the desktop. The authenticated native authority alone imports/validates keys.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
from axr.aet import AXRError,canonical,digest

BASE=Path('/Library/Application Support/Stellaria AXR')
BUNDLES=('AXR Authority.app','AXR Owner.app','AXR MCP.app')

def regular(path,maximum):
    path=Path(path).absolute()
    for node in (path,*path.parents):
        if node.is_symlink() or getattr(node.lstat(),'st_file_attributes',0)&0x400:raise AXRError('setup_path_redirected')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=maximum:
        raise AXRError('setup_file_invalid')
    return path

def fingerprint(path,maximum):
    path=regular(path,maximum);before=path.stat()
    # The desktop receives a fingerprint, never the plaintext credential file.
    if os.name=='nt':
        import ctypes
        system=ctypes.create_unicode_buffer(32768)
        length=ctypes.windll.kernel32.GetSystemDirectoryW(system,len(system))
        if not 0<length<len(system):raise AXRError('setup_hash_utility_unavailable')
        result=subprocess.run([str(Path(system.value)/'certutil.exe'),'-hashfile',str(path),'SHA256'],
            capture_output=True,timeout=20,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        # Localized headings and paths are ignored. Only one complete hash is accepted.
        hashes=[line.strip().replace(b' ',b'').lower() for line in result.stdout.splitlines()]
        hashes=[line for line in hashes if re.fullmatch(b'[0-9a-f]{64}',line)]
        if len(hashes)!=1:raise AXRError('setup_hash_result_invalid')
        value=hashes[0].decode('ascii')
    else:
        result=subprocess.run(['/usr/bin/shasum','-a','256',str(path)],capture_output=True,timeout=20,check=True)
        value=result.stdout.split(b' ',1)[0].decode('ascii')
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    if not re.fullmatch('[0-9a-f]{64}',value) or identity(before)!=identity(path.stat()):raise AXRError('setup_file_changed')
    return value

def account_inventory(root,account):
    if not re.fullmatch('[A-Za-z0-9_.-]{1,128}',account):raise AXRError('setup_account_id_required')
    root=Path(root).absolute()
    if root.name!='db_storage' or not root.is_dir():raise AXRError('setup_account_folder_required')
    for node in (root,*root.parents):
        if node.is_symlink():raise AXRError('setup_path_redirected')
    parts=root.parent.name.split('_')
    if account not in ['_'.join(parts[:i]) for i in range(1,len(parts)+1)]:raise AXRError('setup_account_folder_mismatch')
    names=['contact/contact.db','session/session.db','general/general.db']
    messages=sorted(p for p in (root/'message').glob('message_*.db') if re.fullmatch(r'message_\d+\.db',p.name))
    if not 1<=len(messages)<=125:raise AXRError('setup_message_databases_required')
    names += [p.relative_to(root).as_posix() for p in messages]
    shards=[]
    for name in names:
        path=regular(root/name,2**40)
        with path.open('rb') as stream:salt=stream.read(16)
        if len(salt)!=16 or salt==b'SQLite format 3\0':raise AXRError('setup_database_format_unqualified')
        salt=salt.hex()
        shards.append({'id':path.stem,'path':str(path),'role':Path(name).parts[0],
                       'salt':salt,'key_reference':'wcdb:'+digest([str(path),salt]),'cipher_profile':'wcdb4-raw'})
    return shards

def payload_location():
    root=Path(__file__).parent.parent
    archive=root/'authority-payload.tar.gz'
    manifest=root/'authority-payload.json'
    if not archive.is_file() or not manifest.is_file():raise AXRError('setup_components_missing')
    review=json.loads(manifest.read_bytes())
    if review.get('version')!=1 or fingerprint(archive,1024**3)!=review.get('sha256'):
        raise AXRError('setup_components_changed')
    return archive,review

def unpack_payload(archive,destination):
    destination=Path(destination)
    destination.mkdir(mode=0o700,parents=True,exist_ok=False)
    with tarfile.open(archive,'r:gz') as source:
        files=source.getmembers()
        if len(files)>12000 or sum(m.size for m in files)>2*1024**3:raise AXRError('setup_components_budget')
        for item in files:
            name=Path(item.name)
            if (name.is_absolute() or '..' in name.parts or not name.parts or
                name.parts[0] not in (*BUNDLES,'package-review.json') or not (item.isfile() or item.isdir())):
                raise AXRError('setup_components_path_invalid')
        source.extractall(destination,members=files,filter='data')
    return destination

def native_provider(candidate):
    # Shell installs may expose a symlink or JS launcher. Pin the resolved
    # signed native image; never copy a launcher with undeclared dependencies.
    candidates=[Path(candidate),Path('/Applications/Codex.app/Contents/Resources/codex'),
                Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')]
    for value in candidates:
        try:
            value=regular(value.resolve(strict=True),1024**3)
            subprocess.run(['/usr/bin/codesign','--verify','--strict',str(value)],capture_output=True,check=True)
            libraries=subprocess.run(['/usr/bin/otool','-L',str(value)],capture_output=True,text=True,check=True).stdout.splitlines()[1:]
            if not libraries or any(not line.strip().startswith(('/System/Library/','/usr/lib/')) for line in libraries):continue
            return value
        except (OSError,AXRError,subprocess.CalledProcessError):continue
    raise AXRError('setup_codex_runtime_not_self_contained')

def configuration(root,account,credential,provider,workspace,*,index=False,base=BASE):
    shards=account_inventory(root,account)
    provider=native_provider(provider)
    home=Path.home();workspace=Path(workspace)
    from axr.storage import private_directory
    private_directory(workspace)
    state=home/'.stellaria-axr'/'wechat'
    private_directory(state)
    inference=state/'source';private_directory(inference)
    from axr_applications.provider_trust import prepare_public_ca_bundle
    ca=prepare_public_ca_bundle(workspace/'ca-bundle.pem')
    auth=regular(home/'.codex/auth.json',1024**2)
    identity={'platform':'wechat','account_id':account,'conversation_id':account}
    application={'account_id':account,'resources':[identity],
        'conversations':[{'conversation_id':account,'display_name':'本人','data_class':'personal'}],
        'credential_namespace':'Stellaria.AXR.WeChat.Native.'+digest([str(root),account]),
        'shards':shards,'sqlcipher_library':'@resources/../Frameworks/libwechat-sqlcipher.dylib',
        'navigation_helper':'@resources/bin/wechat-navigation',
        'codex_provider':{'binary':str(base/'Codex Provider/codex'),'sha256':fingerprint(provider,1024**3),
            'auth_file':str(auth),'workspace':str(inference),'tls_bundle':str(base/'ca-bundle.pem'),'tls_sha256':ca['sha256']}}
    value={'state':str(state),'endpoint':str(home/'.stellaria-axr'/'wechat.sock'),'application':application}
    credential=regular(credential,128*1024 if index else 65536)
    if index:
        data=json.loads(credential.read_bytes())
        if (data.get('version')!=1 or data.get('account_root')!=str(Path(root).absolute()) or
            not isinstance(data.get('namespace'),str) or not data['namespace'].startswith('Stellaria.AXR.') or
            any(data.get('keys',{}).get(str(Path(s['path']).relative_to(root)).replace(os.sep,'/'),{}).get('key_reference')!=s['key_reference'] for s in shards)):
            raise AXRError('setup_credential_index_mismatch')
        value['legacy_namespace']=data['namespace']
    else:value['credential_import']={'path':str(credential),'sha256':fingerprint(credential,65536)}
    config={'version':2,'application_module':'axr_applications.wechat','deployment':value}
    if len(canonical(config))>32768:raise AXRError('setup_account_budget')
    return config,{'codex':provider,'ca':Path(ca['path'])}
