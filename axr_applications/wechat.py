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
from axr.ipc import PeerContext, PeerRegistry, process_identity
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
    if type(value) is not dict or set(value)-{'state','endpoint','application','legacy_namespace','credential_import','owner_public_key'} or not {'state','endpoint','application'}<=set(value):raise AXRError('wechat_deployment_configuration_invalid')
    if value.get('legacy_namespace') and value.get('credential_import'):raise AXRError('wechat_deployment_configuration_invalid')
    if 'credential_import' in value:
        source=value['credential_import']
        if (type(source) is not dict or set(source)!={'path','sha256'} or not Path(source['path']).is_absolute()
            or re.fullmatch('[0-9a-f]{64}',source['sha256']) is None):raise AXRError('wechat_deployment_configuration_invalid')
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
        if 'binary' in provider:provider['binary']=asset(provider['binary'])
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
    return _hardware_enrollment(digest(config))

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
    if os.name=='nt':raise AXRError('wechat_build_update_platform_unavailable')
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
    if challenge['configuration_digest']!=digest(config) or challenge['expires']<=time.time() or not native.verify_root_signature(bytes.fromhex(response['public_key']),canonical(challenge),bytes.fromhex(response['signature'])):raise AXRError('wechat_owner_enrollment_signature_invalid')
    with __import__('contextlib').closing(OwnerStore(directory,provision=True,authority_service=True)) as store:
        if not store.journal.verify_audit() or store.journal.checkpoint.read()['sequence']!=0:raise AXRError('wechat_empty_initialization_checkpoint_required')
        application=config['application']
        from . import _wechat_credentials
        if config.get('legacy_namespace'):
            _wechat_credentials.import_legacy_credentials(canonical(application).decode(),config['legacy_namespace'])
        if config.get('credential_import'):
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
        store.seal_config({'version':2,'application':application,'owner_public_key':response['public_key'],
                           'owner_user':actual['user'],'enrollment':digest(challenge)})
        finish_initialization(store,signer)
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
        deployment.enroll(BASE,assets,lambda:store.config()==config and config['owner_user']==process_identity(os.getpid())['user'])
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

def _windows_kernel(store,signer,owner_public_key,*,initialize=False):
    config=store.config();application=config['application'];deployment=OwnerDeployment(store.secrets,store.vault)
    registry=PeerRegistry(store,owner_user=config['owner_user'],owner_deployment=deployment)
    # The controller is trusted root code; native database operations stay in the
    # same protected process. It is registered as a handler, never as a model.
    actual=process_identity(os.getpid())
    credential_peer=PeerContext('handler','wechat:credentials',digest(actual),actual['pid'],actual['birth'])
    def identity(peer):return {'agent':peer.principal,'application':'wechat','identity_verified':registry.accept(process_identity(peer.pid))==peer}
    def environment(peer):
        row=next((r for r in registry.rows if r['identity']['pid']==peer.pid and r['identity']['birth']==peer.birth),None)
        sandbox=(row or {}).get('sandbox')
        return {'sandbox':sandbox.get('profile') if sandbox else 'trusted-native-handler','environment_valid':bool(sandbox),'audit_valid':store.journal.verify_audit(),'network_allowed':True}
    security=SecurityService(store,lambda:{},lambda:{},revoke_domain=lambda scope:None)
    pending={}
    def handler(operation,resource):
        if operation in ('messages.search','database.query','messages.read','disclosure.send','reply.prepare'):return credential_peer
        peer=pending.get('native')
        if peer is None:raise AXRError('wechat_native_handler_not_ready')
        return peer
    kernel=AuthorityKernel(security,signer,bytes.fromhex(owner_public_key),identity=identity,environment=environment,
            handler_for=handler,initialize=initialize,recovery_verifier=lambda peer,scope:store.journal.verify_audit())
    registry.on_change=kernel.integrity.persist
    registry.enroll(actual,'handler','wechat:credentials',lambda:config['owner_user'])
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
    try:
        signer=native.HardwareSigningKey('Stellaria.AXR.Root.v2')
        kernel,registry=_kernel(store,signer,value['owner_public_key'])
        if os.name=='nt':
            from .wechat_mcp import attach_windows_mcp
            attach_windows_mcp(kernel,store.config()['application'])
            server=AuthorityServer(kernel,registry,value['endpoint']);server.wechat_store=store
            return server
        server=AuthorityServer(kernel,registry,value['endpoint']);server.wechat_store=store
        service=WeChatService(kernel,registry,store.config()['application'],value['endpoint']);kernel.application=service
        old_serve=server.serve;old_close=server.close
        def serve():
            service.start()
            return old_serve()
        def close():
            service.close();old_close()
        server.serve=serve;server.close=close
        return server
    except BaseException:store.close();raise

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
    # No live file, credential lookup, service, GUI or model call is used.
    return {'formal_native':native.security_release is True,
        'utf8_runtime':__import__('sys').getfilesystemencoding()=='utf-8' and __import__('sys').stdout.encoding.lower().replace('-','')=='utf8',
        'no_fixture_key_constructor':not hasattr(_wechat_credentials,'fixture_consumer') and not hasattr(_wechat_credentials,'fixture_verify_owner_file'),
        'owner_credential_import':hasattr(_wechat_credentials,'import_owner_credentials'),
        'native_wcdb':hasattr(_wechat_credentials,'WeChatConsumer'),
        'compressed_text':zstandard.ZstdDecompressor().decompress(zstandard.ZstdCompressor().compress(b'AXR runtime fixture'))==b'AXR runtime fixture',
        'journal_runtime':bool(sqlite3.sqlite_version)}
