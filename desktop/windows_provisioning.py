# SPDX-License-Identifier: MIT
"""Prepare Windows setup metadata, never parse raw credential file contents."""
import json,os,sys
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,canonical,digest
from .provisioning import account_inventory,regular,fingerprint

def native_provider(candidate):
    from scripts.windows_runtime import imports
    path=regular(Path(candidate).absolute(),512*1024**2)
    if path.suffix.lower()!='.exe':raise AXRError('setup_windows_native_codex_required')
    try:dependencies=imports(path)
    except ValueError:raise AXRError('setup_windows_native_codex_required') from None
    system=Path(os.environ['SystemRoot'])/'System32'
    if any(not n.startswith(('api-ms-','ext-ms-')) and not (system/n).is_file() for n in dependencies):
        raise AXRError('setup_codex_runtime_not_self_contained')
    return path

def credential_source(root,shards,credential,*,index=False,key_mode='file'):
    credential=regular(credential,128*1024 if index else 65536)
    if index:
        metadata=json.loads(credential.read_bytes())
        if (metadata.get('version')!=1 or metadata.get('account_root')!=str(Path(root).absolute()) or
            not isinstance(metadata.get('namespace'),str) or not metadata['namespace'].startswith('Stellaria.AXR.') or
            any(metadata.get('keys',{}).get(Path(s['path']).relative_to(root).as_posix(),{}).get('key_reference')!=s['key_reference'] for s in shards)):
            raise AXRError('setup_credential_index_mismatch')
        return {'legacy_namespace':metadata['namespace']}
    if key_mode not in ('file','raw','password'):raise AXRError('setup_credential_mode_required')
    source={'path':str(credential),'sha256':fingerprint(credential,65536)}
    if key_mode!='file':source['key_mode']=key_mode
    return {'credential_import':source}

def configuration(root,account,credential,provider,workspace,*,index=False,key_mode='file',navigation=None,package=None,admission_trust=None):
    if sys.platform!='win32':raise AXRError('windows_setup_required')
    from .windows_setup import private_request_directory
    from axr_applications.provider_trust import prepare_public_ca_bundle
    owner=json.loads(native.process_identity(os.getpid()))['user']
    shards=account_inventory(root,account);provider=native_provider(provider);workspace=private_request_directory(workspace,owner)
    ca=prepare_public_ca_bundle(workspace/'ca-bundle.pem');auth=regular(Path.home()/'.codex/auth.json',1024**2)
    install=Path(native.windows_installation_root());data=Path(native.windows_data_root())
    identity={'platform':'wechat','account_id':account,'conversation_id':account}
    application={'account_id':account,'resources':[identity],
        'conversations':[{'conversation_id':account,'display_name':'本人','data_class':'personal'}],
        'credential_namespace':'Stellaria.AXR.WeChat.Native.'+digest([str(Path(root).absolute()),account]),'shards':shards,
        'sqlcipher_library':'@resources/bin/sqlcipher.dll','navigation_helper':str(install/'wechat-uia.exe'),
        'codex_provider':{'binary':'@resources/provider/codex.exe','sha256':fingerprint(provider,512*1024**2),
            'auth_file':str(auth),'workspace':str(data/'source'),'tls_bundle':'@resources/provider/ca-bundle.pem','tls_sha256':ca['sha256']}}
    value={'state':str(data/'state/wechat'),'endpoint':r'\\.\pipe\Stellaria.AXR.WeChat.'+digest([owner,account])[:32],
        'owner_user':owner,'application':application}
    if navigation is not None:
        from axr_applications.windows_navigation import prepare
        from scripts.install_authority_windows import review
        if package is None:raise AXRError('windows_navigation_package_required')
        manifest=review(package)
        application['reply_navigation']=prepare(navigation,account=account,helper=install/'wechat-uia.exe',
            helper_sha=manifest['files']['wechat-uia.exe'],endpoint=value['endpoint'])
    value.update(credential_source(root,shards,credential,index=index,key_mode=key_mode))
    result={'version':2,'application_module':'axr_applications.wechat','deployment':value}
    assets={'codex':provider,'ca':Path(ca['path'])}
    if admission_trust is not None:
        from axr_applications.windows_admission import trust_keys
        from axr_applications.windows_navigation import read_json
        trust_keys(read_json(admission_trust,4096))
        application['admission_trust_sha256']=fingerprint(admission_trust,4096)
        assets['admission_trust']=Path(admission_trust)
    if len(canonical(result))>32768:raise AXRError('setup_account_budget')
    return result,assets

def payload_location():
    from scripts.install_authority_windows import review
    root=Path(__file__).parent.parent/'authority-components'
    review(root)
    return root
