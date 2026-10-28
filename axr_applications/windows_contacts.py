# SPDX-License-Identifier: MIT
"""Owner catalog and signed scope replacement. Requests alone grant nothing."""
from dataclasses import asdict
import copy,math,secrets,threading,time
from functools import wraps
from axr import _axr_native as native
from axr.aet import AXRError,Resource,canonical,digest
from axr.ipc import process_identity
from .wechat_database import NativeDatabase
from .wechat_targets import private_recipient

def make_database(service,application):
    from . import _wechat_credentials
    consumer=_wechat_credentials.WeChatConsumer(service.peer.witness,canonical(application).decode())
    return NativeDatabase(consumer,application['account_id'])

def locked(function):
    @wraps(function)
    def call(self,*args,**kwargs):
        with self.lock:return function(self,*args,**kwargs)
    return call

class ContactAuthorization:
    def __init__(self,service):
        self.service=service;self.reviews={};self.clients={};self.transition=None;self.lock=threading.RLock()
        self.requests=service.state.get('authorization-requests',{})
        if type(self.requests) is not dict or len(self.requests)>20:raise AXRError('wechat_authorization_state_invalid')
        changed=False
        for row in self.requests.values():
            if row['state']=='AwaitingOwner':row['state']='Unknown';changed=True
        if changed:self.save()
        rows=service.state.get('contact-catalog',None)
        if rows is not None:self.install(rows,persist=False)
    def save(self):self.service.state.set('authorization-requests',self.requests)
    @locked
    def install(self,rows,*,persist=True):
        s=self.service
        if type(rows) is not list or not 1<=len(rows)<=4096:raise AXRError('wechat_contact_catalog_invalid')
        checked={}
        for row in rows:
            if (type(row) is not dict or set(row)!={'conversation_id','display_name','data_class'} or
                not private_recipient(row['conversation_id']) or not isinstance(row['display_name'],str) or
                not 0<len(row['conversation_id'].encode())<=256 or not 0<len(row['display_name'].encode())<=4000 or
                row['data_class']!='personal' or row['conversation_id'] in checked):raise AXRError('wechat_contact_catalog_invalid')
            checked[row['conversation_id']]=dict(row)
        if s.config['account_id'] not in checked:raise AXRError('wechat_contact_catalog_invalid')
        resources={i:Resource('wechat',s.config['account_id'],i) for i in checked}
        application={**s.config,'conversations':list(checked.values()),'resources':[asdict(r) for r in resources.values()]}
        database=make_database(s,application)
        # Metadata never adds a target to an active signed scope. Removal
        # invalidates that scope before replacing its underlying directory.
        with s.execution_lock:
            if s.scope and set(s.scope['targets'])-set(checked):s.stop()
            if persist:s.state.set('contact-catalog',list(checked.values()))
            s.config=application;s.catalog=checked;s.resources=resources;s.database=database;s.executor.database=database
        return {'conversations':[{**row,'is_self':i==s.config['account_id']} for i,row in checked.items()],
            'catalog_digest':digest(list(checked.values())),'authority_granted':False}
    @locked
    def refresh(self,peer):
        s=self.service;s.kernel._owner(peer)
        rows=s.database.catalog(lambda:s.kernel._owner(peer))
        s.kernel._owner(peer)
        return self.install(rows)
    def client_alive(self,key):
        peer=self.clients.get(key)
        if peer is None:return False
        try:return self.service.registry.accept(process_identity(peer.pid))==peer
        except (AXRError,OSError,RuntimeError,AttributeError):return False
    @locked
    def request(self,peer,target,reason):
        if (type(target) is not str or not target.strip() or len(target.encode())>512 or type(reason) is not str or
            not reason.strip() or len(reason.encode())>2000):raise AXRError('authorization_request_invalid')
        now=time.time();self.requests={k:v for k,v in self.requests.items() if v['expires']>now}
        if len(self.requests)>=20:
            terminal=sorted((row['created'],key) for key,row in self.requests.items() if row['state']!='AwaitingOwner')
            for _,key in terminal:
                self.requests.pop(key)
                if len(self.requests)<20:break
        self.clients={k:v for k,v in self.clients.items() if k in self.requests}
        if len(self.requests)>=20:raise AXRError('authorization_request_capacity')
        from axr_integration.content_safety import mask_credentials
        key=secrets.token_hex(32)
        self.requests[key]={'id':key,'target':target,'reason':mask_credentials(reason)[0],'client_witness':peer.witness,
            'state':'AwaitingOwner','created':now,'expires':now+600}
        self.clients[key]=peer;self.save()
        return {'request_id':key,'state':'AwaitingOwner','authority_granted':False,
            'next_step':'Wait for a separate local owner review and signature; a request is not authorization.'}
    def row(self,key):
        row=self.requests.get(key)
        if not row or row['expires']<=time.time():raise AXRError('authorization_request_missing_or_expired')
        return row
    @locked
    def status(self,peer,key):
        row=self.row(key)
        if row['client_witness']!=peer.witness:raise AXRError('authorization_request_not_owned')
        s=self.service;active=False
        with s.scope_lock:
            try:s.check();active=True
            except AXRError:pass
            granted=(active and row['state']=='Approved' and row.get('approved_generation')==s.generation and
                row.get('conversation_id') in s.scope['targets'])
            operations=['messages.read','reply.prepare','disclosure.send'] if granted else []
            if granted and row['conversation_id'] in s.scope['reply_targets']:operations.append('messages.send')
        return {'request_id':key,'state':row['state'],'authority_granted':bool(granted),'operations':operations}
    @locked
    def pending(self):
        return [{k:v for k,v in row.items() if k not in ('client_witness','approved_generation')}
            for row in self.requests.values() if row['state']=='AwaitingOwner' and row['expires']>time.time()]
    @locked
    def deny(self,peer,key):
        self.service.kernel._owner(peer);row=self.row(key)
        if row['state']!='AwaitingOwner':raise AXRError('authorization_request_not_pending')
        row['state']='Rejected';self.save()
        return {'request_id':key,'state':'Rejected','authority_granted':False}
    def executing(self):
        return sum(j['state']=='Executing' and j.get('operation')=='messages.send' for j in tuple(self.service.jobs.values()))
    @locked
    def review(self,peer,key):
        s=self.service;s.kernel._owner(peer);row=self.row(key)
        if row['state']!='AwaitingOwner' or not self.client_alive(key):raise AXRError('authorization_request_not_pending')
        if self.transition is not None:raise AXRError('wechat_authorization_transition_busy')
        self.refresh(peer)
        matches=[r for r in s.catalog.values() if row['target'] in (r['conversation_id'],r['display_name'])]
        exact=[r for r in matches if r['conversation_id']==row['target']]
        if exact:matches=exact
        if len(matches)!=1:raise AXRError('wechat_authorization_unique_private_target_required')
        target=matches[0]['conversation_id']
        with s.scope_lock:
            old=copy.deepcopy(s.scope);reserved=self.executing();generation=s.generation;used=s.reply_count
            old_clock=s.scope_clock
        deadline=(old_clock[1]+old_clock[2]) if old and old_clock and old_clock[2] is not None else None
        if old:
            s.check();seconds=math.floor(old['expires']-time.time()) if old['expires'] else 0
            if deadline is not None:seconds=min(seconds,math.floor(deadline-time.monotonic()))
            count=old['max_replies']-used-reserved if old['max_replies'] else 0
            if (old['expires'] and seconds<=0) or (old['max_replies'] and count<=0):raise AXRError('wechat_scope_stopped_or_expired')
            args={k:old[k] for k in ('automatic','style','attribution','overwrite_drafts','self_agent','send_policy','idle_seconds')}
            args.update(targets=list(dict.fromkeys([*old['targets'],target])),reply_targets=list(old['reply_targets']),
                seconds=seconds,max_replies=count,disclose=True)
            profiles=s.config.get('reply_navigation',{}).get('profiles',{})
            if old['automatic'] and target in profiles and target not in args['reply_targets']:args['reply_targets'].append(target)
        else:args={'targets':[target],'reply_targets':[],'seconds':600,'max_replies':4,'automatic':False,'disclose':True}
        reviewed=s._review(peer,args,replacing=True);challenge=reviewed['challenge']
        challenge['expires']=min(challenge['expires'],row['expires'],challenge['scope']['expires'] or challenge['expires'])
        with s.scope_lock:
            if s.generation!=generation or s.reply_count!=used or digest(s.scope)!=digest(old) or self.executing()>reserved:
                s.reviews.pop(challenge['nonce'],None);raise AXRError('wechat_authorization_review_changed')
        detail={'request_id':key,'target':matches[0],'reason':row['reason'],'replaces_current_scope':old is not None,
            'old_pending_approvals_cancelled':old is not None,'send_added':target in challenge['scope']['reply_targets']}
        challenge.update(kind='wechat-contact-authorization',request_id=key,requester=row['client_witness'],
            authorized_contact=target,review_digest=digest(detail))
        self.reviews={n:r for n,r in self.reviews.items() if r['challenge']['expires']>time.time()}
        self.reviews[challenge['nonce']]={'challenge':copy.deepcopy(challenge),'scope_digest':digest(old),'generation':generation,
            'count':used,'executing':reserved,'catalog_digest':digest(s.catalog),'started':time.monotonic(),
            'wall':time.time(),'deadline':deadline}
        return {**reviewed,'review':detail}
    @locked
    def approve(self,peer,nonce,signature):
        s=self.service;s.kernel._owner(peer);review=self.reviews.pop(nonce,None)
        if not review:raise AXRError('wechat_authorization_review_changed')
        challenge=review['challenge'];key=challenge['request_id'];row=self.row(key)
        with s.scope_lock:
            if (self.transition is not None or row['state']!='AwaitingOwner' or not self.client_alive(key) or
                challenge['peer']!=peer.witness or not review['wall']<=time.time()<challenge['expires'] or
                (review['deadline'] is not None and time.monotonic()>=review['deadline']) or
                not 0<=time.monotonic()-review['started']<=120 or s.generation!=review['generation'] or
                s.reply_count!=review['count'] or self.executing()>review['executing'] or
                digest(s.scope)!=review['scope_digest'] or digest(s.catalog)!=review['catalog_digest'] or
                s.reviews.get(nonce)!=challenge):raise AXRError('wechat_authorization_review_changed')
            try:valid=native.verify_owner_signature(s.kernel.owner_public_key,canonical(challenge),bytes.fromhex(signature))
            except Exception:valid=False
            if not valid:raise AXRError('owner_presence_signature_required')
            self.transition=nonce
        try:
            s.stop() # Revoke old tasks before creating any replacement authority.
            with s.scope_lock:
                if (s.generation!=review['generation']+1 or s.scope is not None or not self.client_alive(key) or
                    time.time()>=challenge['expires'] or s.reply_count!=review['count']):raise AXRError('wechat_authorization_review_changed')
                result=s._activate_scope(peer,nonce,signature)
                if s.generation!=review['generation']+2:raise AXRError('wechat_authorization_review_changed')
                if review['deadline'] is not None:
                    wall,tick,duration=s.scope_clock
                    s.scope_clock=(wall,tick,min(duration,max(0,review['deadline']-tick)))
                row.update(state='Approved',conversation_id=challenge['authorized_contact'],approved_generation=s.generation)
                self.save()
            return {**result,'request_id':key,'authorization_signed':True,'previous_authority_restored':False}
        except BaseException:
            s.stop();s.reviews.pop(nonce,None);raise
        finally:self.transition=None
