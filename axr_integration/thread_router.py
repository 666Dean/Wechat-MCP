# SPDX-License-Identifier: MIT
"""Owner-selected conversation routing with explicit lifecycle busy/idle handoff."""
import hmac,json,os,shlex,sys,time,threading
from pathlib import Path
from axr.aet import AXRError
from axr import _axr_native as native

class ThreadRouter:
    def __init__(self,broker):
        self.broker=broker;self.thread_id='';self.state='unpaired';self.ready_at=0;self.turn_id=None
        self.pending=False;self.cached_pending=False;self.hooks_observed=False;self.lock=threading.RLock()
    def bind(self,thread_id):
        with self.lock:
            if self.thread_id!=thread_id:
                self.thread_id=thread_id;self.state='awaiting_lifecycle' if thread_id else 'unpaired'
                self.hooks_observed=False;self.pending=False;self.cached_pending=False
    def event(self,thread_id,event,turn,source=None,worker_token=None):
        with self.lock:return self._event(thread_id,event,turn,source,worker_token)
    def _event(self,thread_id,event,turn,source,worker_token):
        if thread_id!=self.thread_id:return {'ignored':True}
        if source=='codex_hook_v1':self.hooks_observed=True
        # A headless resume may itself run the trusted hooks. Its lifecycle must
        # not interrupt its own worker or masquerade as a new desktop user turn.
        expected=getattr(self.broker,'worker_hook_token',None)
        if expected and isinstance(worker_token,str) and hmac.compare_digest(expected,worker_token):
            return {'worker_event':True,'continue_pending':False}
        if event in ('UserPromptSubmit','SessionStart'):
            self.state='busy';self.turn_id=turn;self.broker.stop_worker()
        elif event=='Interrupt':
            self.state='paused';self.turn_id=turn;self.broker.stop_worker()
        elif event=='Stop':
            # Stop can run before app turn/completed. Keep the current loop alive
            # for pending tasks rather than inserting a new user input mid-turn.
            service=getattr(self.broker.service,'_delegate',None)
            self.pending=False
            # schedule() maintains this metadata projection outside the event
            # lock. If a new task arrives after this snapshot, an idle schedule
            # resumes the same chat after the quiet interval instead.
            if service and service.automatic and service.automatic.status()['active']:
                self.pending=bool(self.cached_pending)
            self.state='busy' if self.pending else 'idle';self.ready_at=time.monotonic()+2
            return {'continue_pending':self.pending}
        return {'recorded':True}
    def status(self):
        with self.lock:return {'thread_id':self.thread_id,'state':self.state,'pending':self.pending,'hooks_observed':self.hooks_observed}
    def schedule(self):
        if not self.thread_id:return
        service=getattr(self.broker.service,'_delegate',None)
        if not service or not service.automatic or not service.automatic.status()['active']:return
        with service.runtime.lock:
            if not service.automatic or not service.automatic.status()['active']:return
            pending=service.automatic.has_pending() or any(not t['draft_job'] and t.get('origin')=='incoming_reply' for t in service.inbox.list())
        with self.lock:
            self.pending=pending;self.cached_pending=pending
            if not self.pending:return
            if self.state!='idle' or time.monotonic()<self.ready_at:return
            process=self.broker.automatic_worker
            if process is not None and process.poll() is None:return
            self.state='worker';self.broker.start_worker(300,self.thread_id)
    def worker_finished(self):
        with self.lock:
            if self.state=='worker':
                process=self.broker.automatic_worker
                self.state='paused' if process is not None and process.returncode else 'idle'
                self.ready_at=time.monotonic()+2

def install_hooks(state,root,python):
    """Preserve existing definitions; Codex itself handles review/trust, never bypass it."""
    path=Path.home()/'.codex/hooks.json'
    if path.is_symlink():raise AXRError('codex_hooks_link_rejected')
    previous=path.read_bytes() if path.exists() else b''
    data=json.loads(previous) if previous else {'hooks':{}}
    command=shlex.join([str(Path(python).absolute()),str(Path(root).resolve()/'scripts/codex_lifecycle_hook.py'),str(Path(state).resolve())])
    for event in ('UserPromptSubmit','SessionStart','Stop','Interrupt'):
        rows=data.setdefault('hooks',{}).setdefault(event,[])
        if not any(h.get('command')==command for group in rows for h in group.get('hooks',[])):
            rows.append({'hooks':[{'type':'command','command':command,'timeout':2}]})
    if previous:
        backup=Path(state)/('codex-hooks-backup-'+str(time.time_ns())+'.json')
        if not native.durable_write(str(backup),previous):raise AXRError('codex_hooks_backup_failed')
    if (path.read_bytes() if path.exists() else b'')!=previous:raise AXRError('codex_hooks_changed_review_again')
    if not native.durable_write(str(path),json.dumps(data,ensure_ascii=False,indent=2).encode()):raise AXRError('codex_hooks_write_failed')
    return {'installed':True,'trust_required':True,'path':str(path)}
