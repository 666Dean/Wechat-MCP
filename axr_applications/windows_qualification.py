# SPDX-License-Identifier: MIT
"""One reviewer-pinned, owner-signed Windows experiment; no normal service gate.

No permit signing, evidence success generation, automatic session or MCP tools.
Only the separate native maintenance entry calls run; ordinary serve never does.
"""
import contextlib,hashlib,math,secrets,threading,time
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,Action,canonical,digest
from axr.rooted import RootedDirectory
from . import windows_admission as admission
from .windows_navigation import read_json,sha,text
from .wechat_service import PRINCIPAL

PRODUCT='wechat-codex-mcp/windows/qualification'
MAX_DURATION=600
SCENARIOS=frozenset(('metadata','read','source','send'))


def verify(envelope,keys,expected,*,clock=time.time):
    try:
        if type(envelope) is not dict or set(envelope)!={'body','key_id','signature'}:raise ValueError()
        body=envelope['body'];signature=envelope['signature']
        if type(signature) is not str or len(signature)>160:raise ValueError()
        raw=bytes.fromhex(signature)
        if raw.hex()!=signature or not native.verify_root_signature(keys[envelope['key_id']],canonical(body),raw):raise ValueError()
        if (type(body) is not dict or set(body)!={'version','product','sequence','subject','created','expires','nonce','software_audit','plan'} or
            type(body['version']) is not int or body['version']!=2 or body['product']!=PRODUCT or
            type(body['sequence']) is not int or not 1<=body['sequence']<2**53 or not sha(body['nonce']) or
            canonical(body['subject'])!=canonical(expected)):raise ValueError()
        now=clock()
        if (any(type(t) not in (int,float) or not math.isfinite(t) for t in (body['created'],body['expires'],now)) or
            not body['created']<=now<body['expires'] or not 0<body['expires']-body['created']<=MAX_DURATION):raise ValueError()
        audit=body['software_audit'];plan=body['plan']
        if (type(audit) is not dict or set(audit)!={'complete','record_sha256'} or audit['complete'] is not True or not sha(audit['record_sha256']) or
            type(plan) is not dict or set(plan)!={'scenario','target','parking','text','since'} or plan['scenario'] not in SCENARIOS or
            not text(plan['target'],512) or not text(plan['parking'],512) or plan['target']==plan['parking'] or
            type(plan['since']) is not int or not 0<=plan['since']<2**63 or type(plan['text']) is not str or
            (not text(plan['text'],16000) if plan['scenario']=='send' else plan['text']!='')):raise ValueError()
        from .wechat_targets import private_recipient
        if any(not private_recipient(plan[k]) or plan[k]=='axr:application-ui' for k in ('target','parking')):raise ValueError()
        return {'expires':body['expires'],'sequence':body['sequence'],'permit_digest':digest(envelope),'runtime_qualified':False}
    except (KeyError,TypeError,ValueError,OverflowError):raise AXRError('windows_qualification_permit_invalid') from None


def installed_permit(runtime_root,configuration):
    from .windows_enrollment import enrolled_public_key
    from .wechat import review_windows_build
    import sys
    version=sys.getwindowsversion()
    expected=admission.subject(configuration,review_windows_build(configuration['application'])['build'],
        enrolled_public_key(runtime_root).hex(),[version.major,version.minor,version.build])
    keys=admission.installed_trust(Path(runtime_root).parent,configuration['application'])
    envelope=read_json(Path(native.windows_data_root())/'windows-qualification.json',20000)
    verify(envelope,keys,expected)
    plan=envelope['body']['plan'];profiles=configuration['application']['reply_navigation']['profiles']
    if any(cid not in profiles for cid in (plan['target'],plan['parking'])):raise AXRError('windows_qualification_navigation_required')
    if plan['scenario']=='send' and configuration['application']['reply_navigation'].get('attribution_required',True) and not plan['text'].startswith(
        configuration['application']['reply_navigation']['attribution_prefix']):raise AXRError('reply_explicit_ai_attribution_required')
    return envelope


class QualificationSession(admission.RuntimeAdmission):
    material_name='windows-qualification.json'
    material_maximum=20000
    def validate_material(self,envelope,wall):return verify(envelope,self.keys,self.expected,clock=lambda:wall)


def claim(store,envelope):
    """Independent sealed high-water mark, consumed even on owner cancellation."""
    name='windows-qualification-head-v2';body=envelope['body']
    try:prior=store.vault.open(store.secrets.get(name),name)
    except AXRError as error:
        if str(error)!='owner_secret_not_provisioned':raise
        prior={'sequence':0}
    if type(prior) is not dict or type(prior.get('sequence')) is not int or body['sequence']<=prior['sequence']:
        raise AXRError('windows_qualification_consumed_no_retry')
    head={'sequence':body['sequence'],'permit_digest':digest(envelope),'outcome':'Unknown','retry':False}
    store.secrets.provision(name,store.vault.seal(head,name))
    if store.vault.open(store.secrets.get(name),name)!=head:raise AXRError('windows_qualification_claim_unknown_no_retry')


