# SPDX-License-Identifier: MIT
"""Trusted application dispatcher, separate from the source model and MCP.

Only a signed local owner review creates a standing scope. Each use derives an
exact AET under a bounded TaskContract. Source models receive typed snapshots,
not this controller's identity, tools, files, owner channel or capabilities.
"""
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
import uuid
from axr import _axr_native as native
from axr.aet import AXRError,Action,Resource,Provenance,canonical,digest
from axr.authority import AuthorityKernel
from axr.ipc import PeerContext,process_identity
from axr.security import TaskContract
from .wechat_database import NativeDatabase,actor_records,saved_draft_metadata
from .wechat_execution import AuthorityNavigation
from .codex_source import CodexSourceProvider
from .wechat_targets import private_recipient
from .wechat_burst import BurstBuffer

PRINCIPAL='wechat:service'
BOUNDARY='wechat-managed-v2'
OPERATIONS=('status.read','messages.read','messages.search','reply.prepare','disclosure.send',
            'application.navigate','application.draft','messages.send')
OWNER_DESTINATION='model:codex-owner-thread'

class WeChatKernel(AuthorityKernel):
    def _task(self,peer,capability):
        # The TCB dispatcher is a native handler, never relabeled as a sandboxed
        # model. Only its exact OS birth may use the owner's delegated scope.
        if peer==getattr(self,'controller_peer',None):
            body=self._verify(capability)
            if body.get('kind')!='task' or body['contract']['agent']!=PRINCIPAL or self.identity(peer).get('identity_verified') is not True:
                raise AXRError('wechat_controller_identity_changed')
            return body['contract']
        return super()._task(peer,capability)
    def dispatch(self,peer,packet):
        if type(packet) is dict and packet.get('operation') in ('WeChat','WeChatOwner'):
            with self.lock:
                if self.closed:raise AXRError('authority_service_closed')
                self._check_integrity()
            # Never hold the authority lock while a helper connects back to
            # preflight/claim/observe. Stop remains responsive during inference.
            return self.application.dispatch(peer,packet)
        return super().dispatch(peer,packet)

class ApplicationState:
    def __init__(self,kernel):self.kernel=kernel;self.store=kernel.store;self.db=kernel.db
    def get(self,key,default=None):
        with self.kernel.lock:
            row=self.db.execute('SELECT payload FROM wechat_state WHERE name=?',(key,)).fetchone()
            return self.store.vault.open(row[0],'wechat-state:'+key) if row else default
    def set(self,key,value):
        with self.kernel.lock:
            if len(canonical(value))>1024*1024:raise AXRError('wechat_state_budget')
            self.kernel._check_integrity()
            self.db.execute('INSERT OR REPLACE INTO wechat_state VALUES(?,?)',(key,self.store.vault.seal(value,'wechat-state:'+key)))
            self.kernel.integrity.persist()

