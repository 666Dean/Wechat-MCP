# SPDX-License-Identifier: MIT
"""WeChat orchestration. No WeChat service implementation is placed in AXR/."""
import hmac
import json
import threading
import time
from dataclasses import asdict,replace
from pathlib import Path
from axr.aet import AXRError,Action,Resource,Provenance,canonical,digest
from axr.policy import OwnerStore
from axr.host import Lease,Supervisor
from axr.runtime import Runtime
from axr.workspace import Workspace
from axr.admission import Budget,Admission
from .policy import validate_controls
from .content_safety import mask_credentials

class Service:
    def __init__(self,state,*,store=None,adapter=None,leases=None,manual_replies=False):
        if type(manual_replies) is not bool:raise AXRError('manual_reply_control_requires_boolean')
        self.manual_replies=manual_replies
        self.store=store or OwnerStore(state)
        self.guard,self.journal=self.store.guard,self.store.journal
        try:self.config=validate_controls(self.store.config())
        except BaseException:self.store.close();raise
        self.initial_policy_digest=digest(self.config)
        self.principal=self.config["principal"]
        self.purpose=self.config.get("purpose","wechat-assistant")
        self.account=self.config["account_id"]
        self.destination=self.config["agent_destination"]
        if self.destination=="local":raise AXRError("model_disclosure_destination_must_be_explicit")
        self.bindings={b["conversation_id"]:b for b in self.config["conversations"]}
        maximum=4096 if self.config.get('account_review',{}).get('enabled') else 32
        if not self.bindings or len(self.bindings)>maximum:raise AXRError("explicit_conversation_bindings_required")
        # Global per-user lease root independent of journal/config locations.
        lease_root=Path(leases) if leases else Path.home()/".stellaria-axr"/"leases"
        self.lifetime=Lease(lease_root,["journal",str(self.store.directory)])
        try:self.lifetime.__enter__()
        except BaseException:
            self.store.close();raise
        try:
            if not self.journal.verify_audit():raise AXRError("journal_audit_integrity_failed")
            self.journal.recover();self.journal.purge()
            if adapter is not None:self.adapter=adapter
            elif self.config["mode"] in {"wcdb","hybrid"}:
                from adapters.wcdb import DatabaseAdapter
                self.adapter=DatabaseAdapter({**self.config["database"],"account_id":self.account,
                    "conversations":self.config["conversations"]},self.store.secrets)
                if self.config["mode"]=="hybrid":
                    from adapters.ui import UIAdapter
                    from adapters.hybrid import HybridAdapter
                    try:
                        ui=UIAdapter({**self.config["ui"],"account_id":self.account,"conversations":self.config["conversations"]})
                    except BaseException:
                        self.adapter.close();raise
                    self.adapter=HybridAdapter(self.adapter,ui)
            elif self.config["mode"]=="ui":
                from adapters.ui import UIAdapter
                self.adapter=UIAdapter({**self.config["ui"],"account_id":self.account,"conversations":self.config["conversations"]})
            else:raise AXRError("unknown_data_mode")
            handlers={"messages.read":self._read,"messages.search":self._read,
                      "disclosure.send":self._disclose,"reply.prepare":self._prepare,"messages.send":self._send}
            self.navigation=None
            if "navigation" in self.config:
                from adapters.macos.navigation import NavigationAdapter
                self.navigation=NavigationAdapter(self.config["navigation"])
                handlers["application.navigate"]=self.navigation.execute
            if self.config.get("workspace"):
                self.workspace=Workspace(self.config["workspace"],self.store.vault,self.store.directory/"versions")
                handlers["workspace.write"]=self.workspace.write
            self.runtime=Runtime(self.guard,self.journal,lease_root,handlers)
            self.budget=Budget(self.journal);self.admission=Admission(self.guard,self.journal,self.budget)
            self.stop_event=threading.Event();self.listener_thread=None
            self.runner_supervisor=Supervisor(timeout=min(60,self.config.get("runner",{}).get("timeout",30)))
            self.baselines=set();self.cursors={};self.pending_drafts=[]
            self.active_policy_version=self.guard.version
            from .inbox import Inbox
            self.inbox=Inbox(self.journal,self.guard,self.principal)
            self.journal.db.execute('CREATE TABLE IF NOT EXISTS review_read_budget(principal TEXT PRIMARY KEY,pages INTEGER)')
            self.journal.db.execute('CREATE TABLE IF NOT EXISTS review_notes(id TEXT PRIMARY KEY,principal TEXT,resource TEXT,version INTEGER,expires REAL,payload BLOB)')
            self.journal.db.execute('DELETE FROM review_notes WHERE expires<=? OR version!=?',(self.journal.clock(),self.guard.version))
            self.listener_since=int(self.journal.clock())
        except BaseException:
            self.lifetime.__exit__();self.store.close();raise

    def ensure_policy(self):
        if digest(self.store.config())!=self.initial_policy_digest:
            self.stop_event.set()
            raise AXRError("owner_policy_changed_restart_required")

    def resource(self,conversation_id):
        if conversation_id not in self.bindings:raise AXRError("conversation_not_owner_bound")
        return Resource("wechat",self.account,conversation_id)

    def status(self):
        return {"axr":True,"protocol":1,"platform":self.adapter.status(),
            "policy_version":self.guard.version,"listener":{k:self.config.get("listener",{}).get(k,False) for k in ("listen","wake_agent","auto_execute")},
            "metrics":self.journal.metrics(),"audit_valid":self.journal.verify_audit(),
            "approval":"local_owner_os_authentication","unknown_retry":False,
            "reply_submission":"human" if self.manual_replies else "approved_adapter",
            "navigation":{"enabled":self.navigation is not None,
                "actions":list(self.config.get("navigation",{}).get("actions",[])),
                "scope":"application_menu_only","message_send_authority":False},
            "restart_required":digest(self.store.config())!=self.initial_policy_digest}

    def navigate(self,command):
        self.ensure_policy()
        if self.navigation is None:raise AXRError("navigation_disabled_by_owner")
        from adapters.macos.navigation import APPLICATION_SCOPE
        action=Action(self.principal,Resource("wechat",self.account,APPLICATION_SCOPE),
            "application.navigate",self.purpose+":ui-navigation",
            {"command":command,"navigation_binding":self.navigation.binding(command)})
        # Always return the proposal. Approval belongs to the local owner CLI.
        return self.runtime.propose(action)

    def conversations(self,offset=0,limit=100):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise AXRError('invalid_catalog_page')
        self.ensure_policy();items=list(self.bindings.items())[offset:offset+limit]
        if self.config.get('account_review',{}).get('enabled'):
            for cid,_ in items:self.guard.check(self._read_action(cid,{'catalog_metadata':True}))
        return {"conversations":[{"conversation_id":k,"display_name":v["display_name"],
                    **{f:v[f] for f in ('kind','records','text_records') if f in v}} for k,v in items],
                'total':len(self.bindings),'next_offset':offset+limit if offset+limit<len(self.bindings) else None,
                "coverage":"explicit_owner_bindings",
                'account_review':self.config.get('account_review',{}).get('coverage')}

    def _action(self,conversation_id,operation,payload,*,sources=(),destination="local",workflow="manual"):
        self.ensure_policy()
        return Action(self.principal,self.resource(conversation_id),operation,self.purpose,payload,
                      tuple(sources),destination,workflow)

    def _read_action(self,conversation_id,payload,*,workflow="manual"):
        binding=self.bindings[conversation_id]
        if self.config["mode"]=="ui" and binding.get("read_method")=="ocr":
            payload={**payload,"visual_binding":binding["visual_binding"]}
        action=self._action(conversation_id,"messages.search" if payload.get("query") else "messages.read",payload,workflow=workflow)
        data_class=self.bindings[conversation_id].get("data_class","personal")
        return replace(action,sources=(Provenance(action.resource,"query:"+digest(payload),data_class),))

    def read(self,conversation_id,query="",sender=None,since=0,until=2**63-1,cursor=None,limit=20):
        with self.runtime.lock:
            return self._read_context_locked(conversation_id,query,sender,since,until,cursor,limit)

    def _read_context_locked(self,conversation_id,query="",sender=None,since=0,until=2**63-1,cursor=None,limit=20):
        if not isinstance(query,str) or len(query)>256 or type(limit) is not int or not 1<=limit<=100:
            raise AXRError("invalid_context_budget")
        self.ensure_policy();review=self.config.get('account_review',{})
        if review.get('enabled'):
            if self.journal.clock()>=review['deadline']:raise AXRError('account_review_expired')
            if until==2**63-1:until=review['snapshot_until']
            if until>review['snapshot_until']:raise AXRError('account_review_snapshot_range')
            limit=min(limit,6)
            self.journal.db.execute('INSERT OR IGNORE INTO review_read_budget VALUES(?,0)',(self.principal,))
            if self.journal.db.execute('UPDATE review_read_budget SET pages=pages+1 WHERE principal=? AND pages<?',
                    (self.principal,review['max_pages'])).rowcount!=1:raise AXRError('account_review_page_budget_exhausted')
        after=None
        resource=self.resource(conversation_id)
        if cursor:
            cursor_data=self.journal.context(cursor,self.principal,resource,self.guard.version)
            if cursor_data.get("filters")!=[query,sender,since,until]:raise AXRError("cursor_filter_mismatch")
            after=cursor_data["after"]
        action=self._read_action(conversation_id,
            dict(query=query,sender=sender,since=since,until=until,after=after,limit=limit))
        receipt=self.runtime.propose(action)
        if receipt["state"]=="Ready":return self.execute(receipt["id"])
        return receipt

    def _read(self,action,check,epoch):
        check()
        options=dict(action.payload)
        options.pop("visual_binding",None) # Sealed owner selector, not a query filter.
        readback_job=options.pop("readback_job",None)
        manual_readback=options.pop('manual_readback_job',None)
        if self.config["mode"]=="ui":options["guard_context"]=check.commit_proof()
        try:page=self.adapter.search(action.resource.conversation_id,**options)
        except AXRError as error:
            # Static codes only: never persist exception text, SQL or bodies.
            codes={'sender_identity_unknown','private_chat_sender_identity_mismatch',
                'wcdb_compression_dictionary_required','message_compression_invalid',
                'wcdb_schema_not_qualified','group_sender_not_resolved','unknown_wcdb_compression',
                'database_query_failed_not_empty_result'}
            code=str(error) if str(error) in codes else 'unclassified'
            self.journal.meter('read_failure_'+code)
            raise
        check() # A changed policy cannot disclose or persist a newly fetched page.
        self.journal.meter("pages_read")
        if readback_job is not None or manual_readback is not None:
            original=self.journal.action(self.journal.get(readback_job or manual_readback,self.principal))
            expected='reply.prepare' if manual_readback else 'messages.send'
            if original.operation!=expected or original.resource!=action.resource:
                raise AXRError("readback_resource_changed")
            matches=[m for m in page["messages"] if m.get("text")==original.payload["text"] and m.get("outgoing") is True
                     and m.get("sender")==self.account and type(m.get("server_id")) is int and m["server_id"]>0
                     and not m.get("truncated") and not m.get("text_truncated")]
            observation={"database_record_observed":len(matches)==1 and not page.get("has_more"),
                         "matching_record_count":len(matches),"delivery_confirmed":False,"body_disclosed":False}
            # Never create a disclosable body context from a send observation.
            return {"epoch":epoch,"verified":True,"evidence_digest":digest(observation),"output":observation}
        # Context cost cap independent of requested record count. No global chat cache.
        messages=[];remaining=24000
        for message in page["messages"]:
            text=message.get("text")
            if not isinstance(text,str):continue
            safe_text,masked=mask_credentials(text)
            clipped=safe_text.encode("utf8")[:min(remaining,4000)].decode("utf8","ignore")
            if not clipped:break
            remaining-=len(clipped.encode("utf8"))
            messages.append({**message,"text":clipped,"truncated":clipped!=safe_text,"credentials_redacted":masked,
                "data_class":self.bindings[action.resource.conversation_id].get("data_class","personal"),
                "trust":"untrusted-external"})
        context={"messages":messages,"coverage":page["coverage"],"complete_history":False,
                 "read_scope":{k:action.payload[k] for k in ('since','until','limit')},
                 "scanned":page.get('scanned'),"has_more":bool(page.get('has_more')),
                 "budget_truncated":len(messages)<len([m for m in page["messages"] if isinstance(m.get("text"),str)]) or any(m["truncated"] for m in messages)}
        cid=self.journal.remember(self.principal,action.resource,context,self.guard.version,ttl=900)
        next_cursor=None
        if page.get("cursor"):
            next_cursor=self.journal.remember(self.principal,action.resource,
                {"filters":[action.payload[k] for k in ("query","sender","since","until")],"after":page["cursor"]},
                self.guard.version,ttl=min(3600,max(1,self.config['account_review']['deadline']-self.journal.clock()))
                    if self.config.get('account_review',{}).get('enabled') else 300)
        return {"epoch":epoch,"verified":True,"evidence_digest":digest([cid,len(messages)]),
            "output":{"context_id":cid,"count":len(messages),"cursor":next_cursor,"has_more":bool(page.get("has_more")),
                      'scanned':page.get('scanned'),'budget_truncated':context['budget_truncated'],
                      'effective_limit':action.payload['limit'],
                      "coverage":page["coverage"],"complete_history":False,"body_disclosed":False}}

    def _sources(self,resource,context_ids=()):
        # Conservative session taint: callers cannot launder read data by omitting context IDs.
        active=self.journal.db.execute("SELECT id,resource FROM contexts WHERE principal=? AND expires>? AND policy_version=?",
            (self.principal,self.journal.clock(),self.guard.version)).fetchall()
        chosen=set(context_ids)
        sources={(p.resource.key,p.reference):p for p in self.journal.disclosure_taint(self.principal)}
        for row in active:
            for cid in self.bindings:
                r=self.resource(cid)
                if row["resource"]!=r.key:continue
                data=self.journal.context(row["id"],self.principal,r,self.guard.version)
                for m in data.get("messages",[]):
                    p=Provenance(r,m["reference"],m["data_class"]);sources[(r.key,p.reference)]=p
                chosen.discard(row["id"])
        if chosen:raise AXRError("context_not_owned_or_expired")
        if len(sources)>200:raise AXRError("provenance_budget_exhausted")
        return tuple(sources.values())

    def disclose(self,conversation_id,context_id,*,runner=False):
        resource=self.resource(conversation_id)
        data=self.journal.context(context_id,self.principal,resource,self.guard.version)
        sources=tuple(Provenance(resource,m["reference"],m["data_class"]) for m in data["messages"])
        return self.runtime.propose(self._action(conversation_id,"disclosure.send",{"context_id":context_id,"context_digest":digest(data),"runner":runner},
                                   sources=sources,destination=self.destination))

    def _disclose(self,action,check,epoch):
        check();data=self.journal.context(action.payload["context_id"],self.principal,action.resource,self.guard.version)
        if digest(data)!=action.payload["context_digest"]:raise AXRError("context_intent_digest_changed")
        # Persist scope before transmitting, including uncertain/failed calls.
        for message in data["messages"]:
            self.journal.taint_disclosure(self.principal,action.resource,message["data_class"])
        if action.payload.get("runner"):
            from .runner import invoke
            data=invoke(self,action,check)
        return {"epoch":epoch,"verified":True,"evidence_digest":digest(data),"output":data}

    def prepare(self,conversation_id,text,context_ids=(),*,workflow="manual"):
        if not isinstance(text,str) or not text.strip() or len(text.encode("utf8"))>8000:raise AXRError("invalid_reply_text")
        prefix=self.config.get("attribution_prefix","【自动回复 · AI 助理】")
        display=self.config.get("display_attribution",True)
        if len(prefix)>120 or (display and not prefix.strip()):raise AXRError("owner_attribution_invalid")
        if display and not text.startswith(prefix):text=prefix+" "+text
        action=self._action(conversation_id,"reply.prepare",{"text":text,"attribution":{"display":display,"origin":"agent","principal":self.principal}},
                            sources=self._sources(self.resource(conversation_id),context_ids),workflow=workflow)
        receipt=self.runtime.propose(action)
        if receipt["state"]=="Ready":receipt=self.execute(receipt["id"])
        return receipt

    def _prepare(self,action,check,epoch):
        check()
        cid=self.journal.remember(self.principal,action.resource,{"draft":asdict(action)},self.guard.version,ttl=900)
        return {"epoch":epoch,"verified":True,"evidence_digest":action.seal,
            "output":{"draft_id":cid,"preview":True,"manual_submission":self.manual_replies,
                      "automatic_send":False}}

    def propose_send(self,conversation_id,draft_id):
        if self.manual_replies:raise AXRError('human_submission_only')
        resource=self.resource(conversation_id)
        data=self.journal.context(draft_id,self.principal,resource,self.guard.version)
        draft=Action.from_dict(data["draft"])
        return self.runtime.propose(self._action(conversation_id,"messages.send",draft.payload,
            sources=tuple({(p.resource.key,p.reference):p for p in (*draft.sources,*self._sources(resource))}.values()),
            destination="wechat:"+resource.key,workflow=draft.workflow))

    def _send(self,action,check,epoch):
        if self.manual_replies:raise AXRError('human_submission_only')
        if self.config["mode"] not in {"ui","hybrid"}:raise AXRError("database_read_mode_has_no_send_authority")
        return self.adapter.send(action,check,epoch)

    def observe_send_record(self,jid):
        """Separate read AET; never retry a send or promote an Unknown receipt."""
        with self.runtime.lock:
            self.ensure_policy()
            if self.config["mode"] not in {"wcdb","hybrid"}:raise AXRError("database_readback_required")
            row=self.journal.get(jid,self.principal)
            action=self.journal.action(row)
            if action.operation!="messages.send" or row["state"] not in {"Completed","Unknown"}:
                raise AXRError("completed_or_unknown_send_required")
            text=action.payload["text"]
            read_action=self._read_action(action.resource.conversation_id,
                {"query":text[:256],"sender":self.account,"since":max(0,int(row["created"])-1),
                 "until":2**63-1,"after":None,"limit":50,"readback_job":jid})
            classes={p.data_class for p in action.sources}
            read_action=replace(read_action,sources=(*read_action.sources,
                *(Provenance(action.resource,"readback-class:"+data_class,data_class) for data_class in sorted(classes))))
            read=self.runtime.propose(read_action)
            if read["state"]=="Ready":read=self.execute(read["id"])
            summary={"send_state":row["state"],"send_state_changed":False,"retry":False,
                     "delivery_confirmed":False,"database_record_observed":False,"read_job":read}
            if read["state"]!="Completed":return summary
            # An existing/manual identical record is not proof of this UI action's
            # delivery. Report observation only; retain Unknown and disable retries.
            summary.update(read["result"])
            return summary

    def observe_manual_reply(self,jid):
        """Observe an exact human-submitted draft; never claim AXR sent it."""
        with self.runtime.lock:
            self.ensure_policy()
            if self.config['mode'] not in {'wcdb','hybrid'}:raise AXRError('database_readback_required')
            row=self.journal.get(jid,self.principal);action=self.journal.action(row)
            if row['state']!='Completed' or action.operation!='reply.prepare':
                raise AXRError('completed_reply_draft_required')
            self.guard.revalidate(action,row['grant_id'],row['policy_version'])
            read_action=self._read_action(action.resource.conversation_id,
                {'query':action.payload['text'][:256],'sender':self.account,'since':max(0,int(row['created'])-1),
                 'until':2**63-1,'after':None,'limit':50,'manual_readback_job':jid})
            classes={p.data_class for p in action.sources}
            read_action=replace(read_action,sources=(*read_action.sources,
                *(Provenance(action.resource,'manual-readback-class:'+c,c) for c in sorted(classes))))
            read=self.runtime.propose(read_action)
            if read['state']=='Ready':read=self.execute(read['id'])
            result={'submission':'human','agent_sent':False,'delivery_confirmed':False,
                    'database_record_observed':False,'read_job':read}
            if read['state']=='Completed':result.update(read['result'])
            return result

    def execute(self,jid,dry_run=False):
        with self.runtime.lock:return self._execute_locked(jid,dry_run)

    def _execute_locked(self,jid,dry_run=False):
        self.ensure_policy()
        if self.manual_replies:
            row=self.journal.get(jid,self.principal)
            if self.journal.action(row).operation=='messages.send':raise AXRError('human_submission_only')
        receipt=self.runtime.execute(jid,self.principal,dry_run)
        if receipt.get("state")=="Completed":
            row=self.journal.get(jid,self.principal);action=self.journal.action(row)
            self.guard.revalidate(action,row["grant_id"],row["policy_version"])
            try:receipt["result"]=self.journal.result(jid,self.principal,self.guard.version)
            except AXRError:pass
        return receipt

    def simulate(self,conversation_id,events):
        if len(events)>100:raise AXRError("simulation_event_limit")
        resource=self.resource(conversation_id)
        policy=self.config.get("listener",{})
        return self.admission.evaluate(resource,events,policy,lambda:self.guard.check(
            self._read_action(conversation_id,{},workflow=policy.get("workflow","manual"))),replay=True)

    def write_workspace(self,conversation_id,path,text,context_ids=()):
        return self.runtime.propose(self._action(conversation_id,"workspace.write",{"path":path,"text":text},
            sources=self._sources(self.resource(conversation_id),context_ids)))

    def poll_tasks(self):
        with self.runtime.lock:
            self.ensure_policy();self.journal.purge()
            tasks=[]
            for task in self.inbox.list():
                self.resource(task['conversation_id'])
                job=self.journal.get(task['disclosure_job'],self.principal)
                state=job['state']
                if state=='AwaitingApproval':
                    try:self.guard.check(self.journal.action(job));state='Ready'
                    except AXRError:pass
                tasks.append({'task_id':task['id'],'conversation_id':task['conversation_id'],
                    'disclosure_job':job['id'],'state':'DraftReadyForHuman' if task['draft_job'] else state,
                    'draft_job':task['draft_job'],'expires':task['expires'],'body_disclosed':False,
                    'origin':task.get('origin','incoming_reply')})
            return {'tasks':tasks,'submission':'human','automatic_send':False}

    def request_task(self,conversation_id,since=0,limit=6,cursor=None,until=2**63-1):
        """Explicit bounded context task, distinct from a newly received message."""
        with self.runtime.lock:
            if type(limit) is not int or not 1<=limit<=6:raise AXRError('reply_task_page_limit')
            read=self.read(conversation_id,since=since,limit=limit,cursor=cursor,until=until)
            if read['state']!='Completed':return {'read_job':read,'body_disclosed':False}
            handle=read['result']['context_id'];proposal=self.disclose(conversation_id,handle)
            task_id=self.inbox.create(self.resource(conversation_id),handle,proposal['id'],origin='explicit_read')
            return {'task_id':task_id,'disclosure_job':proposal['id'],'read_job':read,
                    'body_disclosed':False,'automatic_send':False,'origin':'explicit_read'}

    def acknowledge_review(self,task_id,summary):
        with self.runtime.lock:
            self.ensure_policy();review=self.config.get('account_review',{})
            if not review.get('enabled') or self.journal.clock()>=review['deadline']:raise AXRError('account_review_not_active')
            if not isinstance(summary,str) or len(summary.encode('utf8'))>16000:raise AXRError('review_summary_budget')
            task=self.inbox.get(task_id);row=self.journal.get(task['disclosure_job'],self.principal)
            if row['state']!='Completed':raise AXRError('reply_task_context_not_disclosed')
            action=self.journal.action(row);self.guard.revalidate(action,row['grant_id'],row['policy_version'])
            context=self.journal.context(task['context_id'],self.principal,action.resource,self.guard.version)
            data={'id':task_id,'principal':self.principal,'resource':action.resource.key,'version':self.guard.version,
                  'expires':review['deadline'],'summary':summary,'context_digest':digest(context),
                  'text_records':len(context['messages']),'budget_truncated':context.get('budget_truncated',False)}
            data.update(read_scope=context.get('read_scope'),scanned=context.get('scanned'),has_more=context.get('has_more'))
            self.journal.db.execute('INSERT INTO review_notes VALUES(?,?,?,?,?,?)',
                (task_id,self.principal,action.resource.key,self.guard.version,review['deadline'],self.journal.vault.seal(data,task_id+':review')))
            self.journal.db.execute('DELETE FROM reply_tasks WHERE id=? AND principal=?',(task_id,self.principal))
            self.journal.db.execute('DELETE FROM contexts WHERE id=? AND principal=?',(task['context_id'],self.principal))
            self.journal.meter('review_pages_acknowledged')
            return {'state':'Reviewed','text_records':data['text_records'],'summary_stored_encrypted':True,
                    'budget_truncated':data['budget_truncated'],'agent_sent':False}

    def wait_tasks(self,timeout=40,after=None):
        if type(timeout) is not int or not 0<=timeout<=45:raise AXRError('invalid_task_wait_timeout')
        if after is None:after={}
        if not isinstance(after,dict) or len(after)>50 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in after.items()):
            raise AXRError('invalid_task_wait_state')
        deadline=time.monotonic()+timeout
        while True:
            result=self.poll_tasks()
            result['tasks']=[t for t in result['tasks'] if after.get(t['task_id'])!=t['state']]
            if result['tasks'] or self.stop_event.is_set() or time.monotonic()>=deadline:return result
            self.stop_event.wait(min(0.5,max(0,deadline-time.monotonic())))

    def task_context(self,task_id):
        with self.runtime.lock:
            self.ensure_policy();task=self.inbox.get(task_id)
            resource=self.resource(task['conversation_id'])
            row=self.journal.get(task['disclosure_job'],self.principal)
            action=self.journal.action(row)
            if (action.resource!=resource or action.operation!='disclosure.send' or
                    action.payload.get('context_id')!=task['context_id'] or action.payload.get('runner')):
                raise AXRError('reply_task_disclosure_binding_mismatch')
            if row['state']=='AwaitingApproval':
                try:self.guard.check(action)
                except AXRError:return {'state':'AwaitingApproval','job_id':row['id'],'body_disclosed':False}
            result=self.execute(row['id'])
            return {'task_id':task_id,'conversation_id':task['conversation_id'],
                    'context_id':task['context_id'],'body_disclosed':result.get('state')=='Completed' and 'result' in result,
                    'disclosure':result,'submission':'human','automatic_send':False}

    def finish_task(self,task_id,draft_job):
        with self.runtime.lock:
            self.ensure_policy();task=self.inbox.get(task_id)
            row=self.journal.get(draft_job,self.principal);action=self.journal.action(row)
            if (row['state']!='Completed' or action.operation!='reply.prepare' or
                    action.resource!=self.resource(task['conversation_id'])):
                raise AXRError('completed_matching_reply_draft_required')
            disclosure=self.journal.get(task['disclosure_job'],self.principal)
            if disclosure['state']!='Completed':raise AXRError('reply_task_context_not_disclosed')
            self.guard.revalidate(self.journal.action(disclosure),disclosure['grant_id'],disclosure['policy_version'])
            context=self.journal.context(task['context_id'],self.principal,action.resource,self.guard.version)
            expected={m['reference'] for m in context['messages']}
            actual={p.reference for p in action.sources if p.resource==action.resource}
            if not expected.issubset(actual):raise AXRError('reply_task_sources_missing')
            self.guard.revalidate(action,row['grant_id'],row['policy_version'])
            self.journal.result(draft_job,self.principal,self.guard.version)
            self.inbox.finish(task_id,draft_job)
            return {'state':'DraftReadyForHuman','task_id':task_id,'draft_job':draft_job,
                    'automatic_send':False,'submission':'human'}

    def tick(self):
        # Config controls are read on every tick. Any revocation invalidates cached context and workers.
        with self.runtime.lock:
            fresh=self.store.config()
            if fresh!=self.config:
                self.admission.clear();self.baselines.clear();self.config=fresh
                # Data-source/account/principal changes need a new broker, never hot-rebind.
                self.stop_event.set();return {"state":"policy_changed_restart_required"}
            if self.guard.version!=self.active_policy_version:
                self.admission.clear();self.pending_drafts.clear();self.baselines.clear()
                self.active_policy_version=self.guard.version
            # Privacy maintenance continues while all business controls are off.
            # Purge never reads WeChat or deletes an active commit's payload.
            self.journal.purge()
            self.inbox.purge()
            self.journal.db.execute('DELETE FROM review_notes WHERE expires<=? OR version!=?',(self.journal.clock(),self.guard.version))
            policy=self.config.get("listener",{})
            if not policy.get("listen",False):self.admission.clear();return {"state":"listener_off"}
            if policy.get("auto_execute",False):
                remaining=[]
                for proposal in self.pending_drafts:
                    row=self.journal.get(proposal["job_id"],self.principal)
                    if row["state"] in {"Completed","Unknown","FailedSafe","Expired","Cancelled","Denied"}:continue
                    try:self.guard.check(self.journal.action(row))
                    except AXRError:remaining.append(proposal);continue
                    self.execute(proposal["job_id"])
                self.pending_drafts=remaining
            decisions=[]
            for cid in self.bindings:
                resource=self.resource(cid)
                # Listener pages use the same AET/lease/quota path as explicit reads.
                # Six bounded text records fit the 24k local context budget.
                from_now=policy.get('start_from_now',False)
                payload=dict(query="",sender=None,since=self.listener_since if from_now else 0,
                             until=2**63-1,after=self.cursors.get(cid),limit=6)
                action=self._read_action(cid,payload,workflow=policy.get("workflow","manual"))
                self.guard.check(action)
                proposal=self.runtime.propose(action);receipt=self.execute(proposal["id"])
                if receipt["state"]!="Completed":raise AXRError("listener_page_not_verified")
                result=receipt["result"]
                page=self.journal.context(result["context_id"],self.principal,resource,self.guard.version)
                cursor=result.get("cursor")
                if cursor:
                    self.cursors[cid]=self.journal.context(cursor,self.principal,resource,self.guard.version)["after"]
                else:self.cursors[cid]=payload["after"]
                # These local baseline pages are never a disclosure handle. Only an
                # admitted runner batch creates a new reviewable disclosure context.
                for handle in (result["context_id"],cursor):
                    if handle:self.journal.db.execute("DELETE FROM contexts WHERE id=? AND principal=?",(handle,self.principal))
                if not from_now and resource.key not in self.baselines:
                    for m in page["messages"]:self.journal.seen(resource,m["reference"])
                    if not result["has_more"]:self.baselines.add(resource.key)
                    continue
                result=self.admission.evaluate(resource,page["messages"],policy,lambda:self.guard.check(action))
                decisions.extend(result["decisions"])
                batch=self.admission.drain(resource,policy)
                if batch:
                    if not self.config.get("runner",{}).get("enabled",False):
                        data={'messages':batch,'coverage':'admitted_listener_batch','complete_history':False}
                        handle=self.journal.remember(self.principal,resource,data,self.guard.version,ttl=300)
                        try:
                            proposal=self.disclose(cid,handle)
                            self.inbox.create(resource,handle,proposal['id'])
                        except BaseException:
                            self.journal.db.execute('DELETE FROM contexts WHERE id=? AND principal=?',(handle,self.principal))
                            raise
                        self.journal.meter('reply_tasks_created');continue
                    self.journal.meter("runner_proposals")
                    from .runner import run
                    # Runner receives only scoped data after independent disclosure approval.
                    outcome=run(self,resource,batch,policy)
                    self.pending_drafts.append(outcome)
                    self.pending_drafts=self.pending_drafts[-50:]
            self.journal.purge();return {"decisions":decisions,"model_calls":0}

    def start_listener(self):
        def loop():
            while not self.stop_event.is_set():
                try:self.tick()
                except Exception:
                    with self.runtime.lock:self.journal.meter("listener_failures")
                self.stop_event.wait(max(1,min(60,self.config.get("listener",{}).get("poll_seconds",5))))
        self.listener_thread=threading.Thread(target=loop,daemon=True);self.listener_thread.start()

    def close(self):
        self.stop_event.set()
        self.runner_supervisor.cancel()
        if self.navigation is not None:self.navigation.cancel()
        if hasattr(self.adapter,"cancel"):self.adapter.cancel()
        if self.listener_thread:
            self.listener_thread.join(timeout=12)
            if self.listener_thread.is_alive():raise AXRError("listener_shutdown_timeout_resources_retained")
        with self.runtime.lock:
            self.adapter.close();self.lifetime.__exit__();self.store.close()


