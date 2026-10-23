# SPDX-License-Identifier: MIT
"""Windows OS/approval adapters for the project's shared Mac dispatcher.

No alternate scheduler: pagination, bursts, standing scopes, short child tasks,
owner routing, preferences, queues and stop come from WeChatService.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import time
from axr import _axr_native as native
from axr.aet import AXRError,Action,Provenance,Resource,canonical,digest
from axr.host import Lease
from .wechat_service import WeChatService,PRINCIPAL
from .wechat_reply import ReplyExecutor,ReplyPlan
from .codex_source import CodexSourceProvider

PENDING=frozenset(('AwaitingApproval','AwaitingDisclosureApproval','AwaitingInference','DisclosureReady'))
PRIVATE=frozenset(('text','prompt','page','approval','client_witness','scope_generation'))


class WindowsWeChatService(WeChatService):
    windows=True
    def __init__(self,*args):
        super().__init__(*args)
        self.pending_reviews={};self.scope_clock=None
        self.executor=ReplyExecutor(self.database,self.kernel.store.directory/'reply-attempts')
        self.navigation.release=self.release_handler
        # A new service never restores pending content approvals or disclosures.
        for key,job in list(self.jobs.items()):
            if job['state'] in PENDING:
                self.save_job(key,{k:v for k,v in {**job,'state':'Unknown','retry':False}.items() if k not in ('page','approval')})
    def approval_required(self):
        load=getattr(self.kernel.store,'config',None)
        config=load()['application'] if callable(load) else self.config
        required=config.get('manual_approval_required',True)
        if type(required) is not bool:raise AXRError('wechat_approval_setting_invalid')
        return required
    def close(self):
        if self.stop_event.is_set() and not self.thread.is_alive():return
        super().close()
    def activate(self,peer,nonce,signature):
        with self.scope_lock:
            challenge=self.reviews.get(nonce)
            wall,tick=time.time(),time.monotonic()
            result=super().activate(peer,nonce,signature)
            expires=challenge['scope']['expires']
            self.scope_clock=(wall,tick,max(0,expires-wall) if expires else None)
            return result
    def check(self,generation=None):
        super().check(generation)
        if self.scope_clock:
            wall,tick,duration=self.scope_clock
            elapsed=time.monotonic()-tick
            if time.time()<wall or elapsed<0 or (duration is not None and elapsed>=duration):
                raise AXRError('wechat_scope_stopped_or_expired')
        job=self.jobs.get(getattr(self.context,'executing_job',None),{})
        if job.get('state')=='Executing' and job.get('operation')=='messages.send' and self.approval_required():
            if job.get('approval')!=self.approval_seal(job):raise AXRError('wechat_exact_owner_approval_required')
    def stop(self):
        result=super().stop()
        self.pending_reviews={}
        for key,job in list(self.jobs.items()):
            if job['state'] in PENDING:
                self.save_job(key,{k:v for k,v in {**job,'state':'FailedSafe','retry':False}.items() if k not in ('page','approval')})
        return result
    def queue_state(self,manual):
        return 'Draft' if manual else 'AwaitingApproval' if self.approval_required() else 'Queued'
    def pending_jobs(self):
        return [j for j in self.jobs.values() if j['state'] in PENDING|{'Queued','WaitingForIdle'}
            and j.get('kind')!='mcp-disclosure']
    @staticmethod
    def public_job(job):return {k:v for k,v in job.items() if k not in PRIVATE}
    def status(self):
        return {**super().status(),'manual_approval_required':self.approval_required(),'pending_review_supported':True}
    @staticmethod
    def approval_seal(job):
        return digest({k:job[k] for k in ('id','conversation_id','operation','text','source','page','expires','scope_generation','client_witness') if k in job})
    def process_incoming(self,key,job,context):
        if self.approval_required():
            from .wechat_database import actor_records
            # Store only the same bounded/masked context the source provider sees.
            records=actor_records({'messages':context},include_outgoing=True)
            if not records:raise AXRError('wechat_empty_source_batch')
            from axr_integration.content_safety import mask_credentials
            page={'messages':[{**row,'text':mask_credentials(row['text'])[0]} for row in context]}
            self.save_job(key,{**job,'state':'AwaitingDisclosureApproval','page':page,
                'scope_generation':self.generation})
        else:super().process_incoming(key,job,context)
    def process_pending(self):
        for key,job in list(self.jobs.items()):
            if job['state'] in PENDING and job['expires']<=time.time():
                self.save_job(key,{k:v for k,v in {**job,'state':'FailedSafe','error':'wechat_pending_review_expired'}.items() if k not in ('page','approval')})
                continue
            if job['state'] in ('Queued','WaitingForIdle') and self.approval_required() and job.get('approval')!=self.approval_seal(job):
                self.save_job(key,{**job,'state':'AwaitingApproval'})
            if job['state']!='AwaitingInference':continue
            # Permanent transition BEFORE inference: an exception cannot replay.
            value={k:v for k,v in job.items() if k not in ('page','approval')}
            self.save_job(key,{**value,'state':'Executing'})
            try:
                self.check(job['scope_generation'])
                if job.get('approval')!=self.approval_seal(job):raise AXRError('wechat_pending_review_changed')
                super().process_incoming(key,value,job['page']['messages'])
            except Exception:
                self.save_job(key,{**value,'state':'Unknown','error':'wechat_source_failed','retry':False})
    def review_pending(self,peer,handle):
        self.kernel._owner(peer);self.check()
        with self.job_lock:
            job=self.jobs.get(handle)
            if not job or job['state'] not in ('AwaitingApproval','AwaitingDisclosureApproval') or job['expires']<=time.time():
                raise AXRError('wechat_pending_review_unavailable')
            self.pending_reviews={k:v for k,v in self.pending_reviews.items() if v['expires']>time.time()}
            if len(self.pending_reviews)>=16:raise AXRError('owner_challenge_capacity')
            challenge={'version':2,'kind':'wechat-windows-pending','root_id':self.kernel.root_id,'epoch':self.kernel.epoch,
                'owner':peer.principal,'peer':peer.witness,'nonce':secrets.token_hex(32),'expires':min(job['expires'],time.time()+60),
                'job_id':handle,'seal':self.approval_seal(job),'generation':self.generation,'state':job['state']}
            self.pending_reviews[challenge['nonce']]=challenge
            review={'conversation':self.catalog[job['conversation_id']],'operation':job['operation']}
            if job['state']=='AwaitingApproval':review['text']=job['text']
            else:
                from .wechat_database import actor_records
                review['records']=actor_records(job['page'],include_outgoing=True)
            challenge['review_digest']=digest(review)
            return {'challenge':challenge,'review':review}
    def approve_pending(self,peer,nonce,signature):
        self.kernel._owner(peer);self.check()
        with self.job_lock:
            challenge=self.pending_reviews.pop(nonce,None)
            if (not challenge or challenge['expires']<=time.time() or challenge['generation']!=self.generation
                or challenge['peer']!=peer.witness):raise AXRError('wechat_pending_review_changed')
            job=self.jobs.get(challenge['job_id'])
            if not job or job['state']!=challenge['state'] or self.approval_seal(job)!=challenge['seal']:
                raise AXRError('wechat_pending_review_changed')
            try:valid=native.verify_owner_signature(self.kernel.owner_public_key,canonical(challenge),bytes.fromhex(signature))
            except Exception:valid=False
            if not valid:raise AXRError('owner_presence_signature_required')
            if time.time()>=challenge['expires']:raise AXRError('wechat_pending_review_changed')
            state=('Queued' if job['state']=='AwaitingApproval' else
                'DisclosureReady' if job.get('kind')=='mcp-disclosure' else 'AwaitingInference')
            self.save_job(job['id'],{**job,'state':state,'approval':challenge['seal']})
        self.worker_event.set()
        return {'job_id':job['id'],'state':state,'retry':False}
    def disclose_page(self,peer,job):
        self.check(job['scope_generation'])
        if job['client_witness']!=peer.witness:raise AXRError('wechat_job_not_owned')
        if job.get('approval')!=self.approval_seal(job):raise AXRError('wechat_pending_review_changed')
        page=job['page'];identity=job['conversation_id']
        action=self.action(identity,'disclosure.send',{'page_digest':digest(page)},destination='model:codex-mcp',
            sources=(Provenance(self.resources[identity],digest(page),'personal'),))
        proof=self.prepare(action)
        # Claim, persist terminal metadata and erase pending body before delivery.
        self.kernel.claim_commit(self.peer,proof)
        self.save_job(job['id'],{k:v for k,v in {**job,'state':'Unknown'}.items() if k not in ('page','approval')})
        self.check(job['scope_generation'])
        self.kernel.observe(self.peer,proof,verified=True,evidence_digest=digest(page))
        self.save_job(job['id'],{k:v for k,v in {**job,'state':'Completed'}.items() if k not in ('page','approval')})
        return {'job_id':job['id'],'state':'Completed','page':page,'retry':False}
    def dispatch(self,peer,packet):
        payload=packet.get('payload',{});method=payload.get('method');args=payload.get('arguments',{})
        if packet.get('operation')=='WeChatOwner':
            if method=='review_pending':return self.review_pending(peer,args['job_id'])
            if method=='approve_pending':return self.approve_pending(peer,args['nonce'],args['signature'])
            result=super().dispatch(peer,packet)
            if method=='snapshot':result['jobs']=[self.public_job(job) for job in self.jobs.values()]
            return result
        if peer.role!='client' or peer.principal!=PRINCIPAL:raise AXRError('wechat_managed_frontend_required')
        from .wechat_frontend import validate_arguments
        validate_arguments(method,args);self.context.generation=self.generation
        if method=='wechat_job_status':
            with self.job_lock:
                job=self.jobs.get(args['job_id'])
                if not job or (job.get('client_witness') and job['client_witness']!=peer.witness):raise AXRError('wechat_job_not_owned')
                if job['state']=='DisclosureReady':return self.disclose_page(peer,job)
                return self.public_job(job)
        if method=='wechat_read_messages' and self.approval_required():
            self.check()
            if not self.scope['disclose']:raise AXRError('wechat_model_disclosure_not_authorized')
            identity=args['conversation_id'];page=self.read(identity,since=args.get('since',0),cursor=args.get('cursor'),limit=args.get('limit',6))
            from axr_integration.content_safety import mask_credentials
            page={**page,'messages':[{**row,'text':mask_credentials(row['text'])[0]} for row in page['messages']]}
            key='disclose-'+secrets.token_hex(32)
            self.save_job(key,{'id':key,'kind':'mcp-disclosure','conversation_id':identity,'operation':'disclosure.send',
                'page':page,'state':'AwaitingDisclosureApproval','created':time.time(),'expires':time.time()+300,
                'client_witness':peer.witness,'scope_generation':self.generation,'retry':False})
            return {'job_id':key,'state':'AwaitingDisclosureApproval','body_disclosed':False,'retry':False}
        result=super().dispatch(peer,packet)
        if method=='wechat_status':result['manual_approval_required']=self.approval_required()
        if method in ('wechat_send_message','wechat_prepare_reply'):result=self.public_job(result)
        return result
    def release_handler(self,actual):
        with self.kernel.lock:
            self.registry.retire(actual)
            current=self.kernel.wechat_handlers.get('native')
            if current and (current.pid,current.birth)==(actual['pid'],actual['birth']):self.kernel.wechat_handlers.pop('native',None)
    def readiness(self):
        if self.kernel.development_fixture:return super().readiness()
        readable=bool(self.config['shards'])
        for shard in self.config['shards']:
            try:
                with open(shard['path'],'rb') as stream:header=stream.read(16)
                if header.hex()!=shard['salt']:readable=False
            except OSError:readable=False
        try:
            navigation=self.config['reply_navigation']
            if self.navigation.sha!=navigation['helper_sha256']:raise ValueError()
            pins={profile['visual_binding']['executable_hash'] for profile in navigation['profiles'].values()}
            if len(pins)!=1:raise ValueError()
            def alive():
                if self.stop_event.is_set():raise AXRError('wechat_service_stopped')
            value=self.navigation.readiness(pins.pop(),check=alive)
            accessible=value['running'] is True and value['ambiguous_process'] is False and value['accessibility'] is True
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):accessible=False
        return {'database':readable,'accessibility':accessible}
    def provider_readiness(self):
        result=super().provider_readiness()
        if not result['ready'] or self.kernel.development_fixture:return result
        try:
            provider=self.config['codex_provider']
            CodexSourceProvider(provider['binary'],provider['sha256'],provider['auth_file'],provider['workspace'],
                tls_bundle=provider['tls_bundle'],claim=lambda *args:None,observe=lambda *args:None)
            return result
        except (AXRError,OSError) as error:
            result={'ready':False,'code':str(error) if isinstance(error,AXRError) else 'codex_provider_unavailable'}
            if self.provider_cache:self.provider_cache=(self.provider_cache[0],result)
            return result
    def inspect_binding(self,*,activity=False):
        if not self.scope:
            if not self.readiness()['accessibility']:raise AXRError('wechat_main_window_unavailable')
            return {} # Pre-consent metadata check; never used as an account/recipient witness.
        identity=getattr(self.context,'recipient',None) or self.scope['targets'][0]
        return self.window_binding(identity,self.check)
    def window_binding(self,identity,check):
        check();visual=self.config['reply_navigation']['profiles'][identity]['visual_binding']
        action=Action(PRINCIPAL,Resource('wechat',self.config['account_id'],'axr:application-ui'),'status.read',
            'wechat-owner-service',{'mode':'binding','text':'AXR main-window metadata','visual_binding':visual})
        previous=getattr(self.context,'recipient',None)
        if previous is None:self.context.recipient=identity
        try:result=self.navigation.invoke(action,check=check)
        finally:self.context.recipient=previous
        if result.get('receipt',{}).get('state')!='Completed' or (result.get('native') or {}).get('main_window_verified') is not True:
            raise AXRError('reply_main_window_binding_unconfirmed')
        return result['native']['binding']
    def send(self,identity,text,*,sources=()):
        self.check()
        if identity not in self.scope['reply_targets']:raise AXRError('wechat_send_target_not_authorized')
        job=self.jobs.get(getattr(self.context,'executing_job',None),{})
        if self.approval_required() and (job.get('text')!=text or job.get('conversation_id')!=identity
            or job.get('approval')!=self.approval_seal(job)):raise AXRError('wechat_exact_owner_approval_required')
        if identity==self.config['account_id'] and text.startswith('/agent '):raise AXRError('wechat_self_command_loop_blocked')
        parking=self.parking_target(identity);profiles=self.config['reply_navigation']['profiles']
        plan=ReplyPlan(self.config['account_id'],identity,parking,profiles[identity]['label'],profiles[parking]['label'],text,
            job.get('id') or secrets.token_hex(32)).validate()
        with self.execution_lock,Lease(Path.home()/'.stellaria-axr'/'leases',['wechat',plan.account]):
            if any(j['state']=='Unknown' and j['conversation_id']==identity and j.get('text')==text for j in self.jobs.values()):
                raise AXRError('wechat_uncertain_text_never_retry')
            self.context.recipient=identity
            try:
                def local(resource,kind,parameters,operation,check):
                    check()
                    return self.local(resource.conversation_id,'messages.read',{'kind':kind,**parameters},operation)
                return self.executor.submit(plan,principal=PRINCIPAL,purpose='wechat-owner-service',sources=sources,
                    binding=self.window_binding,native=lambda action,check:self.navigation.invoke(action,check=check),
                    local=local,check=self.check)
            finally:self.context.recipient=None