class QualificationKernel(admission.WindowsAdmissionKernel):
    def dispatch(self,peer,packet):
        p=packet.get('payload',{}) if type(packet) is dict else {}
        op=packet.get('operation') if type(packet) is dict else None
        if (peer.role!='handler' or type(p) is not dict or
            not (op=='Access' and p.get('phase')=='preflight' or op=='Commit' and p.get('phase') in ('claim','receipt'))):
            raise AXRError('windows_qualification_no_public_api')
        return super().dispatch(peer,packet)

    def qualify_action(self,action):
        plan=self.qualification_plan;app=self.qualification_application
        cid=action.resource.conversation_id;scenario=plan['scenario']
        if (action.principal!=PRINCIPAL or action.resource.platform!='wechat' or action.resource.account_id!=app['account_id'] or
            cid not in (plan['target'],plan['parking'],'axr:application-ui')):raise AXRError('windows_qualification_action_outside_plan')
        operations={'metadata':set(),'read':{'messages.search'},'source':{'messages.search','disclosure.send'},
            'send':{'messages.search','messages.read','status.read','application.navigate','application.draft','messages.send'}}[scenario]
        if action.operation not in operations:raise AXRError('windows_qualification_action_outside_plan')
        if any(s.resource.platform!='wechat' or s.resource.account_id!=app['account_id'] or s.resource.conversation_id not in (plan['target'],plan['parking']) for s in action.sources):
            raise AXRError('windows_qualification_action_outside_plan')
        if action.operation=='disclosure.send':
            from .codex_source import CodexSourceProvider
            if cid!=plan['target'] or action.destination!=CodexSourceProvider.destination:raise AXRError('windows_qualification_action_outside_plan')
        elif action.operation=='messages.send':
            if cid!=plan['target'] or action.payload.get('text')!=plan['text'] or action.destination!='wechat:'+action.resource.key:
                raise AXRError('windows_qualification_action_outside_plan')
        elif action.destination!='local':raise AXRError('windows_qualification_action_outside_plan')
        if action.operation=='messages.search':
            if scenario in ('read','source') and (cid!=plan['target'] or action.payload.get('since')!=plan['since'] or action.payload.get('limit')!=6 or action.payload.get('cursor') is not None):
                raise AXRError('windows_qualification_action_outside_plan')
        if action.operation=='application.draft' and action.payload.get('text')!=plan['text']:raise AXRError('windows_qualification_action_outside_plan')
        if action.operation=='application.navigate' and action.payload.get('text') not in [app['reply_navigation']['profiles'][i]['label'] for i in (plan['target'],plan['parking'])]:
            raise AXRError('windows_qualification_action_outside_plan')

    def access(self,peer,capability,action):
        if peer!=self.controller_peer:raise AXRError('windows_qualification_no_public_api')
        self.qualify_action(action)
        return super().access(peer,capability,action)

    def preflight_commit(self,peer,proof):
        result=super().preflight_commit(peer,proof)
        self.qualify_action(Action.from_dict(proof['body']['action']))
        return result


def execute(service,plan,review_disclosure=None):
    """One fixed scenario. Never run the shared scheduler or consume a queue."""
    target=plan['target'];service.check()
    if plan['scenario']=='metadata':return {'metadata':service.readiness(),'body_disclosed':False,'send_invoked':False}
    if plan['scenario'] in ('read','source'):
        page=service.read(target,since=plan['since'],limit=6)
        result={'records':len(page['messages']),'has_more':page['has_more'],'body_disclosed':False,'send_invoked':False}
        if plan['scenario']=='source':
            from .wechat_database import actor_records
            records=actor_records(page,include_outgoing=True)
            if records and service.approval_required():
                if review_disclosure is None:raise AXRError('wechat_exact_owner_approval_required')
                review_disclosure(records)
                service.check()
            output=service.infer(target,page)
            result.update(body_disclosed=output is not None,output_present=output is not None,
                output_digest=digest(output) if output is not None else None)
        return result
    # This exact text is covered by both reviewer permit and owner signature.
    # Keep the normal independent approval setting and reply transaction intact.
    job={'id':'qualification-'+digest(plan),'conversation_id':target,'operation':'messages.send','state':'Executing',
        'text':plan['text'],'created':time.time(),'expires':service.scope['expires'],'scope_generation':service.generation,'retry':False}
    job['approval']=service.approval_seal(job);service.save_job(job['id'],job);service.context.executing_job=job['id']
    try:
        waiting=service.send_wait_reason()
        if waiting:raise AXRError('windows_qualification_foreground_or_idle_required')
        value=service.send(target,plan['text'])
    finally:service.save_job(job['id'],{k:v for k,v in {**job,'state':'Unknown'}.items() if k!='approval'})
    return {'state':value.get('state','Unknown'),'native_state':value.get('native_state','Unknown'),
        'database_record_observed':value.get('database_record_observed',False),'body_disclosed':False}


