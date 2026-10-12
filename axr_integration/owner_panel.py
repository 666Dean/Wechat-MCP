# SPDX-License-Identifier: MIT
"""Local owner console. Never exposed by MCP or loaded by the listener."""
import argparse
import json
import threading
import tkinter as tk
from tkinter import ttk,messagebox
from axr.policy import OwnerStore
from axr.owner import authenticate,approve,review
from axr.aet import AXRError
from .policy import validate_controls

class Panel:
    def __init__(self,root,state,helper):
        self.root,self.state,self.helper=root,state,helper
        root.title('WeChat AXR · Local Owner');root.geometry('920x680')
        self.tabs=ttk.Notebook(root);self.tabs.pack(fill='both',expand=True,padx=12,pady=12)
        settings=ttk.Frame(self.tabs);jobs=ttk.Frame(self.tabs);status=ttk.Frame(self.tabs)
        self.tabs.add(settings,text='Policy');self.tabs.add(jobs,text='Exact approvals');self.tabs.add(status,text='Local telemetry')
        ttk.Label(settings,text='Policy changes revoke previous authority and require broker restart.').pack(anchor='w')
        self.editor=tk.Text(settings,wrap='none');self.editor.pack(fill='both',expand=True)
        controls=ttk.Frame(settings);controls.pack(fill='x');self.switches={}
        self.control_widgets=[]
        for name in ('listen','wake_agent','auto_execute'):
            var=tk.BooleanVar();self.switches[name]=var
            widget=ttk.Checkbutton(controls,text=name,variable=var);widget.pack(side='left');self.control_widgets.append(widget)
        ttk.Button(controls,text='Apply controls to JSON',command=self.set_switches).pack(side='left')
        ttk.Button(controls,text='Review and authenticate policy',command=self.configure).pack(side='right')
        ttk.Label(jobs,text='Approval seals the exact target, body, sources, purpose and expiry below.').pack(anchor='w')
        self.job_list=ttk.Treeview(jobs,columns=('state','expires'),show='tree headings',height=6)
        self.job_list.heading('#0',text='Job ID');self.job_list.heading('state',text='State');self.job_list.heading('expires',text='Expiry')
        self.job_list.pack(fill='x');self.job_list.bind('<<TreeviewSelect>>',self.select_job)
        self.intent=tk.Text(jobs,wrap='word',state='disabled');self.intent.pack(fill='both',expand=True)
        bar=ttk.Frame(jobs);bar.pack(fill='x');ttk.Button(bar,text='Refresh',command=self.refresh).pack(side='left')
        ttk.Button(bar,text='Deny selected job',command=lambda:self.decide(False)).pack(side='right')
        ttk.Button(bar,text='Authenticate exact approval',command=lambda:self.decide(True)).pack(side='right')
        self.metrics=tk.Text(status,wrap='word',state='disabled');self.metrics.pack(fill='both',expand=True)
        ttk.Button(status,text='Refresh counters and verify audit',command=self.refresh).pack(anchor='e')
        drafts=ttk.Frame(self.tabs);self.tabs.add(drafts,text='Manual replies')
        ttk.Label(drafts,text='Review the exact private chat and AI attribution. Copy here; submit yourself in WeChat.').pack(anchor='w')
        self.draft_list=ttk.Treeview(drafts,columns=('target',),show='tree headings',height=6)
        self.draft_list.heading('#0',text='Draft job');self.draft_list.heading('target',text='Target')
        self.draft_list.pack(fill='x');self.draft_list.bind('<<TreeviewSelect>>',self.select_draft)
        self.draft_text=tk.Text(drafts,wrap='word',state='disabled');self.draft_text.pack(fill='both',expand=True)
        ttk.Button(drafts,text='Copy exact draft for manual submission',command=self.copy_draft).pack(anchor='e')
        root.bind('<F6>',lambda event:(self.tabs.select(drafts),self.draft_list.focus_set(),'break')[-1])
        self.notice=tk.StringVar(value='Owner-only console. Chat content cannot change authority.')
        ttk.Label(root,textvariable=self.notice).pack(anchor='w',padx=12,pady=6)
        ttk.Label(root,text='F1: policy · F2: exact approvals · F3: telemetry · F4: draft controls · F5: refresh').pack(anchor='w',padx=12)
        for number in range(3):
            root.bind(f'<F{number+1}>',lambda event,index=number:self.show_tab(index))
        root.bind('<F4>',self.focus_controls)
        root.bind('<F5>',lambda event:(self.refresh(),'break')[1])
        with self.store() as store:
            config=store.config();self.editor.insert('1.0',json.dumps(config,ensure_ascii=True,indent=2))
            for name,var in self.switches.items():var.set(config.get('listener',{}).get(name,False))
        self.refresh()
    def show_tab(self,index):
        self.tabs.select(index)
        (self.editor,self.job_list,self.metrics)[index].focus_set()
        return 'break'
    def focus_controls(self,event=None):
        self.tabs.select(0);self.control_widgets[0].focus_set()
        return 'break'
    def show_intent(self,text):
        self.intent.configure(state='normal');self.intent.delete('1.0','end')
        self.intent.insert('1.0',text);self.intent.configure(state='disabled')
    def store(self):
        from contextlib import contextmanager
        @contextmanager
        def open_store():
            store=OwnerStore(self.state)
            try:yield store
            finally:store.close()
        return open_store()
    def set_switches(self):
        try:
            config=json.loads(self.editor.get('1.0','end'));config.setdefault('listener',{}).update({k:v.get() for k,v in self.switches.items()})
            self.editor.delete('1.0','end');self.editor.insert('1.0',json.dumps(config,ensure_ascii=True,indent=2))
        except Exception:messagebox.showerror('Invalid policy','Policy must be a JSON object.')
    def authenticated(self,callback):
        # The local terminal remains a required trust boundary; Tk buttons alone grant nothing.
        def work():
            try:authenticate(self.helper);callback();message='Owner operation completed.'
            except Exception as exc:message=str(exc) if isinstance(exc,AXRError) else 'Owner operation failed safely.'
            self.root.after(0,lambda:self.notice.set(message));self.root.after(0,self.refresh)
        threading.Thread(target=work,daemon=True).start()
    def configure(self):
        try:
            config=json.loads(self.editor.get('1.0','end'))
            if not isinstance(config,dict):raise ValueError()
            validate_controls(config)
        except Exception:messagebox.showerror('Invalid policy','Policy must be a JSON object and controls must be true/false booleans.');return
        if not messagebox.askyesno('Review policy','Authorize precisely the JSON currently displayed? All previous capabilities will be invalidated.'):
            return
        def commit():
            with self.store() as store:store.guard.revoke_owner('policy-change');store.seal_config(config)
        self.authenticated(commit)
    def selected(self):
        selection=self.job_list.selection()
        if len(selection)!=1:raise AXRError('select_one_job')
        return selection[0]
    def select_job(self,event=None):
        if not self.job_list.selection():
            self.show_intent('');return
        try:
            jid=self.selected()
            with self.store() as store:
                principal=store.config()['principal'];row=store.journal.get(jid,principal)
                from dataclasses import asdict
                text=json.dumps(review(store,jid,principal),ensure_ascii=True,indent=2)
            self.show_intent(text)
        except AXRError as exc:self.show_intent('');self.notice.set(str(exc))
    def decide(self,allowed):
        try:jid=self.selected()
        except AXRError as exc:self.notice.set(str(exc));return
        def commit():
            with self.store() as store:
                principal=store.config()['principal']
                if allowed:approve(store,jid,principal)
                else:store.journal.transition(jid,principal,'Denied')
        self.authenticated(commit)
    def selected_draft(self):
        selected=self.draft_list.selection()
        if len(selected)!=1:raise AXRError('select_one_reply_draft')
        return selected[0]
    def select_draft(self,event=None):
        self.draft_text.configure(state='normal');self.draft_text.delete('1.0','end')
        try:
            from .manual_reply import review_draft
            with self.store() as store:value=review_draft(store,self.selected_draft())
            self.draft_text.insert('1.0',value['display_name']+'\n'+value['conversation_id']+'\n\n'+value['text'])
        except AXRError as exc:self.notice.set(str(exc))
        finally:self.draft_text.configure(state='disabled')
    def copy_draft(self):
        try:
            from .manual_reply import review_draft
            with self.store() as store:value=review_draft(store,self.selected_draft())
            # Re-read the sealed draft immediately before the explicit human copy.
            self.root.clipboard_clear();self.root.clipboard_append(value['text'])
            self.notice.set('Draft copied. Verify the target in WeChat and submit yourself; nothing was sent by AXR.')
        except AXRError as exc:self.notice.set(str(exc))
    def refresh(self):
        previous=self.job_list.selection()
        with self.store() as store:
            principal=store.config()['principal'];rows=store.journal.db.execute("SELECT id,state,expires FROM jobs WHERE principal=? AND state IN ('AwaitingApproval','Ready') ORDER BY created DESC LIMIT 50",(principal,)).fetchall()
            self.job_list.delete(*self.job_list.get_children())
            for row in rows:self.job_list.insert('',tk.END,iid=row['id'],text=row['id'],values=(row['state'],row['expires']))
            data={'counts':store.journal.metrics(),'policy_version':store.guard.version,'audit_valid':store.journal.verify_audit()}
            self.metrics.configure(state='normal');self.metrics.delete('1.0','end');self.metrics.insert('1.0',json.dumps(data,indent=2));self.metrics.configure(state='disabled')
        available=self.job_list.get_children()
        selected=previous[0] if previous and previous[0] in available else (available[0] if available else None)
        if selected:
            self.job_list.focus(selected);self.job_list.selection_set(selected);self.job_list.see(selected)
            self.select_job()
        else:self.show_intent('')
        from .manual_reply import list_drafts
        previous=self.draft_list.selection()
        with self.store() as store:drafts=list_drafts(store)
        self.draft_list.delete(*self.draft_list.get_children())
        for draft in drafts:self.draft_list.insert('',tk.END,iid=draft['job_id'],text=draft['job_id'],values=(draft['display_name'],))
        ids=self.draft_list.get_children()
        if ids:
            selected=previous[0] if previous and previous[0] in ids else ids[0]
            self.draft_list.selection_set(selected);self.select_draft()
        else:
            self.draft_text.configure(state='normal');self.draft_text.delete('1.0','end');self.draft_text.configure(state='disabled')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--state',required=True);parser.add_argument('--helper',required=True);args=parser.parse_args()
    root=tk.Tk();Panel(root,args.state,args.helper);root.mainloop()
if __name__=='__main__':main()
