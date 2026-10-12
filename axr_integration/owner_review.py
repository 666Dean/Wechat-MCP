# SPDX-License-Identifier: MIT
"""One OS-authenticated, finite account review; not an MCP owner endpoint."""
import argparse
import json
import time
import uuid
from pathlib import Path
from contextlib import closing
from axr.aet import AXRError,Resource,digest,canonical
from axr.owner import authenticate
from axr.policy import OwnerStore
from adapters.wcdb_catalog import discover
from .inbox import Inbox
from .owner_codex import approve_session_task,setup


def session(store,ttl=3600,pages=8192,*,draft_contacts=None,draft_self=False,phase_file=None):
    if type(ttl) is not int or not 60<=ttl<=3600 or type(pages) is not int or not 1<=pages<=8192:
        raise AXRError('account_review_budget_invalid')
    if type(draft_self) is not bool or (phase_file is not None and (Path(phase_file).exists() or not draft_contacts and not draft_self)):
        raise AXRError('owner_review_phase_control_invalid')
    deadline=time.monotonic()+ttl;wall_deadline=time.time()+ttl
    previous=store.config();policy=previous;catalog=discover(store,policy)
    if time.monotonic()>=deadline:raise AXRError('account_review_discovery_timeout')
    contacts=list(draft_contacts or [])+([previous['account_id']] if draft_self else [])
    if len(contacts)>32:raise AXRError('owner_reply_binding_limit')
    policy={**policy,'principal':'codex-review:'+uuid.uuid4().hex,'purpose':'wechat-account-review',
        'mode':'wcdb','agent_destination':'model:codex','database':catalog['database'],
        'conversations':catalog['conversations'],'runner':{'enabled':False},
        'listener':{'listen':False,'wake_agent':False,'auto_execute':False},
        'account_review':{'enabled':True,'snapshot_until':catalog['coverage']['snapshot_until'],'deadline':wall_deadline,
                          'max_pages':pages,'coverage':catalog['coverage']}}
    if not policy['conversations']:raise AXRError('account_catalog_empty')
    if len(canonical({'version':1,'policy':policy}))>500*1024:
        raise AXRError('account_review_policy_requires_partition')
    store.guard.revoke_owner('policy-change');store.seal_config(policy)
    for b in policy['conversations']:
        store.guard._issue_owner(principal=policy['principal'],resource=Resource('wechat',policy['account_id'],b['conversation_id']),
            operations=['messages.read','messages.search'],purpose=policy['purpose'],expires_at=wall_deadline,
            max_uses=pages,classes=['personal'])
    seal=digest(policy);version=store.guard.version
    inbox=Inbox(store.journal,store.guard,policy['principal']);seen=set();approved=0
    phase='review'
    print(json.dumps({'account_review_started':True,'conversations':len(policy['conversations']),
        'coverage':catalog['coverage'],'ttl':ttl,'max_pages':pages,'send_authority':False,
        'fresh_model_conversation_required':True}),flush=True)
    try:
        while time.monotonic()<deadline and time.time()<policy['account_review']['deadline']:
            if store.guard.version!=version or digest(store.config())!=seal:raise AXRError('owner_session_policy_changed')
            if phase=='review' and phase_file is not None and Path(phase_file).exists():
                path=Path(phase_file)
                if path.is_symlink() or path.stat().st_size>16 or path.read_text()!='reply':raise AXRError('owner_review_phase_control_invalid')
                remaining=int(deadline-time.monotonic())
                if remaining<60:raise AXRError('owner_review_no_time_for_reply_phase')
                setup(store,remaining,400,contacts,all_incoming=True)
                policy=store.config();seal=digest(policy);version=store.guard.version
                inbox=Inbox(store.journal,store.guard,policy['principal']);seen=set();approved=0;phase='reply'
                print(json.dumps({'reply_phase_started':True,'bindings':len(policy['conversations']),
                    'ttl':remaining,'max_disclosures':12,'all_incoming':True,'submission':'human'}),flush=True)
            for task in inbox.list():
                if approved>=(pages if phase=='review' else 12):break
                if task['id'] not in seen and approve_session_task(store,task,policy):
                    seen.add(task['id']);approved+=1
                    print(json.dumps({'review_batch_approved':approved}),flush=True)
            time.sleep(.25)
    except KeyboardInterrupt:pass
    finally:
        store.guard.revoke_owner('account-review-ended')
        current=store.config()
        if digest(current)==seal:
            previous['listener']={**previous.get('listener',{}),'listen':False,'wake_agent':False,'auto_execute':False}
            store.seal_config(previous)
        print(json.dumps({'account_review_ended':True,'approved_batches':approved,'authority_revoked':True}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--helper',required=True)
    p.add_argument('--ttl',type=int,default=3600);p.add_argument('--pages',type=int,default=8192)
    p.add_argument('--draft-contact',action='append');p.add_argument('--draft-self',action='store_true');p.add_argument('--phase-file')
    args=p.parse_args()
    try:
        print(json.dumps({'operation':'account_review','account_scope':'existing_qualified_account',
            'ttl':args.ttl,'max_pages':args.pages,'messages_per_batch':6,'utf8_bytes_per_batch':24000,
            'draft_contacts':args.draft_contact or [],'draft_self':args.draft_self,
            'reply_phase_requested':args.phase_file is not None,'submission':'human','send_authority':False}),flush=True)
        authenticate(args.helper)
        with closing(OwnerStore(args.state)) as store:session(store,args.ttl,args.pages,
            draft_contacts=args.draft_contact,draft_self=args.draft_self,phase_file=args.phase_file)
    except AXRError as e:p.exit(1,str(e)+'\n')


if __name__=='__main__':main()