class WeChatService:
    def __init__(self,kernel,registry,application,endpoint):
        from . import _wechat_credentials
        # Narrow historical catalogs in memory. Never rewrite enrollment or
        # restore its grants; the next standing scope is separately signed.
        application={**application,'resources':[r for r in application['resources'] if private_recipient(r['conversation_id'])],
            'conversations':[r for r in application['conversations'] if private_recipient(r['conversation_id'])]}
        self.kernel=kernel;self.registry=registry;self.config=application;self.endpoint=endpoint
        self.state=ApplicationState(kernel);self.stop_event=threading.Event();self.worker_event=threading.Event()
        self.scope=None;self.capability=None;self.capabilities={};self.owner=None;self.reviews={};self.generation=0
        self.scope_lock=threading.RLock();self.execution_lock=threading.Lock();self.job_lock=threading.RLock()
        self.context=threading.local()
        self.resources={r['conversation_id']:Resource(**r) for r in application['resources']}
        self.catalog={r['conversation_id']:dict(r) for r in application['conversations']}
        if set(self.resources)!=set(self.catalog):raise AXRError('wechat_catalog_identity_mismatch')
        self.peer=kernel.controller_peer
        consumer=_wechat_credentials.WeChatConsumer(self.peer.witness,canonical(application).decode())
        self.database=NativeDatabase(consumer,application['account_id'])
        helper=Path(application['navigation_helper'])
        self.navigation=AuthorityNavigation(helper,hashlib.sha256(helper.read_bytes()).hexdigest(),endpoint,
            kernel.store.directory/'attempts',enroll_handler=self.enroll_handler,prepare=self.prepare_native,
            receipt=self.receipt)
        self.cursors={};self.baseline=0;self.reply_count=0;self.poll_position=0
        self.activity_after=[0,''];self.activity_seen={};self.activity_pending={}
        self.activity_stamp=None;self.activity_checked=0;self.poll_delay=2
        self.bursts=BurstBuffer()
        self.lifecycle={'thread_id':'','state':'awaiting_lifecycle','turn_id':None};self.bridge_token=None;self.retired_tokens={}
        self.last_error=self.state.get('worker-error',None)
        self.provider_cache=None
        self.jobs=self.state.get('jobs',{})
        # Never resume or retry work interrupted by a crash/restart.
        for job in self.jobs.values():
            if job['state'] in ('Queued','WaitingForIdle','Executing','Verifying','AwaitingAgent','HandedOff'):
                job.update(state='Unknown',retry=False,delivery_confirmed=False)
        self.state.set('jobs',self.jobs)
        self.thread=threading.Thread(target=self.loop,name='wechat-owner-dispatch',daemon=True)
    def start(self):self.thread.start()
    def close(self):
        self.stop();self.stop_event.set();self.worker_event.set()
        if self.thread.is_alive():self.thread.join(timeout=20)
        if self.thread.is_alive():raise AXRError('wechat_worker_shutdown_incomplete')
    def check(self,generation=None):
        if generation is None:generation=getattr(self.context,'generation',None)
        with self.scope_lock:
            scope=self.scope
            if (not scope or self.stop_event.is_set() or (generation is not None and generation!=self.generation)
                or (scope['expires'] and time.time()>=scope['expires'])):raise AXRError('wechat_scope_stopped_or_expired')
            if scope['max_replies'] and self.reply_count>=scope['max_replies']:raise AXRError('wechat_reply_budget_exhausted')
    def stop(self):
        # No owner authentication is needed to reduce authority. Generation is
        # changed before touching the ledger, cancelling a running provider.
        with self.scope_lock:
            self.generation+=1;self.scope=None;caps=self.capabilities;self.capabilities={};self.capability=None
        with self.kernel.lock:
            if caps:self.kernel.security.revoke('kernel')
            self.kernel.integrity.persist()
        with self.job_lock:
            for key,job in list(self.jobs.items()):
                if job['state'] in ('Queued','WaitingForIdle','AwaitingAgent','HandedOff'):self.save_job(key,{**job,'state':'Unknown' if job['state']=='HandedOff' else 'FailedSafe','retry':False})
        self.retire_bridge();self.bursts.clear()
        self.worker_event.set()
        return {'stopped':True,'revoked':True,'retry':False}
    def review(self,peer,arguments):
        self.kernel._owner(peer)
        if self.scope:raise AXRError('automatic_reply_already_active')
        readiness=self.readiness()
        if not readiness['database']:raise AXRError('wechat_full_disk_access_required')
        if arguments.get('automatic',False) and not readiness['accessibility']:raise AXRError('wechat_accessibility_required')
        if arguments.get('disclose',True):
            provider=self.provider_readiness()
            if not provider['ready']:raise AXRError(provider['code'])
        if type(arguments) is not dict or set(arguments)-{'targets','reply_targets','seconds','max_replies','automatic','disclose','style','attribution','overwrite_drafts','self_agent','send_policy','idle_seconds'}:raise AXRError('wechat_owner_scope_invalid')
        policy=arguments.get('send_policy','immediate');idle=arguments.get('idle_seconds',15)
        if policy not in ('immediate','when_idle','foreground_only','background_when_idle') or type(idle) is not int or not 5<=idle<=300:raise AXRError('wechat_owner_scope_invalid')
        targets=arguments.get('targets',[])
        if targets=='all':targets=list(self.resources)
        if type(targets) is not list or not targets or len(set(targets))!=len(targets) or set(targets)-set(self.resources):raise AXRError('wechat_owner_scope_invalid')
        seconds=arguments.get('seconds',3600);count=arguments.get('max_replies',4)
        if type(seconds) is not int or not 0<=seconds<=86400 or type(count) is not int or not 0<=count<=100000:raise AXRError('wechat_owner_scope_invalid')
        if policy=='background_when_idle' and not self.background_qualified() and not (0<seconds<=600 and 0<count<=2):raise AXRError('wechat_background_trial_requires_bounded_scope')
        for key in ('automatic','disclose','attribution','overwrite_drafts','self_agent'):
            if key in arguments and type(arguments[key]) is not bool:raise AXRError('wechat_owner_scope_invalid')
        settings=self.state.get('assistant',{'persona':'','style':'简洁、自然、直接；不编造事实。','attribution':False,'thread_id':'','thread_title':''})
        style=arguments.get('style',settings.get('persona','')+'\n'+settings['style'])
        if not isinstance(style,str) or len(style.encode())>12000:raise AXRError('wechat_owner_scope_invalid')
        if arguments.get('automatic',False) and not arguments.get('disclose',True):raise AXRError('wechat_model_disclosure_required')
        reply_targets=arguments.get('reply_targets',targets)
        if type(reply_targets) is not list or set(reply_targets)-set(targets) or (arguments.get('automatic',False) and not reply_targets):raise AXRError('wechat_owner_scope_invalid')
        self_agent=arguments.get('self_agent',False);owner_thread=settings.get('thread_id','') if self_agent else ''
        if self_agent:
            from axr_integration.assistant_settings import valid_thread
            if (not valid_thread(owner_thread) or self.config['account_id'] not in reply_targets
                or not arguments.get('disclose',True)):raise AXRError('wechat_self_agent_binding_required')
        # Metadata/account checks run BEFORE the hardware-authentication UI.
        # A missing window must not consume another owner approval.
        if arguments.get('automatic',False):self.inspect_binding()
        scope={'targets':targets,'reply_targets':reply_targets,'expires':time.time()+seconds if seconds else 0,'max_replies':count,
               'automatic':arguments.get('automatic',False),'disclose':arguments.get('disclose',True),
               'style':style,'attribution':arguments.get('attribution',settings['attribution']),
               'overwrite_drafts':arguments.get('overwrite_drafts',False),'self_agent':self_agent,'owner_thread':owner_thread,
               'send_policy':policy,'idle_seconds':idle}
        challenge={'version':2,'kind':'wechat-standing-scope','root_id':self.kernel.root_id,'epoch':self.kernel.epoch,
                   'owner':peer.principal,'peer':peer.witness,'nonce':secrets.token_hex(32),'expires':time.time()+120,
                   'scope':scope,'policy_version':self.kernel.security.guard.version,
               'operations':list(OPERATIONS),'model_destinations':[CodexSourceProvider.destination,'model:codex-mcp',*([OWNER_DESTINATION] if self_agent else [])],
                   'send_destinations':['wechat:'+self.resources[i].key for i in reply_targets],
                   'execution':policy+' original-app keyboard; once; Unknown never retries',
                   'restart_restores_authority':False}
        with self.scope_lock:
            self.reviews={k:v for k,v in self.reviews.items() if v['expires']>time.time()}
            if len(self.reviews)>=8:raise AXRError('owner_challenge_capacity')
            self.reviews[challenge['nonce']]=challenge
        reviewed={'challenge':challenge,'targets':[self.catalog[i] for i in targets[:64]],'target_count':len(targets)}
        if len(canonical(reviewed))>512*1024:raise AXRError('wechat_owner_review_budget')
        return reviewed
    def activate(self,peer,nonce,signature):
        self.kernel._owner(peer)
        with self.scope_lock:
            challenge=self.reviews.pop(nonce,None)
            if (not challenge or challenge['expires']<=time.time() or challenge['peer']!=peer.witness or
                challenge['policy_version']!=self.kernel.security.guard.version or self.scope):raise AXRError('wechat_owner_review_expired_or_changed')
            try:verified=native.verify_root_signature(self.kernel.owner_public_key,canonical(challenge),bytes.fromhex(signature))
            except Exception:verified=False
            if not verified:raise AXRError('owner_presence_signature_required')
            self.owner=peer.principal;self.scope=challenge['scope'];self.generation+=1;self.last_error=None
            self.baseline=int(time.time())+1;self.cursors={};self.reply_count=0
            self.poll_position=0;self.activity_after=[0,''];self.activity_seen={};self.activity_pending={}
            self.activity_stamp=None;self.activity_checked=0;self.poll_delay=2;self.bursts.clear()
            try:
                self.derive_contract()
                self.state.set('last-owner-consent',{'challenge':challenge,'signature':signature,'authority_restored':False})
                self.state.set('worker-error',None)
            except BaseException:self.scope=None;self.capability=None;raise
        self.worker_event.set()
        return self.status()
    def derive_contract(self,identity=None):
        # A standing owner consent can be unlimited; every derived task remains
        # finite. Only this trusted host derives it, from the signed exact scope.
        now=time.time();scope=self.scope;identity=identity or scope['targets'][0]
        if identity not in scope['targets']:raise AXRError('wechat_target_not_authorized')
        keys=[self.resources[identity].key]
        contract=TaskContract(uuid.uuid4().hex,self.owner,PRINCIPAL,'wechat',digest(scope),'incoming','external-message',
            OPERATIONS,tuple(keys),tuple(keys),tuple(['local',CodexSourceProvider.destination,'model:codex-mcp',*([OWNER_DESTINATION] if scope.get('self_agent') and identity==self.config['account_id'] else []),*['wechat:'+k for k in keys]]),
            ('personal','workspace-normal'),('ReplyDraft','Summary'),BOUNDARY,False,now,
            min(now+3600,scope['expires']) if scope['expires'] else now+3600,100000,self.kernel.security.guard.version)
        with self.kernel.lock:
            self.kernel.security.authorize(contract,lambda:self.owner)
            self.capability=self.kernel._signed({'version':2,'kind':'task','root_id':self.kernel.root_id,
                'epoch':self.kernel.epoch,'contract':contract.body()})
            self.capabilities[identity]=self.capability
            # Source-read permission is separate from each exact action grant.
            self.kernel.store.guard._issue_owner(principal=PRINCIPAL,resource=self.resources[identity],operations=['messages.read'],
                purpose='wechat-owner-service',expires_at=contract.expires,max_uses=100000,classes=['personal','workspace-normal'])
            self.kernel.integrity.persist()
            return self.capability
    def contract(self,identity):
        self.check()
        with self.kernel.lock:
            cap=self.capabilities.get(identity)
            if cap:
                row,_=self.kernel.security._contract(cap['body']['contract']['id'])
                if not row['revoked'] and row['used']<99000 and cap['body']['contract']['expires']>time.time()+5:return cap
            return self.derive_contract(identity)
    def action(self,identity,operation,payload,*,destination='local',sources=()):
        self.check()
        if identity not in self.scope['targets']:raise AXRError('wechat_target_not_authorized')
        return Action(PRINCIPAL,self.resources[identity],operation,'wechat-owner-service',payload,
                      destination=destination,sources=tuple(sources))
    def prepare(self,action):
        self.check()
        with self.kernel.lock:
            capability=self.contract(action.resource.conversation_id)
            for source in action.sources:
                if action.destination!='local':
                    from dataclasses import replace
                    disclosure=replace(action,resource=source.resource,operation='disclosure.send',payload={'output_seal':action.seal},sources=(source,))
                    self.kernel.store.guard._issue_owner(principal=PRINCIPAL,resource=source.resource,operations=['disclosure.send'],purpose=action.purpose,
                        expires_at=min(time.time()+60,capability['body']['contract']['expires']),max_uses=1,
                        classes=[source.data_class],destinations=[action.destination],intent=disclosure.seal)
            self.kernel.store.guard._issue_owner(principal=PRINCIPAL,resource=action.resource,operations=[action.operation],purpose=action.purpose,
                expires_at=min(time.time()+60,capability['body']['contract']['expires']),max_uses=1,
                classes=['personal','workspace-normal'],destinations=[action.destination],intent=action.seal)
            self.kernel.integrity.persist()
            return self.kernel.prepare_commit(self.peer,capability,action)
    def local(self,identity,operation,payload,function):
        generation=self.generation;action=self.action(identity,operation,payload);proof=self.prepare(action)
        def check():
            self.check(generation)
            self.kernel.preflight_commit(self.peer,proof)
        self.kernel.claim_commit(self.peer,proof)
        result=function(check);check()
        self.kernel.observe(self.peer,proof,verified=True,evidence_digest=digest(result))
        with self.kernel.lock:self.kernel.security.bindings.pop(action.execution_id,None)
        return result
    def read(self,identity,*,since=0,cursor=None,limit=6):
        return self.local(identity,'messages.search',{'since':since,'cursor':cursor,'limit':limit},
            lambda check:self.database.search(identity,check=check,since=since,after=cursor,limit=limit))
    def nav_state(self,identity,kind,**parameters):
        return self.local(identity,'messages.read',{'kind':kind,**parameters},
            lambda check:self.database.navigation(identity,kind,check,**parameters))
    def scan_targets(self):
        self.check();targets=list(self.scope['reply_targets'] or self.scope['targets'])
        # Broad metadata is available only under the owner's full account grant.
        # Restricted grants continue to query only their own exact sources.
        if (len(targets)>8 and set(targets)==set(self.resources)==set(self.scope['targets'])
            and self.config['account_id'] in self.resources):
            stamp=[]
            for shard in self.config['shards']:
                if shard['role'] not in ('session','message'):continue
                for path in (shard['path'],shard['path']+'-wal'):
                    try:
                        st=os.stat(path);stamp.append((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns))
                    except FileNotFoundError:
                        if path==shard['path']:raise
                        stamp.append(None)
            now=time.monotonic()
            if (stamp and stamp==self.activity_stamp and not self.activity_pending
                and self.activity_after==[0,''] and now-self.activity_checked<15):
                self.poll_delay=min(8,self.poll_delay*2);return []
            self.activity_stamp=stamp;self.activity_checked=now;self.poll_delay=2
            page=self.local(self.config['account_id'],'status.read',
                {'kind':'account-activity','since':self.baseline,'after':self.activity_after,
                 'limit':128,'resource_set':digest(sorted(targets))},
                lambda check:self.database.activity(since=self.baseline,after=self.activity_after,check=check))
            for row in page['rows']:
                identity=row['conversation_id']
                if identity not in self.resources:raise AXRError('wechat_activity_target_not_enrolled')
                version=(row['updated'],row['local_id'])
                if self.activity_seen.get(identity)!=version:self.activity_pending[identity]=version
            self.activity_after=page['after'] if page['has_more'] else [0,'']
            return list(self.activity_pending)[:8]
        scan=(targets+targets)[self.poll_position:self.poll_position+min(8,len(targets))]
        self.poll_position=(self.poll_position+min(8,len(targets)))%len(targets)
        return scan
    def finish_scan(self,identity,page):
        if not page['has_more'] and identity in self.activity_pending:
            self.activity_seen[identity]=self.activity_pending.pop(identity)
    def owner_command(self,identity,row):
        if identity!=self.config['account_id'] or not isinstance(row.get('text'),str) or not row['text'].startswith('/agent '):return False
        if not self.scope.get('self_agent'):return False
        self.check();key='owner-'+digest([identity,row['reference']])
        if key in self.jobs:return True
        from axr_integration.content_safety import mask_credentials
        text=mask_credentials(row['text'][7:])[0]
        if not text.strip() or len(text.encode())>16000:raise AXRError('wechat_owner_command_budget')
        self.save_job(key,{'id':key,'conversation_id':identity,'state':'AwaitingAgent','created':time.time(),
            'expires':time.time()+900,'operation':'owner.command','channel':'self','prompt':text,'text':text,'generation':self.generation,
            'thread_id':self.scope['owner_thread'],'source':row['reference'],'retry':False,'delivery_confirmed':False})
        return True
    def retire_bridge(self):
        now=time.monotonic();self.retired_tokens={k:v for k,v in self.retired_tokens.items() if v>now}
        if self.bridge_token:self.retired_tokens[self.bridge_token]=now+30
        if len(self.retired_tokens)>8:self.retired_tokens.pop(min(self.retired_tokens,key=self.retired_tokens.get))
        self.bridge_token=None
    def lifecycle_event(self,args):
        if (set(args)-{'thread_id','event','turn_id','worker_token'} or args.get('event') not in ('UserPromptSubmit','SessionStart','Stop','Interrupt')
            or any(v is not None and (not isinstance(v,str) or len(v)>256) for v in args.values())):raise AXRError('wechat_lifecycle_invalid')
        selected=(self.scope or {}).get('owner_thread') or self.state.get('assistant',{}).get('thread_id')
        if not selected or args.get('thread_id')!=selected:return {'ignored':True}
        if self.bridge_token and secrets.compare_digest(args.get('worker_token') or '',self.bridge_token):return {'worker_event':True}
        if any(expires>time.monotonic() and secrets.compare_digest(args.get('worker_token') or '',token) for token,expires in self.retired_tokens.items()):return {'worker_event':True}
        event=args['event'];state='busy' if event in ('UserPromptSubmit','SessionStart') else 'paused' if event=='Interrupt' else 'idle'
        # A late Stop for an older turn cannot declare the current turn idle.
        if event=='Stop' and self.lifecycle.get('turn_id') not in (None,args.get('turn_id')):return {'ignored':True}
        self.lifecycle={'thread_id':selected,'state':state,'turn_id':args.get('turn_id'),'ready_at':time.monotonic()+2}
        return {'recorded':True}
    def cancel_owner_task(self,args):
        job=self.jobs.get(args.get('job_id'))
        if set(args)!={'job_id'} or not job or job.get('channel') not in ('desktop','self') or job.get('thread_id')!=self.state.get('assistant',{}).get('thread_id'):
            raise AXRError('wechat_owner_command_not_active')
        if job['state'] in ('AwaitingAgent','HandedOff'):
            self.save_job(job['id'],{**job,'state':'Unknown' if job['state']=='HandedOff' else 'FailedSafe','retry':False})
            if job['state']=='HandedOff':self.retire_bridge()
        return {'stopped':True,'retry':False}
    def owner_messages(self):
        thread=self.state.get('assistant',{}).get('thread_id');rows=[]
        for j in self.jobs.values():
            if j.get('thread_id')!=thread or not j.get('prompt'):continue
            if j.get('channel')!='desktop' and not (j.get('channel')=='self' and (self.scope or {}).get('self_agent') and j['generation']==self.generation):continue
            rows.append({'id':j['id'],'prompt':j['prompt'],'answer':j.get('text') if j['state'] in ('Completed','Observed') else '',
                'state':j['state'],'created':j['created'],'channel':j.get('channel'),'model':j.get('model','')})
        return sorted(rows,key=lambda j:j['created'])[-8:]
    def queue_owner_prompt(self,args):
        if set(args)-{'text','request_id','model','effort'} or not {'text','request_id'}<=set(args) or not isinstance(args['request_id'],str) or not __import__('re').fullmatch('[0-9a-f]{32}',args['request_id']) or not isinstance(args['text'],str) or not args['text'].strip() or len(args['text'].encode())>16000:
            raise AXRError('wechat_owner_command_budget')
        if ('model' in args and (not isinstance(args['model'],str) or not __import__('re').fullmatch('[a-z0-9][a-z0-9._-]{0,99}',args['model']))) or ('effort' in args and args['effort'] not in ('none','minimal','low','medium','high','xhigh','max','ultra')):raise AXRError('wechat_owner_model_invalid')
        from axr_integration.assistant_settings import valid_thread
        thread=self.state.get('assistant',{}).get('thread_id','')
        if not valid_thread(thread):raise AXRError('wechat_self_agent_binding_required')
        if sum(j['state'] in ('AwaitingAgent','HandedOff') for j in self.jobs.values())>=32:raise AXRError('wechat_owner_queue_capacity')
        key='desktop-'+digest([thread,args['request_id']]);now=time.time()
        if key in self.jobs:
            if self.jobs[key].get('prompt')!=args['text'] or any(self.jobs[key].get(k)!=args.get(k) for k in ('model','effort')):raise AXRError('wechat_idempotency_content_changed')
            return {'job_id':key,'state':self.jobs[key]['state'],'retry':False}
        if any(j.get('channel')=='desktop' and j['state']=='Unknown' and j.get('prompt')==args['text'] for j in self.jobs.values()):raise AXRError('wechat_uncertain_text_never_retry')
        self.save_job(key,{'id':key,'conversation_id':self.config['account_id'],'channel':'desktop',
            'prompt':args['text'],'text':args['text'],**{k:args[k] for k in ('model','effort') if k in args},'thread_id':thread,'created':now,'expires':now+900,
            'operation':'owner.command','state':'AwaitingAgent','generation':self.generation,'retry':False,'delivery_confirmed':False})
        return {'job_id':key,'state':'AwaitingAgent'}
    def claim_owner_task(self):
        local_pending=any(j.get('channel')=='desktop' and j['state'] in ('AwaitingAgent','HandedOff') for j in self.jobs.values())
        if not local_pending and not (self.scope or {}).get('self_agent'):raise AXRError('wechat_self_agent_not_authorized')
        if self.bridge_token and not any(j['state']=='HandedOff' and j['expires']>time.time() for j in self.jobs.values()):
            for key,j in list(self.jobs.items()):
                if j['state']=='HandedOff':self.save_job(key,{**j,'state':'Unknown','error':'owner_agent_handoff_expired'})
            self.bridge_token=None
        selected=(self.scope or {}).get('owner_thread') or self.state.get('assistant',{}).get('thread_id')
        if (self.lifecycle.get('thread_id')!=selected or self.lifecycle['state']!='idle'
            or time.monotonic()<self.lifecycle.get('ready_at',0) or self.bridge_token):return {'pending':True,'ready':False}
        with self.job_lock:
            job=next((j for j in self.jobs.values() if j['state']=='AwaitingAgent'),None)
            if not job:return {'pending':False,'ready':False}
            if job['expires']<=time.time() or job['generation']!=self.generation or job['thread_id']!=selected:
                self.save_job(job['id'],{**job,'state':'FailedSafe'});return {'pending':True,'ready':False}
            if job.get('channel')=='desktop':
                # Direct owner input is not a disclosure of WeChat data and
                # never creates a read/send scope. Bind the same single handoff.
                self.save_job(job['id'],{**job,'state':'HandedOff'});self.bridge_token=secrets.token_hex(32)
                return {'ready':True,'job_id':job['id'],'thread_id':job['thread_id'],'text':job['text'],
                    'worker_token':self.bridge_token,'expires':job['expires'],'channel':'desktop','retry':False,**{k:job[k] for k in ('model','effort') if k in job}}
            self.check()
            if not self.scope.get('self_agent'):raise AXRError('wechat_self_agent_not_authorized')
            action=self.action(self.config['account_id'],'disclosure.send',{'job_id':job['id'],'thread_id':job['thread_id'],'command_digest':digest(job['text'])},
                destination=OWNER_DESTINATION,sources=(Provenance(self.resources[self.config['account_id']],job['source'],'personal'),))
            proof=self.prepare(action);self.kernel.claim_commit(self.peer,proof)
            self.save_job(job['id'],{**job,'state':'HandedOff'})
            self.kernel.observe(self.peer,proof,verified=True,evidence_digest=digest([job['id'],job['thread_id'],job['text']]))
            self.bridge_token=secrets.token_hex(32)
            return {'ready':True,'job_id':job['id'],'thread_id':job['thread_id'],'text':job['text'],
                    'worker_token':self.bridge_token,'expires':job['expires'],'retry':False}
    def finish_owner_task(self,args):
        job=self.jobs.get(args.get('job_id'))
        if not job or job.get('channel')!='desktop':self.check()
        if (set(args)-{'job_id','text','failed'} or not job or job['state']!='HandedOff' or job['generation']!=self.generation
            or job['expires']<=time.time() or (job.get('channel')!='desktop' and not self.scope.get('self_agent')) or type(args.get('failed',False)) is not bool):raise AXRError('wechat_owner_command_not_active')
        if args.get('failed',False):self.save_job(job['id'],{**job,'state':'Unknown','error':'owner_agent_handoff_uncertain'})
        else:
            text=args.get('text')
            if not isinstance(text,str) or not text.strip() or len(text.encode())>16000 or text.startswith('/agent '):raise AXRError('wechat_owner_command_budget')
            self.save_job(job['id'],{**job,'text':text,'operation':'owner.command' if job.get('channel')=='desktop' else 'messages.send',
                'state':'Completed' if job.get('channel')=='desktop' else 'Queued'})
        self.retire_bridge();self.worker_event.set();return {'recorded':True,'retry':False}
    def enroll_handler(self,actual):
        with self.kernel.lock:
            self.kernel._check_integrity()
            self.registry.enroll(actual,'handler','wechat:navigation',lambda:self.registry.user)
            self.kernel.wechat_handlers['native']=self.registry.accept(actual)
    def prepare_native(self,action,actual):
        if self.kernel.wechat_handlers['native']!=self.registry.accept(actual):raise AXRError('wechat_handler_identity_changed')
        return self.prepare(action)
    def receipt(self,execution_id):
        with self.kernel.lock:
            row=self.kernel.db.execute('SELECT state FROM authority_commits WHERE execution_id=?',(execution_id,)).fetchone()
            if row and row[0] not in ('Prepared','Executing'):self.kernel.security.bindings.pop(execution_id,None)
            return {'state':row[0] if row else 'FailedSafe','execution_id':execution_id,'retry':False,'delivery_confirmed':False}
    def binding(self):
        self.check()
        return self.inspect_binding()
    def inspect_binding(self,*,activity=False):
        helper=self.config['navigation_helper']
        p=subprocess.run([helper],input=canonical({'mode':'binding'}),capture_output=True,timeout=6)
        import json
        reply=json.loads(p.stdout)
        if p.returncode or 'binding' not in reply:raise AXRError('wechat_main_window_unavailable')
        binding=reply['binding'];binding.pop('assurance',None)
        result=subprocess.run(['/usr/sbin/lsof','-p',str(binding['pid']),'-Fn'],capture_output=True,text=True,timeout=5)
        opened={line[1:] for line in result.stdout.splitlines() if line.startswith('n')}
        expected={s['path'] for s in self.config['shards'] if s['role'] in ('session','contact')}
        if len(expected)!=2 or not expected<=opened:raise AXRError('runtime_account_witness_changed')
        return {**binding,'application_active':reply.get('application_active') is True} if activity else binding
    def send_wait_reason(self):
        self.check()
        from .send_schedule import idle_seconds,readiness
        policy=self.scope.get('send_policy','immediate')
        if policy=='immediate':return None
        idle=idle_seconds()
        foreground=False
        if policy=='foreground_only' and idle is not None and idle>=self.scope.get('idle_seconds',15):
            try:foreground=self.inspect_binding(activity=True).get('application_active') is True
            except Exception:return 'wechat_unavailable'
        if policy=='background_when_idle' and idle is not None and idle>=self.scope.get('idle_seconds',15):
            try:
                if self.inspect_binding(activity=True).get('application_active') is True:return 'wechat_foreground'
            except Exception:return 'wechat_unavailable'
        return readiness(policy,self.scope.get('idle_seconds',15),idle=idle,foreground=foreground)
    def background_qualified(self):
        record=self.state.get('background-route',{})
        return bool(record and record.get('helper_sha256')==hashlib.sha256(Path(self.config['navigation_helper']).read_bytes()).hexdigest())
    def navigate(self,identity,*,idle_admitted=False):
        started=time.time();binding=self.binding();text=self.catalog[identity]['display_name']
        binding={**binding,'activation_policy':self.scope.get('send_policy','immediate'),'idle_seconds':self.scope.get('idle_seconds',15)}
        # One exact navigation transaction. The native helper validates its
        # five-second permit locally between keys, avoiding per-key RPC stalls.
        for phase in ('complete',):
            # Admission belongs to the whole send transaction. Its own keys
            # reset macOS idle time; continuation still requires the exact
            # active window, pointer epoch, scope and fresh recipient witness.
            action=self.action(identity,'application.navigate',{'mode':'navigate','text':text,'visual_binding':{**binding,'idle_gate':'continuation' if idle_admitted else 'initial'},
                'navigation_binding':{'menu_path':['编辑','搜索'],'main_window_id':binding['window_id'],'query':text,'phase':phase}})
            result=self.navigation.invoke(action,check=self.check)
            if result['receipt']['state']!='Completed':
                # Fixed native machine codes only, never raw diagnostics/data.
                import re
                code=(result.get('native') or {}).get('error','unconfirmed')
                if not isinstance(code,str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',code):code='unconfirmed'
                raise AXRError('wechat_navigation_'+phase+'_'+code)
        self.check()
        data=result.get('native') or {}
        if (data.get('navigation_invoked') is not True or data.get('query_input_submitted') is not True
            or data.get('main_window_verified') is not True or data.get('send_invoked') is not False):
            raise AXRError('wechat_navigation_result_unconfirmed')
        rows=self.nav_state(identity,'recent',query=text,since=int(started)-1)
        if len(rows)!=1 or rows[0]['username']!=identity or rows[0]['query']!=text or not started-1<=rows[0]['last_click_time']<=time.time()+1:
            raise AXRError('wechat_unique_fresh_recipient_required')
        return binding,started,rows
    def send(self,identity,text,*,sources=()):
        if not isinstance(text,str) or not text.strip() or len(text.encode())>16000:raise AXRError('wechat_text_budget')
        self.check()
        if identity not in self.scope['reply_targets']:raise AXRError('wechat_send_target_not_authorized')
        if identity==self.config['account_id'] and text.startswith('/agent '):raise AXRError('wechat_self_command_loop_blocked')
        with self.execution_lock:
            if any(j['state']=='Unknown' and j['conversation_id']==identity and j.get('text')==text for j in self.jobs.values()):raise AXRError('wechat_uncertain_text_never_retry')
            self.check();parking=self.parking_target(identity)
            rows=self.nav_state(identity,'draft')
            if len(rows)!=1:raise AXRError('wechat_existing_draft_preserved')
            # SessionTable can retain text after the user cleared the live
            # composer. The pinned helper checks current edit-command state
            # immediately before insertion; cached nonempty text is not proof.
            before=int(time.time())-30;baseline=self.read(identity,since=before);prior={r['reference'] for r in baseline['messages']}
            if baseline['has_more']:raise AXRError('wechat_send_baseline_requires_bounded_page')
            window,_,_=self.navigate(identity)
            stage_binding={**window,'draft_policy':'replace' if self.scope.get('overwrite_drafts',False) else 'preserve'}
            staged=self.navigation.invoke(self.action(identity,'application.draft',{'mode':'stage_draft','text':text,'visual_binding':stage_binding}),check=self.check)
            if (staged.get('native') or {}).get('error')=='existing_input_preserved':raise AXRError('wechat_existing_draft_preserved')
            if staged['receipt']['state']!='Completed' or staged.get('native',{}).get('draft_match') is not True:
                import re
                code=(staged.get('native') or {}).get('error','exact_input_required')
                if not isinstance(code,str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',code):code='unconfirmed'
                raise AXRError('wechat_draft_'+code)
            self.navigate(parking,idle_admitted=True)
            cache=self.nav_state(identity,'unique_draft',text=text);observed=time.time();observed_mono=time.monotonic()
            binding,started,search=self.navigate(identity,idle_admitted=True)
            draft=self.nav_state(identity,'draft')
            if (binding!=window or time.monotonic()-observed_mono>60 or not observed<=started or
                len(draft)!=1 or draft[0]['draft'] not in ('',text)):raise AXRError('wechat_cached_recipient_witness_changed')
            binding={**binding,'recipient_assurance':'cached_exact_draft_and_fresh_search',
                'recipient_witness':digest([cache,search,draft,text,window,started])}
            action=self.action(identity,'messages.send',{'mode':'send','text':text,'visual_binding':binding},
                destination='wechat:'+self.resources[identity].key,sources=sources)
            result=self.navigation.invoke(action,check=self.check)
            matches=[]
            # Independent readback does not turn an uncertain input receipt into
            # permission to retry, or assert remote delivery.
            for _ in range(12):
                page=self.read(identity,since=before,cursor=baseline['cursor'])
                matches=[r for r in page['messages'] if r['reference'] not in prior and r['outgoing'] is True and r['text']==text and type(r.get('server_id')) is int and r['server_id']>0]
                if matches:break
                self.stop_event.wait(.5)
            native_result=result.get('native') or {}
            if (self.scope.get('send_policy')=='background_when_idle' and len(matches)==1
                and native_result.get('send_invoked') is True and native_result.get('started_background') is True
                and native_result.get('foreground_unchanged') is True):
                self.state.set('background-route',{'helper_sha256':hashlib.sha256(Path(self.config['navigation_helper']).read_bytes()).hexdigest(),'verified':time.time()})
            return {**result,'exact_database_records':len(matches),'database_record_observed':len(matches)==1,
                'retry':False,'delivery_confirmed':False}
    def parking_target(self,identity):
        if identity!=self.config['account_id'] and self.config['account_id'] in self.scope['targets']:return self.config['account_id']
        # A broad catalog's first entry is not a qualified navigation target.
        # Prefer a real observed private peer still in the current scope. Every
        # actual navigation continues to require a new unique stable-ID witness.
        for job in sorted(self.jobs.values(),key=lambda j:j['created'],reverse=True):
            candidate=job['conversation_id']
            if (job['state']=='Observed' and (job.get('result') or {}).get('database_record_observed') is True
                and candidate!=identity and candidate in self.scope['reply_targets']):return candidate
        candidates=[i for i in self.scope['reply_targets'] if i!=identity]
        if len(candidates)==1:return candidates[0]
        raise AXRError('wechat_verified_parking_conversation_required')
    def save_job(self,key,value):
        with self.job_lock:
            if len(self.jobs)>=1000 and key not in self.jobs:raise AXRError('wechat_job_capacity')
            self.jobs[key]=value;self.state.set('jobs',self.jobs)
    def queue(self,identity,text,request_id,*,manual=False):
        self.check()
        if identity not in self.scope['targets']:raise AXRError('wechat_target_not_authorized')
        if not manual and identity not in self.scope['reply_targets']:raise AXRError('wechat_send_target_not_authorized')
        if not isinstance(text,str) or not text.strip() or len(text.encode())>16000:raise AXRError('wechat_text_budget')
        key=digest([identity,request_id])
        with self.job_lock:
            if key in self.jobs:
                if self.jobs[key].get('text')!=text:raise AXRError('wechat_idempotency_content_changed')
                return {'job_id':key,**{k:v for k,v in self.jobs[key].items() if k!='text'}}
            if not manual and any(j['state']=='Unknown' and j['conversation_id']==identity and j.get('text')==text for j in self.jobs.values()):raise AXRError('wechat_uncertain_text_never_retry')
            value={'id':key,'conversation_id':identity,'text':text,'state':'Draft' if manual else 'Queued',
                'created':time.time(),'expires':time.time()+900,'operation':'reply.prepare' if manual else 'messages.send',
                'retry':False,'delivery_confirmed':False}
            self.save_job(key,value)
        self.worker_event.set();return {'job_id':key,'state':value['state'],'retry':False}
    def infer(self,identity,page):
        if not self.scope['disclose']:raise AXRError('wechat_model_disclosure_not_authorized')
        records=actor_records(page,include_outgoing=True)
        if not records:return None
        generation=self.generation;resource=self.resources[identity]
        capability=self.contract(identity)
        request={'version':2,'context_id':uuid.uuid4().hex,'contract':capability['body']['contract']['id'],
            'records':records,'style':self.scope['style'],'allowed_outputs':['ReplyDraft'],'source_keys':[resource.key],
            'tools':[],'history':[],'parent_context':None}
        action=self.action(identity,'disclosure.send',{'request_digest':digest(request),'context_id':request['context_id']},
            destination=CodexSourceProvider.destination,sources=(Provenance(resource,digest(records),'personal'),))
        proof=self.prepare(action)
        provider=self.config['codex_provider']
        if hashlib.sha256(Path(provider['tls_bundle']).read_bytes()).hexdigest()!=provider['tls_sha256']:raise AXRError('codex_provider_trust_bundle_changed')
        source=CodexSourceProvider(provider['binary'],provider['sha256'],provider['auth_file'],provider['workspace'],
            tls_bundle=provider['tls_bundle'],claim=lambda a,p:self.kernel.claim_commit(self.peer,p),
            observe=lambda a,p,e:self.kernel.observe(self.peer,p,verified=True,evidence_digest=e))
        def check():
            self.check(generation)
            # Model inference may exceed the five-second final-input claim.
            # Its authority was consumed BEFORE disclosure; never mint a second
            # permit or resend a request on a timeout.
            row,contract=self.kernel.security._contract(capability['body']['contract']['id'])
            if row['revoked'] or time.time()>=contract['expires']:raise AXRError('wechat_scope_stopped_or_expired')
        output=source.complete(action,request,proof,check)
        text=output['content']
        if self.scope['attribution']:text='【AI 助理】'+text
        return text
    def status(self):
        active=bool(self.scope and (not self.scope['expires'] or self.scope['expires']>time.time()))
        permissions=self.readiness()
        # Verify the chain and independent checkpoint against one serialized
        # journal view. Concurrent append/anchor must not produce a false alarm;
        # a real invalid chain is still returned unchanged as False.
        with self.kernel.lock:audit_valid=self.kernel.store.journal.verify_audit()
        return {'axr':True,'operational':True,'authority':'independent-native-v2','owner_authorized':active,
            'automatic_reply':bool(active and self.scope['automatic']),'scope':self.scope if active else None,
            'permissions':permissions,'send_available':active and bool(self.scope['reply_targets']) and permissions['database'] and permissions['accessibility'],
            'listener':{'listen':active,'wake_agent':active,'auto_execute':active and self.scope['automatic']},
            'platform':{'mode':'wcdb-native','send_available':active and bool(self.scope['reply_targets']) and permissions['database'] and permissions['accessibility']},'audit_valid':audit_valid,
            'policy_version':self.kernel.store.guard.version,'reply_count':self.reply_count,'retry_unknown':False,
            'delivery_confirmed':False,'body_disclosed':False,'pause_reason':self.last_error,'inference':self.provider_readiness(),
            'background_send_qualified':self.background_qualified()}
    def provider_readiness(self):
        if self.kernel.development_fixture:return {'ready':True,'code':None}
        try:
            provider=self.config['codex_provider']
            paths=[Path(provider[key]) for key in ('binary','auth_file','tls_bundle')]
            stamp=tuple((p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in paths)
            if self.provider_cache and self.provider_cache[0]==stamp:return self.provider_cache[1]
            code=None
            if hashlib.sha256(paths[0].read_bytes()).hexdigest()!=provider['sha256']:code='codex_provider_build_changed'
            elif not 0<paths[1].stat().st_size<=1024*1024:code='codex_provider_login_required'
            elif hashlib.sha256(paths[2].read_bytes()).hexdigest()!=provider['tls_sha256']:code='codex_provider_trust_bundle_changed'
            result={'ready':code is None,'code':code};self.provider_cache=(stamp,result);return result
        except (OSError,KeyError,ValueError):return {'ready':False,'code':'codex_provider_unavailable'}
    def readiness(self):
        if self.kernel.development_fixture:return {'database':True,'accessibility':True,'synthetic':True}
        readable=True
        for shard in self.config['shards']:
            try:
                with open(shard['path'],'rb') as stream:header=stream.read(16)
                if header.hex()!=shard['salt']:readable=False
            except OSError:readable=False
        import ctypes
        try:
            api=ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
            api.AXIsProcessTrusted.restype=ctypes.c_bool;accessible=bool(api.AXIsProcessTrusted())
        except OSError:accessible=False
        return {'database':readable,'accessibility':accessible}
    def dispatch(self,peer,packet):
        p=packet.get('payload',{})
        if type(p) is not dict:raise AXRError('wechat_request_invalid')
        if packet['operation']=='WeChatOwner':
            self.kernel._owner(peer);method=p.get('method');args=p.get('arguments',{})
            if method=='review':return self.review(peer,args)
            if method=='activate':return self.activate(peer,args['nonce'],args['signature'])
            if method=='stop':return self.stop()
            if method=='codex_lifecycle':return self.lifecycle_event(args)
            if method=='claim_owner_task':return self.claim_owner_task()
            if method=='queue_owner_prompt':return self.queue_owner_prompt(args)
            if method=='cancel_owner_task':return self.cancel_owner_task(args)
            if method=='finish_owner_task':return self.finish_owner_task(args)
            if method=='assistant_settings':return self.state.get('assistant',{'thread_id':'','thread_title':'','persona':'','style':'简洁、自然、直接；不编造事实。','attribution':False})
            if method=='save_assistant_settings':
                if self.scope:raise AXRError('stop_automatic_before_settings_change')
                if set(args)-{'thread_id','thread_title','persona','style','attribution'} or any(not isinstance(v,str) or len(v.encode())>12000 for k,v in args.items() if k!='attribution') or type(args.get('attribution',False)) is not bool:raise AXRError('wechat_assistant_settings_invalid')
                value={**self.state.get('assistant',{'thread_id':'','thread_title':'','persona':'','style':'简洁、自然、直接；不编造事实。','attribution':False}),**args}
                self.state.set('assistant',value);return value
            if method=='snapshot':
                return {'status':self.status(),'conversations':[{**c,'is_self':c['conversation_id']==self.config['account_id']} for c in self.catalog.values()],'jobs':[
                    {k:v for k,v in j.items() if k not in ('text','prompt')} for j in self.jobs.values()],
                    'drafts':[{'job_id':k,'display_name':self.catalog[j['conversation_id']]['display_name'],
                        'expires':j['expires']} for k,j in self.jobs.items() if j['state']=='Draft' and j['expires']>time.time()],
                    'grants':[],'summaries':[],'thread_binding':self.lifecycle,
                    'owner_agent_enabled':bool(self.scope and self.scope.get('self_agent')) or any(j.get('channel')=='desktop' and j['state'] in ('AwaitingAgent','HandedOff') for j in self.jobs.values()),
                    'owner_messages':self.owner_messages()}
            if method=='check_target':
                self.check();identity=args.get('conversation_id')
                if (set(args)-{'conversation_id','metadata_only','isolated_snapshot'} or 'conversation_id' not in args
                    or type(args.get('metadata_only',False)) is not bool
                    or type(args.get('isolated_snapshot',False)) is not bool
                    or (args.get('isolated_snapshot',False) and not args.get('metadata_only',False))
                    or identity not in self.scope['reply_targets']):raise AXRError('wechat_owner_scope_invalid')
                started=time.monotonic()
                try:
                    if not args.get('metadata_only',False):self.navigate(identity)
                    rows=self.nav_state(identity,'draft')
                    return {'navigation_verified':not args.get('metadata_only',False),'draft_present':len(rows)!=1 or rows[0]['draft']!='',
                        'cached_draft_metadata':saved_draft_metadata(rows[0]) if len(rows)==1 else {},
                        'session_schema':self.nav_state(identity,'session_schema') if args.get('metadata_only',False) else [],
                        'session_state':self.nav_state(identity,'session_state') if args.get('metadata_only',False) else [],
                        'message_state':self.nav_state(identity,'message_state',isolated_snapshot=args.get('isolated_snapshot',False)) if args.get('metadata_only',False) else [],
                        'elapsed_ms':round((time.monotonic()-started)*1000),'send_invoked':False}
                except AXRError as error:
                    code=str(error)
                    if not __import__('re').fullmatch('[a-z][a-z0-9_]{0,99}',code):code='wechat_target_check_failed'
                    return {'navigation_verified':False,'error':code,'elapsed_ms':round((time.monotonic()-started)*1000),'send_invoked':False}
            if method=='manual_draft':
                job=self.jobs.get(args['job_id'])
                if not job or job['state']!='Draft' or job['expires']<=time.time():raise AXRError('wechat_manual_draft_expired')
                return {**job,'job_id':job['id'],'submission':'human','display_name':self.catalog[job['conversation_id']]['display_name']}
            raise AXRError('wechat_owner_operation_not_registered')
        if peer.role!='client' or peer.principal!=PRINCIPAL:raise AXRError('wechat_managed_frontend_required')
        self.context.generation=self.generation
        method=p.get('method');args=p.get('arguments',{})
        from .wechat_frontend import validate_arguments
        validate_arguments(method,args)
        if method=='wechat_status':
            value=self.status();scope=value.get('scope')
            if scope:
                value['scope']={k:scope[k] for k in ('expires','max_replies','automatic','disclose','attribution','overwrite_drafts','self_agent','send_policy','idle_seconds') if k in scope}
                value['scope'].update(target_count=len(scope['targets']),reply_target_count=len(scope['reply_targets']))
            return value
        if method=='wechat_job_status':
            job=self.jobs.get(args['job_id'])
            if not job:raise AXRError('wechat_job_not_owned')
            return {k:v for k,v in job.items() if k not in ('text','prompt')}
        self.check()
        if method=='wechat_conversations':return {'conversations':[self.catalog[i] for i in self.scope['targets'] if args.get('query','').casefold() in (self.catalog[i]['display_name']+' '+i).casefold()],'complete_history':False}
        if method=='wechat_read_messages':
            if not self.scope['disclose']:raise AXRError('wechat_model_disclosure_not_authorized')
            identity=args['conversation_id'];page=self.read(identity,since=args.get('since',0),cursor=args.get('cursor'),limit=args.get('limit',6))
            from axr_integration.content_safety import mask_credentials
            page={**page,'messages':[{**r,'text':mask_credentials(r['text'])[0]} for r in page['messages']]}
            action=self.action(identity,'disclosure.send',{'page_digest':digest(page)},destination='model:codex-mcp',
                sources=(Provenance(self.resources[identity],digest(page),'personal'),))
            proof=self.prepare(action);self.kernel.claim_commit(self.peer,proof)
            self.kernel.observe(self.peer,proof,verified=True,evidence_digest=digest(page))
            return page
        if method=='wechat_send_message':return self.queue(args['conversation_id'],args['text'],args['request_id'])
        if method=='wechat_prepare_reply':return self.queue(args['conversation_id'],args['text'],uuid.uuid4().hex,manual=True)
        raise AXRError('wechat_operation_not_registered')
    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.context.generation=self.generation
                self.check()
                for key,job in list(self.jobs.items()):
                    if job['state'] not in ('Queued','WaitingForIdle'):continue
                    if job['expires']<=time.time():
                        self.save_job(key,{**job,'state':'FailedSafe','error':'wechat_queued_reply_expired','retry':False});continue
                    waiting=self.send_wait_reason()
                    if waiting:
                        if job['state']!='WaitingForIdle' or job.get('wait_reason')!=waiting:
                            self.save_job(key,{**job,'state':'WaitingForIdle','wait_reason':waiting})
                        continue
                    self.check();self.save_job(key,{**job,'state':'Executing'})
                    try:
                        sources=(Provenance(self.resources[job['conversation_id']],job['source'],'personal'),) if job.get('source') else ()
                        result=self.send(job['conversation_id'],job['text'],sources=sources);value={**job,'state':'Observed' if result['database_record_observed'] else 'Unknown','result':result}
                    except Exception as exc:value={**job,'state':'Unknown','error':str(exc) if isinstance(exc,AXRError) else 'wechat_execution_failed','retry':False}
                    self.save_job(key,value);self.reply_count+=1
                for identity in self.scan_targets():
                    self.check();page=self.read(identity,since=self.baseline,cursor=self.cursors.get(identity))
                    # Advance before disclosure/inference. Errors are visible
                    # terminal records; no replay of the same inbound batch.
                    self.cursors[identity]=page['cursor']
                    self.finish_scan(identity,page)
                    rows=[]
                    for row in page['messages']:
                        if self.owner_command(identity,row):continue
                        if identity==self.config['account_id'] and row.get('outgoing') is True and row.get('text','').startswith('/agent '):
                            rows.append({**row,'outgoing':False,'text':row['text'][7:]})
                        else:rows.append(row)
                    self.bursts.add(identity,rows,page['has_more'])
                waiting=[j for j in self.jobs.values() if j['state'] in ('Queued','WaitingForIdle')]
                slots=max(0,self.scope['max_replies']-self.reply_count-len(waiting)) if self.scope['max_replies'] else None
                for identity,context,incoming in self.bursts.ready(limit=slots,blocked={j['conversation_id'] for j in waiting}):
                    self.check()
                    key='inbound-'+digest([identity,[r['reference'] for r in incoming]])
                    if key in self.jobs:continue
                    job={'id':key,'conversation_id':identity,'state':'Executing','created':time.time(),
                        'expires':time.time()+900,'operation':'reply.prepare','batch_count':len(incoming),
                        'context_count':len(context)-len(incoming),'retry':False,'delivery_confirmed':False}
                    self.save_job(key,job)
                    try:
                        text=self.infer(identity,{'messages':context})
                        if text:
                            value={**job,'text':text,'state':'Draft'}
                            if self.scope['automatic']:
                                value.update(state='Queued',operation='messages.send',source=digest(context))
                            self.save_job(key,value)
                            self.worker_event.set()
                    except Exception as exc:self.save_job(key,{**job,'state':'Unknown','error':str(exc) if isinstance(exc,AXRError) else 'wechat_source_failed'})
                if self.bursts.pending:self.poll_delay=1
            except AXRError as exc:
                if self.scope and str(exc) in ('wechat_scope_stopped_or_expired','wechat_reply_budget_exhausted'):self.stop()
                elif self.scope and str(exc)=='wechat_burst_capacity':
                    self.last_error={'code':'wechat_burst_capacity'}
                    self.stop()
                    try:self.state.set('worker-error',self.last_error)
                    except Exception:pass
                elif self.scope and (str(exc).startswith('wcdb_') or str(exc)=='wechat_native_database_failed'):
                    self.last_error={'code':str(exc)}
                    self.stop()
                    try:self.state.set('worker-error',self.last_error)
                    except Exception:pass
            except Exception as exc:
                # Bounded exception class only; never persist a source body,
                # arbitrary message, traceback, path or credential.
                self.last_error={'code':'wechat_dispatcher_stopped','category':type(exc).__name__[:48]}
                # Infrastructure failure cannot silently preserve an active UI
                # state; revoke before the next dispatch pass.
                self.stop()
                try:self.state.set('worker-error',self.last_error)
                except Exception:pass
            self.worker_event.wait(self.poll_delay);self.worker_event.clear()