def register(mcp,service):
    # Sync handlers are executed by the MCP SDK; Runtime serializes account transactions.
    @mcp.tool(annotations={"readOnlyHint":True})
    def wechat_status()->dict:return service.status()
    @mcp.tool(annotations={"readOnlyHint":True})
    def wechat_find_conversations(offset:int=0,limit:int=100)->dict:return service.conversations(offset,limit)
    @mcp.tool()
    def wechat_ui_navigate(command:str)->dict:
        """Propose an owner-allowlisted menu action. No contact selection, reading or sending."""
        return service.navigate(command)
    @mcp.tool()
    def wechat_read_context(conversation_id:str,query:str="",sender:str|None=None,since:int=0,
                            until:int=2**63-1,cursor:str|None=None,limit:int=20)->dict:
        """Read a bounded local context. Returns handles; body needs a separate disclosure approval."""
        return service.read(conversation_id,query,sender,since,until,cursor,limit)
    @mcp.tool()
    def wechat_disclose_context(conversation_id:str,context_id:str)->dict:
        """Propose disclosure to the owner-pinned model destination. Never self-approve."""
        return service.disclose(conversation_id,context_id)
    @mcp.tool()
    def wechat_prepare_reply(conversation_id:str,text:str,context_ids:list[str])->dict:
        return service.prepare(conversation_id,text,context_ids)
    @mcp.tool(annotations={"readOnlyHint":True})
    def wechat_poll_tasks()->dict:
        """List scoped reply tasks without message bodies; approval stays with the local owner."""
        return service.poll_tasks()
    @mcp.tool()
    def wechat_request_task(conversation_id:str,since:int=0,limit:int=6,cursor:str|None=None,until:int=2**63-1)->dict:
        """Request a bounded context task; old content is not a newly received reply."""
        return service.request_task(conversation_id,since,limit,cursor,until)
    @mcp.tool(annotations={"readOnlyHint":True})
    def wechat_wait_for_tasks(timeout:int=40,after:dict[str,str]|None=None)->dict:
        """Wait up to 45 seconds for metadata only. Requires a running, authorized listener."""
        return service.wait_tasks(timeout,after)
    @mcp.tool()
    def wechat_get_task_context(task_id:str)->dict:
        """Return an exact owner-approved batch; unapproved tasks return metadata only."""
        return service.task_context(task_id)
    @mcp.tool()
    def wechat_finish_task(task_id:str,draft_job:str)->dict:
        """Associate a completed reply draft with its task. Human submission remains pending."""
        return service.finish_task(task_id,draft_job)
    @mcp.tool()
    def wechat_observe_manual_reply(draft_job:str)->dict:
        """Read WCDB for an exact human-submitted draft. Counts only; no send or delivery claim."""
        return service.observe_manual_reply(draft_job)
    @mcp.tool()
    def wechat_acknowledge_review(task_id:str,summary:str)->dict:
        """Store a bounded encrypted review note after exact disclosure; never send or grant."""
        return service.acknowledge_review(task_id,summary)
    @mcp.tool()
    def wechat_propose_send(conversation_id:str,draft_id:str)->dict:
        return service.propose_send(conversation_id,draft_id)
    @mcp.tool()
    def wechat_observe_send_record(job_id:str)->dict:
        """Read a separate bounded WCDB AET for exact outgoing text. Counts only;
        no resend, no Unknown state change, no claim of recipient delivery."""
        return service.observe_send_record(job_id)
    @mcp.tool()
    def axr_execute(job_id:str,dry_run:bool=False)->dict:return service.execute(job_id,dry_run)
    @mcp.tool()
    def axr_job_status(job_id:str)->dict:return service.journal.receipt(job_id,service.principal)
    @mcp.tool()
    def axr_cancel(job_id:str)->dict:return service.runtime.cancel(job_id,service.principal)
    @mcp.tool()
    def axr_policy_simulate(conversation_id:str,events:list[dict])->dict:return service.simulate(conversation_id,events)
    @mcp.tool()
    def axr_workspace_write(conversation_id:str,path:str,text:str,context_ids:list[str])->dict:
        return service.write_workspace(conversation_id,path,text,context_ids)
    @mcp.tool()
    def axr_run_approved_batch(job_id:str)->dict:
        from .runner import execute_batch
        with service.runtime.lock:return execute_batch(service,job_id)
    @mcp.tool()
    def poll_messages()->dict:
        """Compatibility name: bounded authorized reads via AET; never bypass Guard."""
        return {"jobs":[service.read(cid) for cid in service.bindings]}
    @mcp.tool()
    def reply_to_message(conversation_id:str,text:str,context_ids:list[str])->dict:
        """AXR compatibility entry prepares a draft; explicit AET approval required to send."""
        return service.prepare(conversation_id,text,context_ids)
