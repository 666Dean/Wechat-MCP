# SPDX-License-Identifier: MIT
"""WeChat orchestration. No WeChat service implementation is placed in AXR/."""
import hmac
import json
import threading
import time
from dataclasses import asdict
from pathlib import Path
from axr.aet import AXRError,Action,Resource,Provenance,canonical,digest
from axr.policy import OwnerStore
from axr.host import Lease,Supervisor
from axr.runtime import Runtime
from axr.workspace import Workspace
from axr.admission import Budget,Admission

class Service:
    def __init__(self,state,*,store=None,adapter=None,leases=None):
        self.store=store or OwnerStore(state)
        self.guard,self.journal=self.store.guard,self.store.journal
        self.config=self.store.config()
        self.initial_policy_digest=digest(self.config)
        self.principal=self.config["principal"]
        self.purpose=self.config.get("purpose","wechat-assistant")
        self.account=self.config["account_id"]
        self.destination=self.config["agent_destination"]
        if self.destination=="local":raise AXRError("model_disclosure_destination_must_be_explicit")
        self.bindings={b["conversation_id"]:b for b in self.config["conversations"]}
        if not self.bindings or len(self.bindings)>32:raise AXRError("explicit_conversation_bindings_required")
        # Global per-user lease root independent of journal/config locations.
        lease_root=Path(leases) if leases else Path.home()/".stellaria-axr"/"leases"
        self.lifetime=Lease(lease_root,["journal",str(self.store.directory)])
        self.lifetime.__enter__()
        try:
            if not self.journal.verify_audit():raise AXRError("journal_audit_integrity_failed")
            self.journal.recover();self.journal.purge()
            if adapter is not None:self.adapter=adapter
            elif self.config["mode"]=="wcdb":
                from adapters.wcdb import DatabaseAdapter
                self.adapter=DatabaseAdapter({**self.config["database"],"account_id":self.account,
                    "conversations":self.config["conversations"]},self.store.secrets)
            elif self.config["mode"]=="ui":
                from adapters.ui import UIAdapter
                self.adapter=UIAdapter({**self.config["ui"],"account_id":self.account,"conversations":self.config["conversations"]})
            else:raise AXRError("unknown_data_mode")
            handlers={"messages.read":self._read,"messages.search":self._read,
                      "disclosure.send":self._disclose,"reply.prepare":self._prepare,"messages.send":self._send}
            if self.config.get("workspace"):
                self.workspace=Workspace(self.config["workspace"],self.store.vault,self.store.directory/"versions")
                handlers["workspace.write"]=self.workspace.write
            self.runtime=Runtime(self.guard,self.journal,lease_root,handlers)
            self.budget=Budget(self.journal);self.admission=Admission(self.guard,self.journal,self.budget)
            self.stop_event=threading.Event();self.listener_thread=None
            self.runner_supervisor=Supervisor(timeout=min(60,self.config.get("runner",{}).get("timeout",30)))
            self.baselines=set();self.cursors={};self.pending_drafts=[]
            self.active_policy_version=self.guard.version
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
            "restart_required":digest(self.store.config())!=self.initial_policy_digest}

    def conversations(self):
        return {"conversations":[{"conversation_id":k,"display_name":v["display_name"]} for k,v in self.bindings.items()],
                "coverage":"explicit_owner_bindings"}

    def _action(self,conversation_id,operation,payload,*,sources=(),destination="local",workflow="manual"):
        self.ensure_policy()
        return Action(self.principal,self.resource(conversation_id),operation,self.purpose,payload,
                      tuple(sources),destination,workflow)

    def read(self,conversation_id,query="",sender=None,since=0,until=2**63-1,cursor=None,limit=20):
        if not isinstance(query,str) or len(query)>256 or type(limit) is not int or not 1<=limit<=100:
            raise AXRError("invalid_context_budget")
        after=None
        resource=self.resource(conversation_id)
        if cursor:
            cursor_data=self.journal.context(cursor,self.principal,resource,self.guard.version)
            if cursor_data.get("filters")!=[query,sender,since,until]:raise AXRError("cursor_filter_mismatch")
            after=cursor_data["after"]
        action=self._action(conversation_id,"messages.search" if query else "messages.read",
            dict(query=query,sender=sender,since=since,until=until,after=after,limit=limit))
        data_class=self.bindings[conversation_id].get("data_class","personal")
        if data_class in {"sensitive","credentials","financial"}:
            from dataclasses import replace
            action=replace(action,sources=(Provenance(resource,"query:"+digest(action.payload),data_class),))
        receipt=self.runtime.propose(action)
        if receipt["state"]=="Ready":return self.execute(receipt["id"])
        return receipt

    def _read(self,action,check,epoch):
        check()
        page=self.adapter.search(action.resource.conversation_id,**action.payload)
        check() # A changed policy cannot disclose or persist a newly fetched page.
        self.journal.meter("pages_read")
        # Context cost cap independent of requested record count. No global chat cache.
        messages=[];remaining=24000
        for message in page["messages"]:
            text=message.get("text")
            if not isinstance(text,str):continue
            clipped=text.encode("utf8")[:min(remaining,4000)].decode("utf8","ignore")
            if not clipped:break
            remaining-=len(clipped.encode("utf8"))
            messages.append({**message,"text":clipped,"truncated":clipped!=text,
                "data_class":self.bindings[action.resource.conversation_id].get("data_class","personal"),
                "trust":"untrusted-external"})
        context={"messages":messages,"coverage":page["coverage"],"complete_history":False,
                 "budget_truncated":len(messages)<len([m for m in page["messages"] if isinstance(m.get("text"),str)]) or any(m["truncated"] for m in messages)}
        cid=self.journal.remember(self.principal,action.resource,context,self.guard.version,ttl=900)
        next_cursor=None
        if page.get("cursor") and page.get("has_more"):
            next_cursor=self.journal.remember(self.principal,action.resource,
                {"filters":[action.payload[k] for k in ("query","sender","since","until")],"after":page["cursor"]},
                self.guard.version,ttl=300)
        return {"epoch":epoch,"verified":True,"evidence_digest":digest([cid,len(messages)]),
            "output":{"context_id":cid,"count":len(messages),"cursor":next_cursor,
                      "coverage":page["coverage"],"complete_history":False,"body_disclosed":False}}

    def _sources(self,resource,context_ids=()):
        # Conservative session taint: callers cannot launder read data by omitting context IDs.
        active=self.journal.db.execute("SELECT id,resource FROM contexts WHERE principal=? AND expires>? AND policy_version=?",
            (self.principal,self.journal.clock(),self.guard.version)).fetchall()
        chosen=set(context_ids);sources={}
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
        return {"epoch":epoch,"verified":True,"evidence_digest":action.seal,"output":{"draft_id":cid,"preview":True}}

    def propose_send(self,conversation_id,draft_id):
        resource=self.resource(conversation_id)
        data=self.journal.context(draft_id,self.principal,resource,self.guard.version)
        draft=Action.from_dict(data["draft"])
        return self.runtime.propose(self._action(conversation_id,"messages.send",draft.payload,
            sources=tuple({(p.resource.key,p.reference):p for p in (*draft.sources,*self._sources(resource))}.values()),
            destination="wechat:"+resource.key,workflow=draft.workflow))

    def _send(self,action,check,epoch):
        if self.config["mode"]!="ui":raise AXRError("database_read_mode_has_no_send_authority")
        return self.adapter.send(action,check,epoch)

    def execute(self,jid,dry_run=False):
        with self.runtime.lock:return self._execute_locked(jid,dry_run)

    def _execute_locked(self,jid,dry_run=False):
        self.ensure_policy()
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
            self._action(conversation_id,"messages.read",{},workflow=policy.get("workflow","manual"))),replay=True)

    def write_workspace(self,conversation_id,path,text,context_ids=()):
        return self.runtime.propose(self._action(conversation_id,"workspace.write",{"path":path,"text":text},
            sources=self._sources(self.resource(conversation_id),context_ids)))

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
                action=self._action(cid,"messages.read",{},workflow=policy.get("workflow","manual"))
                self.guard.check(action)
                page=self.adapter.search(cid,after=self.cursors.get(cid),limit=50)
                self.cursors[cid]=page.get("cursor")
                if resource.key not in self.baselines:
                    for m in page["messages"]:self.journal.seen(resource,m["reference"])
                    if not page.get("has_more"):self.baselines.add(resource.key)
                    continue
                result=self.admission.evaluate(resource,page["messages"],policy,lambda:self.guard.check(action))
                decisions.extend(result["decisions"])
                batch=self.admission.drain(resource,policy)
                if batch:
                    if not self.config.get("runner",{}).get("enabled",False):
                        self.journal.meter("runner_disabled_batches");continue
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
        if hasattr(self.adapter,"cancel"):self.adapter.cancel()
        if self.listener_thread:
            self.listener_thread.join(timeout=12)
            if self.listener_thread.is_alive():raise AXRError("listener_shutdown_timeout_resources_retained")
        with self.runtime.lock:
            self.adapter.close();self.lifetime.__exit__();self.store.close()


def register(mcp,service):
    # Sync handlers are executed by the MCP SDK; Runtime serializes account transactions.
    @mcp.tool()
    def wechat_status()->dict:return service.status()
    @mcp.tool()
    def wechat_find_conversations()->dict:return service.conversations()
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
    @mcp.tool()
    def wechat_propose_send(conversation_id:str,draft_id:str)->dict:
        return service.propose_send(conversation_id,draft_id)
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
