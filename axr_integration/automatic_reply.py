# SPDX-License-Identifier: MIT
"""Ephemeral, OS-owner-authorized MCP reply controller. Never exposed as an issuer tool."""
import sys
import threading
import time
from pathlib import Path
from axr.aet import AXRError, digest
from .owner_codex import approve_session_task
from .chat_executor import execute_plan


def validate_scope(service,targets,ttl,replies,helper):
    if (type(targets) is not list or not 2<=len(targets)<=4096 or len(set(targets))!=len(targets) or
            any(not isinstance(c,str) or c not in service.bindings or c=='filehelper' or
                c.startswith(('gh_','axr:')) or '@' in c for c in targets) or
            type(ttl) is not int or not (ttl==0 or 60<=ttl<=86400) or
            type(replies) is not int or not 0<=replies<=1000000):
        raise AXRError('automatic_reply_scope_invalid')
    if sys.platform!='darwin' or service.config['mode']!='wcdb' or service.destination!='model:codex':
        raise AXRError('automatic_reply_backend_unavailable')
    if not helper or not Path(helper).is_file():raise AXRError('automatic_reply_helper_required')
    if any(service.bindings[c].get('data_class','personal') not in ('personal','workspace-normal') for c in targets):
        raise AXRError('automatic_reply_class_outside_scope')
    return Path(helper).resolve(strict=True)


