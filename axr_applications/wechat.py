# SPDX-License-Identifier: MIT
"""WeChat registration for the independently installed AXR authority.

Setup imports existing WCDB credentials natively after owner authentication and
creates a NEW ledger. It never restores legacy grants or pending send attempts.
All application actions still require a signed TaskContract and an AET.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import time
from dataclasses import asdict
from axr import _axr_native as native
from axr.aet import AXRError, Action, Resource, canonical, digest
from axr.authority import AuthorityKernel
from axr.authority_server import AuthorityServer
from axr.deployment import OwnerDeployment
from axr.ipc import PeerContext, PeerRegistry, process_identity,windows_client_sandbox
from axr.policy import OwnerStore
from axr.release import ReleaseGate
from axr.security import SecurityService
from .wechat_service import WeChatKernel,WeChatService,PRINCIPAL,BOUNDARY

BASE=Path('/Library/Application Support/Stellaria AXR')

from .wechat_targets import private_recipient

def resources_root():
    actual=process_identity(os.getpid());image=Path(actual['image'])
    return image.parent/'runtime' if os.name=='nt' else image.parent.parent/'Resources'

def _configuration(value):
    if type(value) is not dict or set(value)-{'state','endpoint','application','legacy_namespace','credential_import','owner_public_key','owner_user'} or not {'state','endpoint','application'}<=set(value):raise AXRError('wechat_deployment_configuration_invalid')
    if 'owner_user' in value and (os.name!='nt' or type(value['owner_user']) is not str or
            re.fullmatch(r'S-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+',value['owner_user']) is None):raise AXRError('wechat_windows_owner_user_invalid')
    if value.get('legacy_namespace') and value.get('credential_import'):raise AXRError('wechat_deployment_configuration_invalid')
    if 'credential_import' in value:
        source=value['credential_import']
        fields={'path','sha256'}
        if os.name=='nt' and type(source) is dict and 'key_mode' in source:fields.add('key_mode')
        if (type(source) is not dict or set(source)!=fields or not Path(source['path']).is_absolute()
            or re.fullmatch('[0-9a-f]{64}',source['sha256']) is None):raise AXRError('wechat_deployment_configuration_invalid')
        if 'key_mode' in source and source['key_mode'] not in ('raw','password'):raise AXRError('wechat_deployment_configuration_invalid')
    root=resources_root();application=dict(value['application'])
    if type(application.get('manual_approval_required',True)) is not bool:raise AXRError('wechat_approval_setting_invalid')
    def asset(value):
        if not isinstance(value,str):raise AXRError('wechat_deployment_asset_invalid')
        if not value.startswith('@resources/'):return value
        relative=value[len('@resources/'):]
        from pathlib import PurePosixPath
        # macOS signs dylibs in Contents/Frameworks. This one fixed sibling is
        # part of the reviewed bundle; arbitrary parent traversal stays denied.
        if os.name!='nt' and relative=='../Frameworks/libwechat-sqlcipher.dylib':
            path=(root/relative).resolve(strict=True)
            if path.parent!=(root.parent/'Frameworks').resolve(strict=True) or not path.is_file():
                raise AXRError('wechat_deployment_asset_invalid')
            return str(path)
        if (not relative or '\\' in relative or PurePosixPath(relative).is_absolute() or
                any(part in ('.','..') for part in relative.split('/'))):
            raise AXRError('wechat_deployment_asset_invalid')
        path=(root/relative).resolve(strict=True)
        if not path.is_relative_to(root.resolve(strict=True)) or not path.is_file():
            raise AXRError('wechat_deployment_asset_invalid')
        return str(path)
    for field in ('sqlcipher_library','navigation_helper'):
        if field in application:application[field]=asset(application[field])
    if 'codex_provider' in application:
        provider=dict(application['codex_provider'])
        for field in ('binary','tls_bundle'):
            if field in provider:provider[field]=asset(provider[field])
        application['codex_provider']=provider
    state=Path(value['state'])
    if not state.is_absolute() or str(state)==str(Path.home()) or state.is_symlink():raise AXRError('wechat_deployment_state_invalid')
    endpoint=value['endpoint']
    if not isinstance(endpoint,str):raise AXRError('wechat_deployment_endpoint_invalid')
    if os.name=='nt':
        prefix='\\\\.\\pipe\\Stellaria.AXR.'
        if not endpoint.startswith(prefix) or re.fullmatch(r'[A-Za-z0-9_.-]{1,120}',endpoint[len(prefix):]) is None:
            raise AXRError('wechat_deployment_endpoint_invalid')
    elif not Path(endpoint).is_absolute() or len(os.fsencode(endpoint))>100:
        raise AXRError('wechat_deployment_endpoint_invalid')
    if 'reply_navigation' in application:
        navigation=dict(application['reply_navigation'])
        navigation['helper']=asset(navigation['helper'])
        if navigation['endpoint']!=endpoint or navigation['helper']!=application.get('navigation_helper'):
            raise AXRError('wechat_deployment_navigation_mismatch')
        application['reply_navigation']=navigation
    if not application.get('resources') or len(application['resources'])>4096:raise AXRError('wechat_deployment_resources_required')
    seen=set()
    for row in application['resources']:
        resource=Resource(**row)
        if resource.platform!='wechat' or resource.account_id!=application['account_id'] or resource.key in seen:raise AXRError('wechat_deployment_resource_mismatch')
        seen.add(resource.key)
        identity=resource.conversation_id
        if os.name!='nt' and (not private_recipient(identity)):raise AXRError('wechat_private_resource_required')
    return {**value,'state':str(state),'application':application}

def owner_setup_review(value):
    config=_configuration(value)
    if os.name=='nt' and 'owner_user' not in config:raise AXRError('wechat_windows_owner_user_required')
    if os.name!='nt' and ('conversations' not in config['application'] or 'codex_provider' not in config['application']):raise AXRError('wechat_application_routes_required')
    return {'application':'WeChat MCP','fresh_state':config['state'],'endpoint':config['endpoint'],
        'credential_import':'native OS store to native OS store; keys never returned to Python',
        'resources':config['application']['resources'],'shard_count':len(config['application']['shards']),
        'automatic_reply_enabled':False,'legacy_permissions_restored':False,'vendor_certificate_required':False,
        'manual_approval_required':config['application'].get('manual_approval_required',True)}

def authenticate_owner_setup(value):
    config=_configuration(value);directory=Path(config['state'])
    from axr.initialization import empty_initialization
    if not empty_initialization(directory):raise AXRError('wechat_fresh_authority_state_required')
    if os.name=='nt':
        from .windows_enrollment import exchange
        _build_assets(config['application']) # Reject helper escapes before any owner key operation.
        build=review_windows_build(config['application'])
        challenge={'version':2,'kind':'wechat-owner-enrollment','configuration_digest':digest(config),
            'build_digest':build['build'],'nonce':secrets.token_hex(32),'expires':time.time()+180}
        response,actual=exchange(config,challenge,resources_root())
        if review_windows_build(config['application'])!=build:raise AXRError('wechat_owner_build_changed_during_review')
        return {**response,'identity':actual}
    return _hardware_enrollment(digest(config))


def review_windows_build(application):
    return OwnerDeployment.review(resources_root().parent,_build_assets(application))


def authenticate_owner_recovery(value):
    if os.name!='nt':raise AXRError('wechat_windows_recovery_required')
    config=_configuration(value)
    from axr.initialization import empty_initialization
    if not empty_initialization(config['state']) or (Path(config['state'])/'policy.sealed.json').exists():
        raise AXRError('wechat_orphan_recovery_requires_empty_setup')
    try:(resources_root()/'owner-key.json').lstat()
    except FileNotFoundError:pass
    else:raise AXRError('wechat_owner_orphan_recovery_requires_missing_pin')
    from .windows_enrollment import exchange
    build=review_windows_build(config['application'])
    challenge={'version':2,'kind':'wechat-owner-orphan-recovery','configuration_digest':digest(config),
        'build_digest':build['build'],'nonce':secrets.token_hex(32),'expires':time.time()+180}
    response,actual=exchange(config,challenge,resources_root())
    if review_windows_build(config['application'])!=build:raise AXRError('wechat_owner_build_changed_during_review')
    return {**response,'identity':actual}


def replace_uninitialized_source(value,source,runtime_root):
    """Correct only a credential reference before any approved configuration.

    Called solely by the fixed System one-shot entry after bootstrap absence
    was checked natively. Preserve account, assets, state, keys and all files.
    """
    if os.name!='nt' or type(source) is not dict or set(source) not in ({'credential_import'},{'legacy_namespace'}):
        raise AXRError('windows_setup_source_request_invalid')
    if 'legacy_namespace' in source and (type(source['legacy_namespace']) is not str or
        not source['legacy_namespace'].startswith('Stellaria.AXR.') or len(source['legacy_namespace'])>200):
        raise AXRError('windows_setup_source_request_invalid')
    candidate={**{k:v for k,v in value.items() if k not in ('credential_import','legacy_namespace')},**source}
    config=_configuration(candidate);directory=Path(config['state'])
    if directory.is_symlink() or directory.is_junction():raise AXRError('windows_setup_source_history_present')
    for path in (directory/'policy.sealed.json',Path(runtime_root)/'owner-key.json'):
        try:path.lstat()
        except FileNotFoundError:continue
        raise AXRError('windows_setup_source_already_reviewed')
    from axr.initialization import empty_initialization
    if directory.exists() and any(p.is_symlink() or p.is_junction() or not p.is_file() or p.stat().st_nlink!=1 for p in directory.iterdir()):
        raise AXRError('windows_setup_source_history_present')
    if not empty_initialization(directory):raise AXRError('windows_setup_source_history_present')
    if directory.exists() and any(directory.iterdir()):
        with __import__('contextlib').closing(OwnerStore(directory,authority_service=True)) as store:
            if not store.journal.verify_audit() or store.journal.checkpoint.read()['sequence']!=0:
                raise AXRError('windows_setup_source_history_present')
    return candidate

def _hardware_enrollment(configuration_digest):
    # The second process is a fixed protected owner identity. Its hardware key
    # can require user presence; the authority cannot open that private key.
    owner=BASE/'AXR Owner.app/Contents/MacOS/axr-owner'
    challenge={'version':2,'kind':'wechat-owner-enrollment','configuration_digest':configuration_digest,
               'nonce':secrets.token_hex(32),'expires':time.time()+180}
    process=subprocess.Popen([str(owner),'--owner-enroll'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        actual=process_identity(process.pid)
        if Path(actual['image'])!=owner or actual.get('signature_valid') is not True or actual.get('hardened_runtime') is not True or actual.get('signing_id')!='org.stellaria.axr.owner':raise AXRError('wechat_owner_host_identity_required')
        raw,_=process.communicate(canonical(challenge)+b'\n',timeout=180)
        if len(raw)>(300000 if os.name=='nt' else 32768) or process.returncode:raise AXRError('wechat_owner_enrollment_failed')
        response=json.loads(raw)
        if response.get('challenge')!=challenge or not native.verify_owner_signature(bytes.fromhex(response['public_key']),canonical(challenge),bytes.fromhex(response['signature'])):raise AXRError('wechat_owner_enrollment_signature_invalid')
        if os.name=='nt':
            from .windows_enrollment import trust_roots,validate_response
            validate_response(challenge,response,trust_roots(resources_root()))
    finally:
        if process.poll() is None:process.kill();process.wait()
    return {'challenge':challenge,'public_key':response['public_key'],'signature':response['signature'],'identity':actual}

def provider_build_update(original,current,*,bundled_path):
    """Only a CLI image/path change, never credentials, sources or authority.

    Accepted solely inside a stopped install plus exact hardware-signed build
    update. Does not itself approve or write anything.
    """
    if original==current:return True
    old=original.get('codex_provider');new=current.get('codex_provider')
    if type(old) is not dict or type(new) is not dict:return False
    without=lambda value,keys:{k:v for k,v in value.items() if k not in keys}
    return (without(original,{'codex_provider'})==without(current,{'codex_provider'})
        and set(old)==set(new) and without(old,{'binary','sha256'})==without(new,{'binary','sha256'})
        and new.get('binary')==str(bundled_path) and isinstance(new.get('sha256'),str)
        and re.fullmatch('[0-9a-f]{64}',new['sha256']) is not None)

def refresh_owner_build(value,bootstrap):
    """Revoke old contracts, authenticate this exact build, retain the ledger.

    Runs only in the root-owned fixed native host with its existing bootstrap.
    The journal lease excludes a live server. No action contract is issued.
    """
    if os.name=='nt':return _refresh_windows_owner_build(value,bootstrap)
    config=_configuration(value)
    if (config['state']!=bootstrap.get('state') or config['endpoint']!=bootstrap.get('endpoint') or
        Path(config['endpoint']).exists() or Path(config['endpoint']).is_symlink()):
        raise AXRError('wechat_build_update_requires_stopped_service')
    with __import__('contextlib').closing(OwnerStore(config['state'],authority_service=True)) as store:
        approved=store.config()
        current={k:v for k,v in config['application'].items() if k not in ('resources','conversations')}
        original={k:v for k,v in approved['application'].items() if k not in ('resources','conversations')}
        bundled=BASE/'AXR Authority.app/Contents/Resources/CodexCLI.app/Contents/MacOS/codex'
        if (not provider_build_update(original,current,bundled_path=bundled) or approved['owner_user']!=process_identity(os.getpid())['user'] or
            approved['owner_public_key']!=bootstrap.get('owner_public_key')):
            raise AXRError('wechat_build_update_configuration_changed')
        if current!=original:
            if (bundled.is_symlink() or not bundled.is_file() or
                hashlib.sha256(bundled.read_bytes()).hexdigest()!=current['codex_provider']['sha256']):
                raise AXRError('codex_provider_build_changed')
        signer=native.HardwareSigningKey('Stellaria.AXR.Root.v2')
        kernel,registry=_kernel(store,signer,approved['owner_public_key'])
        try:
            # Reducing authority is always permitted. An abandoned update
            # cannot leave any old contract active or resurrect a send job.
            kernel.security.revoke('kernel');kernel.integrity.persist()
            def revoked():
                return kernel.integrity.verify() and not kernel.db.execute('SELECT 1 FROM security_contracts WHERE revoked=0 LIMIT 1').fetchone()
            pins=OwnerDeployment(store.secrets,store.vault,revoke_for_update=revoked)
            assets=_build_assets(approved['application'])
            reviewed=pins.review(BASE,assets)
            enrollment=_hardware_enrollment(digest({'configuration':config,'build':reviewed}))
            def authenticated():
                return (enrollment['public_key']==approved['owner_public_key'] and
                    enrollment['identity']['user']==approved['owner_user'] and
                    enrollment['challenge']['expires']>time.time() and
                    pins.review(BASE,assets)==reviewed)
            result=pins.enroll(BASE,assets,authenticated)
            if current!=original:
                store.seal_config({**approved,'application':{**approved['application'],'codex_provider':current['codex_provider']}})
            store.journal.security_event('owner-build-update',{'build':result['build'],'authority_restored':False})
            kernel.integrity.persist()
            return {**result,'updated':True,'credentials_retained':True,'ledger_retained':True}
        finally:kernel.close()

def _build_assets(application):
    helper=Path(application['navigation_helper'])
    if os.name=='nt':
        install=resources_root().parent
        try:
            relative=helper.relative_to(install)
            if not helper.is_absolute() or '..' in relative.parts:raise ValueError()
        except ValueError:raise AXRError('wechat_deployment_native_helper_required') from None
        return [{'path':'axr-authority.exe','roles':['server','handler']},
            {'path':'axr-owner.exe','roles':['owner']},{'path':'axr-frontend.exe','roles':['client']},
            {'path':'installation-review.json','roles':['handler']},
            {'path':relative.as_posix(),'roles':['handler']}]
    return [{'path':'AXR Authority.app/Contents/MacOS/axr-authority','roles':['server','handler']},
            {'path':'AXR Owner.app/Contents/MacOS/axr-owner','roles':['owner']},
            {'path':'AXR MCP.app/Contents/MacOS/axr-frontend','roles':['client']},
            {'path':str(helper.relative_to(BASE)),'roles':['handler']}]

def initialize_owner(value, signer, enrollment=None):
    config=_configuration(value);directory=Path(config['state'])
    from axr.initialization import empty_initialization
    if not empty_initialization(directory):raise AXRError('wechat_fresh_authority_state_required')
    if enrollment is None:enrollment=authenticate_owner_setup(value)
    challenge=enrollment['challenge'];actual=enrollment['identity'];response=enrollment
    verify=native.verify_owner_signature if os.name=='nt' else native.verify_root_signature
    if challenge['configuration_digest']!=digest(config) or challenge['expires']<=time.time() or not verify(bytes.fromhex(response['public_key']),canonical(challenge),bytes.fromhex(response['signature'])):raise AXRError('wechat_owner_enrollment_signature_invalid')
    if os.name=='nt':
        from .windows_enrollment import validate_enrollment
        validate_enrollment(config,enrollment,resources_root())
        if challenge.get('kind') not in ('wechat-owner-enrollment','wechat-owner-orphan-recovery'):
            raise AXRError('wechat_owner_enrollment_signature_invalid')
    with __import__('contextlib').closing(OwnerStore(directory,provision=True,authority_service=True)) as store:
        if not store.journal.verify_audit() or store.journal.checkpoint.read()['sequence']!=0:raise AXRError('wechat_empty_initialization_checkpoint_required')
        application=config['application']
        from . import _wechat_credentials
        if config.get('legacy_namespace'):
            if os.name=='nt':
                importer=getattr(_wechat_credentials,'import_legacy_owner_credentials',None)
                if not callable(importer):raise AXRError('wechat_windows_owner_credential_migration_required')
                importer(canonical(application).decode(),config['legacy_namespace'],actual['user'])
            else:_wechat_credentials.import_legacy_credentials(canonical(application).decode(),config['legacy_namespace'])
        if config.get('credential_import'):
            if os.name=='nt' and not hasattr(_wechat_credentials,'import_owner_credentials'):
                raise AXRError('wechat_windows_owner_credential_migration_required')
            _wechat_credentials.import_owner_credentials(canonical(application).decode(),canonical(config['credential_import']).decode())
        # This first-setup metadata read is part of the authenticated setup
        # review. No message body or prior permission is imported.
        consumer=_wechat_credentials.WeChatConsumer('owner-initialization',canonical(application).decode())
        catalog=[]
        for offset in range(0,5000,1000):
            batches=json.loads(native.CredentialConsumer.use(consumer,canonical(asdict(Resource('wechat',application['account_id'],application['account_id']))).decode(),
                'database.query',canonical({'kind':'catalog','offset':offset,'limit':1000}).decode(),lambda:None))
            if len(batches)!=1:raise AXRError('wechat_contact_shard_required')
            rows=batches[0]['rows']
            for row in rows:
                identity=row['username']
                if not private_recipient(identity):continue
                catalog.append({'conversation_id':identity,'display_name':row['remark'] or row['nick_name'] or identity,'data_class':'personal'})
            if len(rows)<1000:break
        else:raise AXRError('wechat_contact_catalog_budget')
        if not catalog or len(catalog)>4096:raise AXRError('wechat_contact_catalog_budget')
        application={**application,'conversations':catalog,'resources':[asdict(Resource('wechat',application['account_id'],r['conversation_id'])) for r in catalog]}
        # No authority comes from the imported keys, including unlimited legacy
        # sessions. Only new separately signed owner contracts can enable use.
        receipt={'version':2,'application':application,'owner_public_key':response['public_key'],
                           'owner_user':actual['user'],'enrollment':digest(challenge)}
        if os.name=='nt' and 'build_digest' in challenge:receipt['enrollment_build']=challenge['build_digest']
        store.seal_config(receipt)
        finish_initialization(store,signer)
    if os.name=='nt':
        from .windows_enrollment import persist_pin
        _windows_source_workspace(application)
        persist_pin(resources_root(),response['public_key'])
    return {'state':str(directory),'endpoint':config['endpoint'],'owner_public_key':response['public_key']}

def finish_initialization(store,signer):
        # Only the empty, audit-anchored FIRST setup may enroll its completed
        # build after an interrupted transaction. No existing task is restored.
        config=store.config();application=config['application']
        if not store.journal.verify_audit() or store.journal.checkpoint.read()['sequence']!=0:raise AXRError('wechat_empty_initialization_checkpoint_required')
        from axr.initialization import empty_initialization
        deployment=OwnerDeployment(store.secrets,store.vault,revoke_for_update=lambda:
            empty_initialization(store.directory) and store.journal.verify_audit() and store.journal.checkpoint.read()['sequence']==0)
        assets=_build_assets(application)
        install=resources_root().parent if os.name=='nt' else BASE
        if os.name=='nt' and config.get('enrollment_build') is not None and review_windows_build(application)['build']!=config['enrollment_build']:
            raise AXRError('wechat_owner_build_changed_during_review')
        deployment.enroll(install,assets,lambda:store.config()==config and
            (os.name=='nt' or config['owner_user']==process_identity(os.getpid())['user']))
        kernel,registry=_kernel(store,signer,config['owner_public_key'],initialize=True)
        try:kernel.integrity.persist()
        finally:kernel.close()

def resume_owner_setup(value):
    """Finish an already authenticated setup; never authorize an operation.

    The receipt is an existing native-Root-MAC policy, not a caller flag. The
    generic host additionally refuses this path once its bootstrap key exists.
    Active/previous task state and nonzero protected audit heads are rejected.
    """
    config=_configuration(value);directory=Path(config['state'])
    if not (directory/'policy.sealed.json').exists():return None
    if os.name=='nt':return _resume_windows_owner_setup(config)
    from axr.initialization import empty_initialization
    if not empty_initialization(directory):raise AXRError('wechat_initialization_recovery_requires_review')
    with __import__('contextlib').closing(OwnerStore(directory,authority_service=True)) as store:
        approved=store.config();current={k:v for k,v in config['application'].items() if k not in ('resources','conversations')}
        original={k:v for k,v in approved.get('application',{}).items() if k not in ('resources','conversations')}
        if (approved.get('version')!=2 or original!=current or approved.get('owner_user')!=process_identity(os.getpid())['user']
            or len(approved.get('enrollment',''))!=64 or len(bytes.fromhex(approved['owner_public_key']))!=65):raise AXRError('wechat_initialization_approval_changed')
        signer=native.HardwareSigningKey('Stellaria.AXR.Root.v2')
        finish_initialization(store,signer)
        return {'state':str(directory),'endpoint':config['endpoint'],'owner_public_key':approved['owner_public_key']}

def _windows_setup_review(config,key,build,kind):
    from .windows_enrollment import exchange
    challenge={'version':2,'kind':kind,'configuration_digest':digest(config),'expected_public_key':key,
        'build_digest':build['build'],'nonce':secrets.token_hex(32),'expires':time.time()+180}
    response,actual=exchange(config,challenge,resources_root())
    if response['public_key']!=key or response['challenge']!=challenge or actual['user']!=config['owner_user']:
        raise AXRError('wechat_initialization_approval_changed')
    return challenge


def _windows_source_workspace(application):
    provider=application.get('codex_provider')
    if provider is not None:
        path=Path(native.windows_data_root())/'source'
        if Path(provider.get('workspace',''))!=path:raise AXRError('windows_source_fixed_workspace_required')
        from axr.storage import private_directory
        private_directory(path)


def _resume_windows_owner_setup(config):
    from axr.initialization import empty_initialization
    directory=Path(config['state']);early=empty_initialization(directory)
    allowed={'guard.sqlite3','journal.sqlite3','policy.sealed.json','peer-registry.sealed','security-state.sealed'}
    allowed|={n+s for n in ('guard.sqlite3','journal.sqlite3') for s in ('-shm','-wal')}
    if (not early and (not all((directory/n).is_file() for n in ('guard.sqlite3','journal.sqlite3','security-state.sealed')) or
        any(p.name not in allowed or p.is_symlink() or p.is_junction() for p in directory.iterdir()))):
        raise AXRError('wechat_initialization_recovery_requires_review')
    with __import__('contextlib').closing(OwnerStore(directory,authority_service=True)) as store:
        approved=store.config();strip=lambda app:{k:v for k,v in app.items() if k not in ('resources','conversations')}
        if (approved.get('version')!=2 or strip(approved.get('application',{}))!=strip(config['application']) or
            approved.get('owner_user')!=config['owner_user'] or re.fullmatch('[0-9a-f]{64}',approved.get('enrollment','')) is None or
            re.fullmatch('[0-9a-f]{588}',approved.get('owner_public_key','')) is None):raise AXRError('wechat_initialization_approval_changed')
        if not store.journal.verify_audit():raise AXRError('wechat_initialization_recovery_requires_review')
        if not early:
            from axr.integrity import AuthorityIntegrity
            AuthorityIntegrity(store,application_tables={'wechat_state':'name'}).verify()
            # A fully persisted first setup may have state checkpoints but must
            # never have issued a task, accessed/disclosed content or executed.
            empty=('jobs','contexts','events','telemetry','results','disclosed_scopes','execution_claims',
                'security_contracts','security_claims','security_events','security_execution_reviews','authority_commits','wechat_state')
            if any(store.journal.db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone() for table in empty):
                raise AXRError('wechat_initialization_recovery_requires_review')
            import sqlite3
            with __import__('contextlib').closing(sqlite3.connect((directory/'guard.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute('SELECT 1 FROM grants LIMIT 1').fetchone():raise AXRError('wechat_initialization_recovery_requires_review')
        deployment=OwnerDeployment(store.secrets,store.vault);assets=_build_assets(approved['application']);root=resources_root().parent
        build=deployment.review(root,assets)
        challenge=_windows_setup_review(config,approved['owner_public_key'],build,'wechat-owner-recovery')
        if store.config()!=approved or deployment.review(root,assets)!=build or time.time()>=challenge['expires']:
            raise AXRError('wechat_initialization_approval_changed')
        if early:
            if approved.get('enrollment_build') is not None and approved['enrollment_build']!=build['build']:
                # This new exact signature supersedes only the unfinished setup
                # receipt, never an operational policy/task or its history.
                store.seal_config({**approved,'enrollment':digest(challenge),'enrollment_build':build['build']})
            finish_initialization(store,native.HardwareSigningKey('Stellaria.AXR.Root.v2'))
        elif deployment._load()!=build:raise AXRError('wechat_initialization_approval_changed')
    from .windows_enrollment import persist_pin
    _windows_source_workspace(approved['application'])
    persist_pin(resources_root(),approved['owner_public_key'])
    return {'state':str(directory),'endpoint':config['endpoint'],'owner_public_key':approved['owner_public_key']}


def _refresh_windows_owner_build(value,bootstrap):
    config=_configuration(value)
    if config['state']!=bootstrap.get('state') or config['endpoint']!=bootstrap.get('endpoint'):
        raise AXRError('wechat_build_update_configuration_changed')
    with __import__('contextlib').closing(OwnerStore(config['state'],authority_service=True)) as store:
        approved=store.config();strip=lambda app:{k:v for k,v in app.items() if k not in ('resources','conversations')}
        old,new=strip(approved['application']),strip(config['application']);root=resources_root().parent
        if (approved['owner_user']!=config.get('owner_user') or approved['owner_public_key']!=bootstrap.get('owner_public_key') or
            not provider_build_update(old,new,bundled_path=root/'runtime/provider/codex.exe')):
            raise AXRError('wechat_build_update_configuration_changed')
        kernel,registry=_windows_kernel(store,native.HardwareSigningKey('Stellaria.AXR.Root.v2'),approved['owner_public_key'],enroll_current=False)
        try:
            kernel.security.revoke('kernel');kernel.integrity.persist()
            def revoked():return kernel.integrity.verify() and not kernel.db.execute('SELECT 1 FROM security_contracts WHERE revoked=0 LIMIT 1').fetchone()
            deployment=OwnerDeployment(store.secrets,store.vault,revoke_for_update=revoked);assets=_build_assets(approved['application']);build=deployment.review(root,assets)
            challenge=_windows_setup_review(config,approved['owner_public_key'],build,'wechat-owner-build-update')
            def authenticated():return store.config()==approved and time.time()<challenge['expires'] and deployment.review(root,assets)==build and revoked()
            result=deployment.enroll(root,assets,authenticated)
            if old!=new:store.seal_config({**approved,'application':{**approved['application'],'codex_provider':new['codex_provider']}})
            registry.rows=[]
            if not native.durable_write(str(registry.path),store.vault.seal([],'axr-peer-registry-v2')):raise AXRError('peer_registry_write_failed')
            store.journal.security_event('owner-build-update',{'build':result['build'],'authority_restored':False});kernel.integrity.persist()
            return {**result,'updated':True,'credentials_retained':True,'ledger_retained':True}
        finally:kernel.close()


def _windows_kernel(store,signer,owner_public_key,*,initialize=False,enroll_current=True):
    config=store.config();application=config['application'];deployment=OwnerDeployment(store.secrets,store.vault)
    registry=PeerRegistry(store,owner_user=config['owner_user'],owner_deployment=deployment)
    # LPAC clients can reach the pipe, but receive no handshake bytes until the
    # fixed enrolled image, owner user and actual no-network token are checked.
    registry.public_sandbox_sids=('S-1-15-2-2',)
    # The controller is trusted root code; native database operations stay in the
    # same protected process. It is registered as a handler, never as a model.
    actual=process_identity(os.getpid())
    credential_peer=PeerContext('handler',PRINCIPAL,digest(actual),actual['pid'],actual['birth'])
    def identity(peer):return {'agent':peer.principal,'application':'wechat','identity_verified':registry.accept(process_identity(peer.pid))==peer}
    def environment(peer):
        row=next((r for r in registry.rows if r['identity']['pid']==peer.pid and r['identity']['birth']==peer.birth),None)
        sandbox=(row or {}).get('sandbox')
        return {'sandbox':BOUNDARY if peer==credential_peer else sandbox.get('profile') if sandbox else 'trusted-native-handler',
            'environment_valid':bool(sandbox) or peer==credential_peer,'audit_valid':store.journal.verify_audit(),'network_allowed':True}
    security=SecurityService(store,lambda:{},lambda:{},revoke_domain=lambda scope:None)
    pending={}
    def handler(operation,resource):
        if operation in ('messages.search','database.query','messages.read','disclosure.send','reply.prepare'):return credential_peer
        peer=pending.get('native')
        if operation=='status.read' and resource.conversation_id!='axr:application-ui' and peer is None:return credential_peer
        if peer is None:raise AXRError('wechat_native_handler_not_ready')
        return peer
    store.journal.db.execute('CREATE TABLE IF NOT EXISTS wechat_state(name TEXT PRIMARY KEY,payload BLOB)')
    kernel=WeChatKernel(security,signer,bytes.fromhex(owner_public_key),identity=identity,environment=environment,
            handler_for=handler,initialize=initialize,recovery_verifier=lambda peer,scope:store.journal.verify_audit(),
            application_tables={'wechat_state':'name'})
    kernel.controller_peer=credential_peer
    registry.on_change=kernel.integrity.persist
    if enroll_current:registry.enroll(actual,'handler',PRINCIPAL,lambda:config['owner_user'])
    original_accept=registry.accept
    def accept(candidate):
        try:return original_accept(candidate)
        except AXRError:
            root=resources_root().parent
            role='owner' if candidate.get('image')==str(root/'axr-owner.exe') else 'client'
            expected=root/('axr-owner.exe' if role=='owner' else 'axr-frontend.exe')
            if candidate.get('image')!=str(expected) or not deployment.verify_process(candidate,role):
                raise AXRError('ipc_peer_not_enrolled') from None
            sandbox=None
            if role=='client':
                witness=windows_client_sandbox(candidate)
                sandbox={**witness,'native_profile':witness['profile'],'profile':BOUNDARY}
            with kernel.lock:
                kernel._check_integrity()
                def alive(row):
                    try:return process_identity(row['identity']['pid'])==row['identity']
                    except AXRError:return False
                registry.rows=[r for r in registry.rows if alive(r)]
                registry.enroll(candidate,role,'wechat:owner' if role=='owner' else PRINCIPAL,lambda:config['owner_user'],managed_sandbox=sandbox)
                return original_accept(candidate)
    registry.accept=accept
    kernel.wechat_registry=registry;kernel.wechat_handlers=pending
    return kernel,registry

def _kernel(store,signer,owner_public_key,*,initialize=False):
    if os.name=='nt':return _windows_kernel(store,signer,owner_public_key,initialize=initialize)
    config=store.config();application=config['application'];deployment=OwnerDeployment(store.secrets,store.vault)
    registry=PeerRegistry(store,owner_user=config['owner_user'],owner_deployment=deployment)
    # The controller is trusted root code; native database operations stay in the
    # same protected process. It is registered as a handler, never as a model.
    actual=process_identity(os.getpid())
    credential_peer=PeerContext('handler',PRINCIPAL,digest(actual),actual['pid'],actual['birth'])
    def identity(peer):return {'agent':peer.principal,'application':'wechat','identity_verified':registry.accept(process_identity(peer.pid))==peer}
    def environment(peer):
        row=next((r for r in registry.rows if r['identity']['pid']==peer.pid and r['identity']['birth']==peer.birth),None)
        sandbox=(row or {}).get('sandbox')
        return {'sandbox':BOUNDARY,'environment_valid':bool(sandbox) or peer==credential_peer,
            'audit_valid':store.journal.verify_audit(),'network_allowed':True}
    security=SecurityService(store,lambda:{},lambda:{},revoke_domain=lambda scope:None)
    pending={}
    def handler(operation,resource):
        if operation not in ('application.navigate','application.draft','messages.send'):return credential_peer
        peer=pending.get('native')
        if peer is None:raise AXRError('wechat_native_handler_not_ready')
        return peer
    store.journal.db.execute('CREATE TABLE IF NOT EXISTS wechat_state(name TEXT PRIMARY KEY,payload BLOB)')
    kernel=WeChatKernel(security,signer,bytes.fromhex(owner_public_key),identity=identity,environment=environment,
            handler_for=handler,initialize=initialize,recovery_verifier=lambda peer,scope:store.journal.verify_audit(),
            application_tables={'wechat_state':'name'})
    kernel.controller_peer=credential_peer
    registry.on_change=kernel.integrity.persist
    registry.enroll(actual,'handler',PRINCIPAL,lambda:config['owner_user'])
    original_accept=registry.accept
    def accept(candidate):
        try:return original_accept(candidate)
        except AXRError:
            # Only fixed, owner-enrolled native images can enter dynamically.
            # Frontend's sole C++ entry applies Seatbelt before Python/input.
            role='owner' if candidate.get('image')==str(BASE/'AXR Owner.app/Contents/MacOS/axr-owner') else 'client'
            if not deployment.verify_process(candidate,role):raise AXRError('ipc_peer_not_enrolled') from None
            with kernel.lock:
                kernel._check_integrity()
                def alive(row):
                    try:return process_identity(row['identity']['pid'])==row['identity']
                    except AXRError:return False
                registry.rows=[r for r in registry.rows if alive(r)]
                registry.enroll(candidate,role,'wechat:owner' if role=='owner' else PRINCIPAL,lambda:config['owner_user'],
                    managed_sandbox={'pid':candidate['pid'],'birth':candidate['birth'],'profile':BOUNDARY} if role=='client' else None)
                return original_accept(candidate)
    registry.accept=accept
    kernel.wechat_registry=registry;kernel.wechat_handlers=pending
    return kernel,registry

def release_gate(value):
    # These providers report observed deployment facts. In particular no JSON
    # UI flag can declare the incoming actor or MCP bridge qualified.
    def identity():
        actual=process_identity(os.getpid());return actual.get('signing_id')=='org.stellaria.axr.authority' and actual.get('hardened_runtime') is True and actual.get('signature_valid') is True
    def data():
        from . import _wechat_credentials
        return hasattr(_wechat_credentials,'import_legacy_credentials') and not hasattr(_wechat_credentials,'fixture_consumer')
    def integration():
        if os.name=='nt':return False # Windows deployment remains independently gated.
        with __import__('contextlib').closing(OwnerStore(value['state'],authority_service=True)) as store:
            config=store.config();app=config['application'];pins=OwnerDeployment(store.secrets,store.vault)._load()
            front=BASE/'AXR MCP.app/Contents/MacOS/axr-frontend'
            enrolled=any(p['path']==str(front) and p['roles']==['client'] and p['sha256']==hashlib.sha256(front.read_bytes()).hexdigest() for p in pins['assets'])
            provider=app['codex_provider']
            return (enrolled and bool(app.get('conversations')) and
                hashlib.sha256(Path(provider['binary']).read_bytes()).hexdigest()==provider['sha256'] and
                hashlib.sha256(Path(provider['tls_bundle']).read_bytes()).hexdigest()==provider['tls_sha256'] and
                Path('/usr/bin/sandbox-exec').is_file())
    def content():
        from .wechat_database import actor_records
        return actor_records({'messages':[{'outgoing':False,'text':'密码：qualification-fixture','reference':'synthetic'}]})[0]['text'].find('qualification-fixture')<0
    return ReleaseGate({'identity':identity,'authorization':identity,'content':content,
        'data':data,'isolation':integration,'containment':identity,'distribution':identity,
        'adversarial':integration,'experience':integration})

def create_authority(value):
    release_gate(value).require()
    store=OwnerStore(value['state'],authority_service=True)
    kernel=None
    try:
        signer=native.HardwareSigningKey('Stellaria.AXR.Root.v2')
        kernel,registry=_kernel(store,signer,value['owner_public_key'])
        if os.name=='nt' and native.security_release:
            native.expose_windows_authority_identity(registry.user)
            connection={'version':2,'endpoint':value['endpoint'],'server':process_identity(os.getpid())}
            if not native.durable_write(str(resources_root()/'owner-connection.json'),canonical(connection)+b'\n'):
                raise AXRError('wechat_owner_connection_publish_failed')
        if os.name=='nt':
            from .wechat_mcp import attach_windows_mcp
            attach_windows_mcp(kernel,store.config()['application'])
        server=AuthorityServer(kernel,registry,value['endpoint']);server.wechat_store=store
        if os.name=='nt':
            from .wechat_windows_service import WindowsWeChatService
            service=WindowsWeChatService(kernel,registry,store.config()['application'],value['endpoint'])
            kernel.wechat_service=service # Keep the separately approved eight-tool application intact.
        else:
            service=WeChatService(kernel,registry,store.config()['application'],value['endpoint']);kernel.application=service
        old_serve=server.serve;old_close=server.close
        def serve():
            service.start()
            return old_serve()
        def close():
            try:service.close()
            finally:old_close()
        if os.name=='nt':
            previous_close=getattr(kernel,'application_close',None)
            def application_close():
                try:service.close()
                finally:
                    if callable(previous_close):previous_close()
            kernel.application_close=application_close
        server.serve=serve;server.close=close
        return server
    except BaseException:
        try:
            if kernel is not None:kernel.close()
        finally:store.close()
        raise

def owner_enroll(runtime_root):
    from .wechat_owner import main
    return main(runtime_root)

def owner_control(runtime_root):
    from .windows_owner import main
    return main(runtime_root)

def frontend_main(runtime_root):
    from .wechat_frontend import main
    return main(runtime_root)

def validate_runtime():
    from . import _wechat_credentials
    from .wechat_database import NativeDatabase
    from .codex_source import CodexSourceProvider
    from .wechat_execution import AuthorityNavigation
    import zstandard
    import sqlite3
    if os.name=='nt':
        import win32api,win32security,win32file,win32pipe,win32event,win32process,win32service,pywintypes
    # No live file, credential lookup, service, GUI or model call is used.
    return {'formal_native':native.security_release is True,
        'utf8_runtime':__import__('sys').getfilesystemencoding()=='utf-8' and __import__('sys').stdout.encoding.lower().replace('-','')=='utf8',
        'no_fixture_key_constructor':not hasattr(_wechat_credentials,'fixture_consumer') and not hasattr(_wechat_credentials,'fixture_verify_owner_file'),
        'owner_credential_import':hasattr(_wechat_credentials,'import_owner_credentials'),
        'native_wcdb':hasattr(_wechat_credentials,'WeChatConsumer'),
        'compressed_text':zstandard.ZstdDecompressor().decompress(zstandard.ZstdCompressor().compress(b'AXR runtime fixture'))==b'AXR runtime fixture',
        'journal_runtime':bool(sqlite3.sqlite_version)}
