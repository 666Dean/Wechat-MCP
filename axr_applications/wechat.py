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

BASE=Path('/Library/Application Support/Stellaria AXR')

def resources_root():
    actual=process_identity(os.getpid());image=Path(actual['image'])
    return image.parent/'runtime' if os.name=='nt' else image.parent.parent/'Resources'

def _configuration(value):
    if type(value) is not dict or set(value)-{'state','endpoint','application','legacy_namespace','owner_public_key'} or not {'state','endpoint','application'}<=set(value):raise AXRError('wechat_deployment_configuration_invalid')
    root=resources_root();application=dict(value['application'])
    if type(application.get('manual_approval_required',True)) is not bool:raise AXRError('wechat_approval_setting_invalid')
    def asset(value):
        if not isinstance(value,str):raise AXRError('wechat_deployment_asset_invalid')
        if not value.startswith('@resources/'):return value
        relative=value[len('@resources/'):]
        from pathlib import PurePosixPath
        if (not relative or '\\' in relative or PurePosixPath(relative).is_absolute() or
                any(part in ('.','..') for part in relative.split('/'))):
            raise AXRError('wechat_deployment_asset_invalid')
        path=(root/relative).resolve(strict=True)
        if not path.is_relative_to(root.resolve(strict=True)) or not path.is_file():
            raise AXRError('wechat_deployment_asset_invalid')
        return str(path)
    for field in ('sqlcipher_library','navigation_helper'):
        if field in application:application[field]=asset(application[field])
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
    return {**value,'state':str(state),'application':application}

def owner_setup_review(value):
    config=_configuration(value)
    return {'application':'WeChat MCP','fresh_state':config['state'],'endpoint':config['endpoint'],
        'credential_import':'native OS store to native OS store; keys never returned to Python',
        'resources':config['application']['resources'],'shard_count':len(config['application']['shards']),
        'automatic_reply_enabled':False,'legacy_permissions_restored':False,'vendor_certificate_required':False,
        'manual_approval_required':config['application'].get('manual_approval_required',True)}

def initialize_owner(value, signer):
    config=_configuration(value);directory=Path(config['state'])
    if directory.exists() and any(directory.iterdir()):raise AXRError('wechat_fresh_authority_state_required')
    # The second process is a fixed protected owner identity. Its hardware key
    # can require user presence; the authority cannot open that private key.
    owner=BASE/'AXR Owner.app/Contents/MacOS/axr-owner'
    challenge={'version':2,'kind':'wechat-owner-enrollment','configuration_digest':digest(config),
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
    with __import__('contextlib').closing(OwnerStore(directory,provision=True,authority_service=True)) as store:
        application=config['application']
        from . import _wechat_credentials
        if config.get('legacy_namespace'):
            _wechat_credentials.import_legacy_credentials(canonical(application).decode(),config['legacy_namespace'])
        # No authority comes from the imported keys, including unlimited legacy
        # sessions. Only new separately signed owner contracts can enable use.
        store.seal_config({'version':2,'application':application,'owner_public_key':response['public_key'],
                           'owner_user':actual['user'],'enrollment':digest(challenge)})
        deployment=OwnerDeployment(store.secrets,store.vault)
        helper=Path(application['navigation_helper'])
        assets=[{'path':'AXR Authority.app/Contents/MacOS/axr-authority','roles':['server','handler']},
                {'path':'AXR Owner.app/Contents/MacOS/axr-owner','roles':['owner']},
                {'path':str(helper.relative_to(BASE)),'roles':['handler']}]
        deployment.enroll(BASE,assets,lambda:True)
        kernel,registry=_kernel(store,signer,response['public_key'],initialize=True)
        try:kernel.integrity.persist()
        finally:kernel.close()
    return {'state':str(directory),'endpoint':config['endpoint'],'owner_public_key':response['public_key']}

def _kernel(store,signer,owner_public_key,*,initialize=False):
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

def release_gate(value):
    # These providers report observed deployment facts. In particular no JSON
    # UI flag can declare the incoming actor or MCP bridge qualified.
    def identity():
        actual=process_identity(os.getpid());return actual.get('signing_id')=='org.stellaria.axr.authority' and actual.get('hardened_runtime') is True and actual.get('signature_valid') is True
    def data():
        from . import _wechat_credentials
        return hasattr(_wechat_credentials,'import_legacy_credentials') and not hasattr(_wechat_credentials,'fixture_consumer')
    def integration():
        # Qualified frontend/source-handler enrollment is a protected setup
        # artifact, absent in older deployments. No legacy fallback is used.
        with __import__('contextlib').closing(OwnerStore(value['state'],authority_service=True)) as store:
            store.config()
            return False  # Managed MCP frontend is not deployed in this build.
    return ReleaseGate({'identity':identity,'authorization':identity,'content':lambda:False,
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
    except BaseException:store.close();raise

def owner_enroll(runtime_root):
    from .wechat_owner import main
    return main(runtime_root)

def owner_control(runtime_root):
    from .windows_owner import main
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
        'no_fixture_key_constructor':not hasattr(_wechat_credentials,'fixture_consumer'),
        'native_wcdb':hasattr(_wechat_credentials,'WeChatConsumer'),
        'compressed_text':zstandard.ZstdDecompressor().decompress(zstandard.ZstdCompressor().compress(b'AXR runtime fixture'))==b'AXR runtime fixture',
        'journal_runtime':bool(sqlite3.sqlite_version)}
