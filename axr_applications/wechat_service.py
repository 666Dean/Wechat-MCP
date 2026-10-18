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

PRINCIPAL='wechat:service'
BOUNDARY='wechat-managed-v2'
OPERATIONS=('status.read','messages.read','messages.search','reply.prepare','disclosure.send',
            'application.navigate','application.draft','messages.send')

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
        self.jobs=self.state.get('jobs',{})
        # Never resume or retry work interrupted by a crash/restart.
        for job in self.jobs.values():
            if job['state'] in ('Queued','Executing','Verifying'):
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
                if job['state']=='Queued':self.save_job(key,{**job,'state':'FailedSafe','retry':False})
        self.worker_event.set()
        return {'stopped':True,'revoked':True,'retry':False}
    def review(self,peer,arguments):
        self.kernel._owner(peer)
        if self.scope:raise AXRError('automatic_reply_already_active')
        readiness=self.readiness()
        if not readiness['database']:raise AXRError('wechat_full_disk_access_required')
        if arguments.get('automatic',False) and not readiness['accessibility']:raise AXRError('wechat_accessibility_required')
        if type(arguments) is not dict or set(arguments)-{'targets','reply_targets','seconds','max_replies','automatic','disclose','style','attribution','overwrite_drafts'}:raise AXRError('wechat_owner_scope_invalid')
        targets=arguments.get('targets',[])
        if targets=='all':targets=list(self.resources)
        if type(targets) is not list or not targets or len(set(targets))!=len(targets) or set(targets)-set(self.resources):raise AXRError('wechat_owner_scope_invalid')
        seconds=arguments.get('seconds',3600);count=arguments.get('max_replies',4)
        if type(seconds) is not int or not 0<=seconds<=86400 or type(count) is not int or not 0<=count<=100000:raise AXRError('wechat_owner_scope_invalid')
        for key in ('automatic','disclose','attribution','overwrite_drafts'):
            if key in arguments and type(arguments[key]) is not bool:raise AXRError('wechat_owner_scope_invalid')
        settings=self.state.get('assistant',{'persona':'','style':'简洁、自然、直接；不编造事实。','attribution':False,'thread_id':'','thread_title':''})
        style=arguments.get('style',settings.get('persona','')+'\n'+settings['style'])
        if not isinstance(style,str) or len(style.encode())>12000:raise AXRError('wechat_owner_scope_invalid')
        if arguments.get('automatic',False) and not arguments.get('disclose',True):raise AXRError('wechat_model_disclosure_required')
        reply_targets=arguments.get('reply_targets',targets)
        if type(reply_targets) is not list or not reply_targets or set(reply_targets)-set(targets):raise AXRError('wechat_owner_scope_invalid')
        # Metadata/account checks run BEFORE the hardware-authentication UI.
        # A missing window must not consume another owner approval.
        if arguments.get('automatic',False):self.inspect_binding()
        scope={'targets':targets,'reply_targets':reply_targets,'expires':time.time()+seconds if seconds else 0,'max_replies':count,
               'automatic':arguments.get('automatic',False),'disclose':arguments.get('disclose',True),
               'style':style,'attribution':arguments.get('attribution',settings['attribution']),
               'overwrite_drafts':arguments.get('overwrite_drafts',False)}
        challenge={'version':2,'kind':'wechat-standing-scope','root_id':self.kernel.root_id,'epoch':self.kernel.epoch,
                   'owner':peer.principal,'peer':peer.witness,'nonce':secrets.token_hex(32),'expires':time.time()+120,
                   'scope':scope,'policy_version':self.kernel.security.guard.version,
               'operations':list(OPERATIONS),'model_destinations':[CodexSourceProvider.destination,'model:codex-mcp'],
                   'send_destinations':['wechat:'+self.resources[i].key for i in reply_targets],
                   'execution':'foreground original-app keyboard; once; Unknown never retries',
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
            self.owner=peer.principal;self.scope=challenge['scope'];self.generation+=1
            self.baseline=int(time.time())+1;self.cursors={};self.reply_count=0
            try:self.derive_contract()
            except BaseException:self.scope=None;self.capability=None;raise
            self.state.set('last-owner-consent',{'challenge':challenge,'signature':signature,'authority_restored':False})
        self.worker_event.set()
        return self.status()
    def derive_contract(self,identity=None):
        # A standing owner consent can be unlimited; every derived task remains
        # finite. Only this trusted host derives it, from the signed exact scope.
        now=time.time();scope=self.scope;identity=identity or scope['reply_targets'][0]
        if identity not in scope['targets']:raise AXRError('wechat_target_not_authorized')
        keys=[self.resources[identity].key]
        contract=TaskContract(uuid.uuid4().hex,self.owner,PRINCIPAL,'wechat',digest(scope),'incoming','external-message',
            OPERATIONS,tuple(keys),tuple(keys),tuple(['local',CodexSourceProvider.destination,'model:codex-mcp',*['wechat:'+k for k in keys]]),
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
    def inspect_binding(self):
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
        return binding
    def navigate(self,identity):
        started=time.time();binding=self.binding();text=self.catalog[identity]['display_name']
        # One exact navigation transaction. The native helper validates its
        # five-second permit locally between keys, avoiding per-key RPC stalls.
        for phase in ('complete',):
            action=self.action(identity,'application.navigate',{'mode':'navigate','text':text,'visual_binding':binding,
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
        with self.execution_lock:
            if any(j['state']=='Unknown' and j['conversation_id']==identity and j.get('text')==text for j in self.jobs.values()):raise AXRError('wechat_uncertain_text_never_retry')
            self.check();parking=next((i for i in self.scope['targets'] if i!=identity),None)
            if identity!=self.config['account_id'] and self.config['account_id'] in self.scope['targets']:parking=self.config['account_id']
            elif identity==self.config['account_id']:parking=next((i for i in self.scope['reply_targets'] if i!=identity),parking)
            if parking is None:raise AXRError('wechat_parking_conversation_required')
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
            if staged['receipt']['state']!='Completed' or staged.get('native',{}).get('draft_match') is not True:raise AXRError('wechat_exact_input_required')
            self.navigate(parking)
            cache=self.nav_state(identity,'unique_draft',text=text);observed=time.time();observed_mono=time.monotonic()
            binding,started,search=self.navigate(identity)
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
            return {**result,'exact_database_records':len(matches),'database_record_observed':len(matches)==1,
                'retry':False,'delivery_confirmed':False}
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
        records=actor_records(page)
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
        return {'axr':True,'operational':True,'authority':'independent-native-v2','owner_authorized':active,
            'automatic_reply':bool(active and self.scope['automatic']),'scope':self.scope if active else None,
            'permissions':permissions,'send_available':active and permissions['database'] and permissions['accessibility'],
            'listener':{'listen':active,'wake_agent':active,'auto_execute':active and self.scope['automatic']},
            'platform':{'mode':'wcdb-native','send_available':active and permissions['database'] and permissions['accessibility']},'audit_valid':self.kernel.store.journal.verify_audit(),
            'policy_version':self.kernel.store.guard.version,'reply_count':self.reply_count,'retry_unknown':False,
            'delivery_confirmed':False,'body_disclosed':False}
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
            if method=='assistant_settings':return self.state.get('assistant',{'thread_id':'','thread_title':'','persona':'','style':'简洁、自然、直接；不编造事实。','attribution':False})
            if method=='save_assistant_settings':
                if self.scope:raise AXRError('stop_automatic_before_settings_change')
                if set(args)-{'thread_id','thread_title','persona','style','attribution'} or any(not isinstance(v,str) or len(v.encode())>12000 for k,v in args.items() if k!='attribution') or type(args.get('attribution',False)) is not bool:raise AXRError('wechat_assistant_settings_invalid')
                value={**self.state.get('assistant',{'thread_id':'','thread_title':'','persona':'','style':'简洁、自然、直接；不编造事实。','attribution':False}),**args}
                self.state.set('assistant',value);return value
            if method=='snapshot':
                return {'status':self.status(),'conversations':list(self.catalog.values()),'jobs':[
                    {k:v for k,v in j.items() if k!='text'} for j in self.jobs.values()],
                    'drafts':[{'job_id':k,'display_name':self.catalog[j['conversation_id']]['display_name'],
                        'expires':j['expires']} for k,j in self.jobs.items() if j['state']=='Draft' and j['expires']>time.time()],
                    'grants':[],'summaries':[]}
            if method=='check_target':
                self.check();identity=args.get('conversation_id')
                if (set(args)-{'conversation_id','metadata_only'} or 'conversation_id' not in args
                    or type(args.get('metadata_only',False)) is not bool
                    or identity not in self.scope['reply_targets']):raise AXRError('wechat_owner_scope_invalid')
                started=time.monotonic()
                try:
                    if not args.get('metadata_only',False):self.navigate(identity)
                    rows=self.nav_state(identity,'draft')
                    return {'navigation_verified':not args.get('metadata_only',False),'draft_present':len(rows)!=1 or rows[0]['draft']!='',
                        'cached_draft_metadata':saved_draft_metadata(rows[0]) if len(rows)==1 else {},
                        'session_schema':self.nav_state(identity,'session_schema') if args.get('metadata_only',False) else [],
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
        if method=='wechat_status':return self.status()
        if method=='wechat_job_status':
            job=self.jobs.get(args['job_id'])
            if not job:raise AXRError('wechat_job_not_owned')
            return {k:v for k,v in job.items() if k!='text'}
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
                    if job['state']!='Queued':continue
                    self.check();self.save_job(key,{**job,'state':'Executing'})
                    try:result=self.send(job['conversation_id'],job['text']);value={**job,'state':'Observed' if result['database_record_observed'] else 'Unknown','result':result}
                    except Exception as exc:value={**job,'state':'Unknown','error':str(exc) if isinstance(exc,AXRError) else 'wechat_execution_failed','retry':False}
                    self.save_job(key,value);self.reply_count+=1
                targets=list(self.scope['reply_targets']);scan=(targets+targets)[self.poll_position:self.poll_position+min(8,len(targets))]
                self.poll_position=(self.poll_position+min(8,len(targets)))%len(targets)
                for identity in scan:
                    self.check();page=self.read(identity,since=self.baseline,cursor=self.cursors.get(identity))
                    # Advance before disclosure/inference. Errors are visible
                    # terminal records; no replay of the same inbound batch.
                    self.cursors[identity]=page['cursor']
                    incoming=[r for r in page['messages'] if r['outgoing'] is False]
                    if not incoming:continue
                    key='inbound-'+digest([identity,[r['reference'] for r in incoming]])
                    if key in self.jobs:continue
                    job={'id':key,'conversation_id':identity,'state':'Executing','created':time.time(),
                        'expires':time.time()+900,'operation':'reply.prepare','retry':False,'delivery_confirmed':False}
                    self.save_job(key,job)
                    try:
                        text=self.infer(identity,{**page,'messages':incoming})
                        if text:
                            value={**job,'text':text,'state':'Draft'}
                            if self.scope['automatic']:
                                result=self.send(identity,text,sources=(Provenance(self.resources[identity],digest(incoming),'personal'),));value.update(state='Observed' if result['database_record_observed'] else 'Unknown',result=result);self.reply_count+=1
                            self.save_job(key,value)
                    except Exception as exc:self.save_job(key,{**job,'state':'Unknown','error':str(exc) if isinstance(exc,AXRError) else 'wechat_source_failed'})
            except AXRError as exc:
                if self.scope and str(exc) in ('wechat_scope_stopped_or_expired','wechat_reply_budget_exhausted'):self.stop()
            except Exception:
                # Infrastructure failure cannot silently preserve an active UI
                # state; revoke before the next dispatch pass.
                self.stop()
            self.worker_event.wait(2);self.worker_event.clear()