class AutomaticReply:
    """Created only after broker OS authentication; authority is memory-only.

    Agent outputs remain untrusted. Only new incoming tasks after this session
    started may reach the exact, one-use child AETs. Restart never restores this
    session. Claims survive timeout, stop, worker crash and process restart.
    """
    def __init__(self,service,targets,ttl,replies,helper):
        self.service=service;self.targets=tuple(targets);self.helper=validate_scope(service,targets,ttl,replies,helper)
        self.helper_seal=digest(self.helper.read_bytes().hex())
        self.started=time.time();self.expires=self.started+ttl if ttl else None;self.started_monotonic=time.monotonic();self.deadline=self.started_monotonic+ttl if ttl else None
        self.version=service.guard.version;self.stopped=threading.Event();self.limit=replies or None
        self.approved=set();self.approved_count=0;self.used=0;self.last_result=None;self.access={};self.poll_queue=[];self.poll_stamp=None;self.all_users=False;self.last_catalog_refresh=time.monotonic()
        self.seal=digest(service.store.config());self.stop_lock=threading.Lock();self.revoked=False;self.timer=None
        self.policy={**service.config,'conversations':[service.bindings[c] for c in targets]}
        self.listener={'listen':True,'wake_agent':True,'auto_execute':False,'start_from_now':True,
                       'all_incoming':True,'aggregate_seconds':2,'poll_seconds':2,'event_ttl':300,'workflow':'manual'}
        service.journal.db.execute('''CREATE TABLE IF NOT EXISTS automatic_reply_claims(
            task TEXT,principal TEXT,draft_seal TEXT,job TEXT,result BLOB,PRIMARY KEY(task,principal))''')
        from .assistant_settings import load
        self.preferences=load(service.store) if hasattr(service.store,'directory') and (service.store.directory/'assistant-preferences.sealed').exists() else {}
        for cid in targets:self.ensure_access(cid)

    def ensure_access(self,cid):
        self.check()
        if cid not in self.targets:raise AXRError('automatic_reply_target_not_authorized')
        now=time.time()
        if self.access.get(cid,0)>now:return
        s=self.service
        s.guard._issue_owner(principal=s.principal,resource=s.resource(cid),
            operations=['messages.read','messages.search','reply.prepare'],purpose=s.purpose,
            expires_at=min(self.expires or now+300,now+300),max_uses=400,
            classes=[s.bindings[cid].get('data_class','personal')])
        self.access[cid]=now+120

    def poll_targets(self):
        self.check()
        if self.all_users and time.monotonic()-self.last_catalog_refresh>=60:
            from .authorization_requests import catalog,add_bindings
            bindings=catalog(self.service);add_bindings(self.service,bindings)
            self.targets=tuple(dict.fromkeys([*self.targets,*(b['conversation_id'] for b in bindings)]))
            self.policy={**self.policy,'conversations':[self.service.bindings[c] for c in self.targets]}
            self.last_catalog_refresh=time.monotonic()
        paths=[Path(shard['path']) for shard in self.service.config.get('database',{}).get('shards',[])]
        stamp=[]
        for path in paths:
            for candidate in (path,Path(str(path)+'-wal')):
                try:stat=candidate.stat();stamp.append((stat.st_size,stat.st_mtime_ns))
                except FileNotFoundError:stamp.append(None)
        # Synthetic adapters without files keep the normal bounded polling path.
        if not paths or not any(value is not None for value in stamp):return self.targets
        if stamp!=self.poll_stamp:
            self.poll_stamp=stamp
            self.poll_queue=list(dict.fromkeys([*self.poll_queue,*self.targets]))
        ready=self.poll_queue[:32];del self.poll_queue[:32]
        waiting=[cid for cid in self.targets if self.service.resource(cid).key in self.service.admission.pending]
        return list(dict.fromkeys([*ready,*waiting]))

    def defer(self,cid,batch):
        # Only references/times are retained while the chosen Codex turn is busy.
        import uuid
        s=self.service;self.check()
        s.journal.db.execute('CREATE TABLE IF NOT EXISTS automatic_pending(id TEXT PRIMARY KEY,principal TEXT,expires REAL,version INTEGER,payload BLOB)')
        count=s.journal.db.execute('SELECT count(*) FROM automatic_pending WHERE principal=?',(s.principal,)).fetchone()[0]
        if count>=1000:raise AXRError('automatic_pending_capacity')
        for start in range(0,len(batch),6):
            messages=batch[start:start+6];key=str(uuid.uuid4())
            data={'cid':cid,'refs':[m['reference'] for m in messages],
                  'since':max(0,int(min(m['created'] for m in messages))),
                  'until':int(max(m['created'] for m in messages))+1}
            s.journal.db.execute('INSERT INTO automatic_pending VALUES(?,?,?,?,?)',
                (key,s.principal,time.time()+86400,self.version,s.store.vault.seal(data,key+':pending')))

    def has_pending(self):
        s=self.service
        s.journal.db.execute('CREATE TABLE IF NOT EXISTS automatic_pending(id TEXT PRIMARY KEY,principal TEXT,expires REAL,version INTEGER,payload BLOB)')
        s.journal.db.execute('DELETE FROM automatic_pending WHERE expires<=? OR version!=?',(time.time(),self.version))
        return bool(s.journal.db.execute('SELECT 1 FROM automatic_pending WHERE principal=? LIMIT 1',(s.principal,)).fetchone())

    def materialize(self):
        s=self.service
        if not self.has_pending():return
        self.check()
        if len(s.inbox.list())>=40:return
        rows=s.journal.db.execute('SELECT id,payload FROM automatic_pending WHERE principal=? ORDER BY rowid LIMIT 4',(s.principal,)).fetchall()
        for row in rows:
            data=s.store.vault.open(row['payload'],row['id']+':pending');self.ensure_access(data['cid'])
            action=s._read_action(data['cid'],{'query':'','sender':None,'since':data['since'],'until':data['until'],
                'after':None,'limit':100,'pending_references':data['refs']})
            job=s.runtime.propose(action);result=s.execute(job['id'])
            if result['state']!='Completed':raise AXRError('automatic_pending_refresh_failed')
            handle=result['result']['context_id'];proposal=s.disclose(data['cid'],handle)
            s.inbox.create(s.resource(data['cid']),handle,proposal['id'])
            s.journal.db.execute('DELETE FROM automatic_pending WHERE id=?',(row['id'],))

    def stop(self):
        self.stopped.set()
        with self.stop_lock:
            if self.timer:self.timer.cancel()
            if not self.revoked:
                self.service.guard.revoke_owner('automatic-reply-stopped');self.revoked=True

    def check(self):
        s=self.service
        if (self.stopped.is_set() or time.time()<self.started-1 or (self.expires is not None and time.time()>=self.expires) or
                time.monotonic()<self.started_monotonic or (self.deadline is not None and time.monotonic()>=self.deadline) or
                s.guard.version!=self.version or digest(s.store.config())!=self.seal or
                digest(self.helper.read_bytes().hex())!=self.helper_seal):
            self.stopped.set();raise AXRError('automatic_reply_session_stopped_or_expired')

    def status(self):
        try:self.check();active=True
        except (AXRError,OSError):active=False
        return {'active':active,'targets':list(self.targets),'expires':self.expires,
                'remaining':max(0,self.limit-self.used) if self.limit is not None else None,'max_replies':self.limit,
                'model_destination':'model:codex','foreground_required':True,
                'retry_unknown':False,'last_result':self.last_result}

    def approve_context(self,task):
        self.check()
        if task['id'] in self.approved:return
        if self.limit is not None and self.approved_count>=self.limit:raise AXRError('automatic_reply_batch_budget_exhausted')
        if (task['conversation_id'] not in self.targets or task.get('origin')!='incoming_reply' or
                task['expires']-300<self.started):raise AXRError('automatic_reply_requires_new_incoming_task')
        s=self.service
        action=s.journal.action(s.journal.get(task['disclosure_job'],s.principal))
        data=s.journal.context(task['context_id'],s.principal,action.resource,s.guard.version)
        if not data.get('messages') or any(m.get('outgoing') is not False or m.get('created',0)<self.started for m in data['messages']):
            raise AXRError('automatic_reply_incoming_context_required')
        if approve_session_task(s.store,task,self.policy):
            self.approved.add(task['id']);self.approved_count+=1

    def submit(self,task_id):
        s=self.service
        # Durable replay lookup precedes session/task TTL checks; never resume an
        # incomplete preparation or an uncertain send, even under a new session.
        row=s.journal.db.execute('SELECT * FROM automatic_reply_claims WHERE task=? AND principal=?',(task_id,s.principal)).fetchone()
        if row:
            if row['result']:return s.store.vault.open(row['result'],task_id+':automatic-reply')
            return {'send_job':s.journal.receipt(row['job'],s.principal) if row['job'] else None,
                    'state':'Unknown','retry':False,'delivery_confirmed':False,'database_record_observed':False}
        self.check()
        if self.limit is not None and self.used>=self.limit:raise AXRError('automatic_reply_send_budget_exhausted')
        task=s.inbox.get(task_id)
        if task_id not in self.approved or task['conversation_id'] not in self.targets:
            raise AXRError('automatic_reply_task_outside_session')
        row=s.journal.get(task['draft_job'],s.principal);draft=s.journal.action(row)
        if row['state']!='Completed' or draft.operation!='reply.prepare' or draft.resource!=s.resource(task['conversation_id']):
            raise AXRError('completed_matching_reply_draft_required')
        s.guard.revalidate(draft,row['grant_id'],row['policy_version'])
        sources=tuple({(p.resource.key,p.reference):p for p in (*draft.sources,*s._sources(draft.resource))}.values())
        allowed={s.resource(c).key for c in self.targets}
        if any(p.resource.key not in allowed or p.data_class not in ('personal','workspace-normal') for p in sources):
            raise AXRError('automatic_reply_sources_outside_scope')
        self.used+=1
        s.journal.db.execute('INSERT INTO automatic_reply_claims VALUES(?,?,?,?,?)',(task_id,s.principal,draft.seal,None,None))
        def linked(jid):
            self.check()
            s.journal.db.execute('UPDATE automatic_reply_claims SET job=? WHERE task=? AND principal=?',(jid,task_id,s.principal))
            s.journal.db.execute('INSERT INTO reply_submissions VALUES(?,?,?)',(task_id,s.principal,jid))
        try:
            # Retain the owner's original qualified switching pair when the
            # scope expands; an arbitrary historical contact may not be searchable.
            parking=next((b['conversation_id'] for b in s.config['conversations']
                if b['conversation_id'] in self.targets and b['conversation_id']!=task['conversation_id']),
                next(c for c in self.targets if c!=task['conversation_id']))
            plan={'version':1,'messages':[{'conversation_id':task['conversation_id'],
                'parking_conversation_id':parking, 'text':draft.payload['text']}]}
            results=execute_plan(s.store,s.store.directory,self.helper,plan,principal=s.principal,
                action_purpose=s.purpose,sources=sources,ttl=max(1,min(180,(self.expires or time.time()+180)-time.time())),binding_catalog=s.bindings,
                attribution=self.preferences.get("attribution",True),attempt_id=task_id,
                session_check=self.check,journal=s.journal,on_send_job=linked,revoke_on_exit=False)
            result=results[0]
            # Observation is separate evidence. Input still remains Unknown.
            result.update(database_record_observed=result['exact_database_records']==1,
                          automatic_send=result.get('native',{}).get('send_invoked') is True,
                          submission='owner_session',state='Observed' if result['exact_database_records']==1 else 'Unknown')
            result.pop('native',None);result.pop('role',None)
        except Exception as exc:
            error=str(exc) if isinstance(exc,AXRError) and str(exc).replace("_", "").isalnum() and len(str(exc))<=100 else "automatic_reply_failed_safe"
            row=s.journal.db.execute('SELECT job FROM automatic_reply_claims WHERE task=? AND principal=?',(task_id,s.principal)).fetchone()
            result={'error':error,'state':'Unknown' if row['job'] else 'Stopped','send_job':s.journal.receipt(row['job'],s.principal) if row['job'] else None,
                    'automatic_send':False,'database_record_observed':False,'delivery_confirmed':False,'retry':False,'submission':'owner_session'}
        s.journal.db.execute('UPDATE automatic_reply_claims SET result=? WHERE task=? AND principal=?',
                            (s.store.vault.seal(result,task_id+':automatic-reply'),task_id,s.principal))
        self.last_result={k:result[k] for k in ('state','database_record_observed','delivery_confirmed','retry')}
        if result['state']!='Observed' or (self.limit is not None and self.used>=self.limit):self.stop()
        self.approved.discard(task_id)
        s.journal.db.execute('DELETE FROM reply_tasks WHERE id=? AND principal=?',(task_id,s.principal))
        s.journal.db.execute('DELETE FROM contexts WHERE id=? AND principal=?',(task['context_id'],s.principal))
        return result