def activate_scope(service,plan,expires):
    # This is reached only after the independent permit AND exact owner proof.
    service.owner='wechat:owner';service.generation+=1
    service.scope={'targets':[plan['target'],plan['parking']],'reply_targets':[plan['target']] if plan['scenario']=='send' else [],
        'expires':expires,'max_replies':1,'automatic':False,'disclose':plan['scenario']=='source',
        'style':'简洁、准确。仅根据当前来源回复。','attribution':True,'overwrite_drafts':False,'self_agent':False,
        'owner_thread':'','send_policy':'foreground_only','idle_seconds':5}
    service.derive_contract(plan['target'])


def run(value):
    """Called only by --qualify-service. Normal release_gate is never changed."""
    from . import wechat
    from .windows_enrollment import exchange
    from .wechat_windows_service import WindowsWeChatService
    from axr.deployment_configuration import read
    from axr.authority_server import AuthorityServer
    root=Path(native.windows_installation_root());admission.installed_context(value)
    config=wechat._configuration(read(root/'runtime')['deployment']);envelope=installed_permit(root/'runtime',config)
    session=QualificationSession(value);plan=envelope['body']['plan']
    if session.material_digest!=digest(envelope):raise AXRError('windows_qualification_changed')
    kernel=service=server=worker=None
    result={'state':'Unknown','retry':False,'runtime_qualified':False,'authorization_restored':False,'permit_digest':digest(envelope)}
    with contextlib.closing(wechat.OwnerStore(config['state'],authority_service=True)) as store:
        try:
            kernel,registry=wechat._windows_kernel(store,native.HardwareSigningKey('Stellaria.AXR.Root.v2'),value['owner_public_key'],kernel_type=QualificationKernel)
            kernel.security.revoke('kernel');claim(store,envelope)
            challenge={'version':2,'kind':'wechat-owner-qualification','configuration_digest':digest(config),
                'build_digest':envelope['body']['subject']['build'],'expected_public_key':value['owner_public_key'],
                'qualification_digest':digest(envelope),'nonce':secrets.token_hex(32),'expires':min(time.time()+180,envelope['body']['expires'])}
            response,actual=exchange(config,challenge,root/'runtime')
            if response['public_key']!=value['owner_public_key'] or actual['user']!=config['owner_user']:raise AXRError('windows_qualification_owner_changed')
            session.require();admission.installed_context(value)
            kernel.windows_admission=session;kernel.qualification_plan=plan;kernel.qualification_application=config['application']
            class QualificationService(WindowsWeChatService):
                def parking_target(self,identity):return plan['parking']
            service=QualificationService(kernel,registry,store.config()['application'],config['endpoint'])
            kernel.wechat_service=service
            activate_scope(service,plan,envelope['body']['expires'])
            server=AuthorityServer(kernel,registry,config['endpoint'])
            errors=[]
            def serve():
                try:server.serve()
                except BaseException as error:errors.append(type(error).__name__)
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            end=time.monotonic()+5
            while server.listener is None:
                session.require()
                if errors or not worker.is_alive() or time.monotonic()>=end:raise AXRError('windows_qualification_transport_unavailable')
                time.sleep(.01)
            def review_source(records):
                session.require()
                prompt={**challenge,'kind':'wechat-owner-qualification-disclosure','nonce':secrets.token_hex(32),
                    'expires':min(time.time()+180,envelope['body']['expires']),'records':records,'content_digest':digest(records)}
                response,actual=exchange(config,prompt,root/'runtime')
                if response['public_key']!=value['owner_public_key'] or actual['user']!=config['owner_user']:
                    raise AXRError('windows_qualification_owner_changed')
                session.require()
            facts=execute(service,plan,review_source);session.require()
            result.update(state='Recorded',facts=facts)
        except Exception as error:
            code=str(error)
            result['error']=code if isinstance(error,AXRError) and code.replace('_','').isalnum() and len(code)<=100 else 'windows_qualification_failed_unknown'
        finally:
            try:
                if service is not None:service.close()
            finally:
                try:
                    if kernel is not None:kernel.security.revoke('kernel');kernel.integrity.persist()
                finally:
                    try:
                        if server is not None:server.close()
                        if worker is not None:
                            worker.join(5)
                            if worker.is_alive():raise AXRError('windows_qualification_shutdown_incomplete')
                    finally:
                        if kernel is not None:kernel.close()
        # Only aggregate facts cross the desktop result channel. This is not
        # admission evidence and cannot create device/pass statements.
        data=RootedDirectory(native.windows_data_root())
        try:
            with data.parent('windows-qualification-result.json') as (parent,name):data.replace_at(parent,name,canonical(result),lambda:None)
        finally:data.close()
    return result
