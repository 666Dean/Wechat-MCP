# SPDX-License-Identifier: MIT
"""OS-authenticated local setup and exact batch approvals; never an MCP tool."""
import argparse
import json
import time
import uuid
from contextlib import closing
from pathlib import Path
from axr.aet import AXRError, Resource, digest
from axr.owner import authenticate, approve, review
from axr.policy import OwnerStore
from .inbox import Inbox
from .policy import validate_controls


def qualify_existing_contacts(store,policy,labels):
    """Owner-selected replacement contacts; reuse only verified local keys."""
    from adapters.wcdb_keys import inventory,qualify_contacts
    from adapters.wcdb_owner import verified_cached
    shards=policy.get('database',{}).get('shards',[])
    roots={Path(s['path']).absolute().parent.parent for s in shards}
    if len(roots)!=1:raise AXRError('qualified_single_account_root_required')
    root=roots.pop();rows=inventory(root);keys=verified_cached(store,root,rows)
    item=keys.get('contact/contact.db')
    if not item:raise AXRError('verified_contact_key_required')
    return qualify_contacts(rows['contact/contact.db']['path'],policy['database'].get('sqlcipher_library'),
        store.secrets.get(item['key_reference']),policy['account_id'],labels,account_root=root,
        engine=policy['database'].get('engine','sqlcipher'))


def setup(store,ttl,uses,contacts=None):
    if type(ttl) is not int or not 60<=ttl<=3600 or type(uses) is not int or not 1<=uses<=500:
        raise AXRError('codex_setup_budget_invalid')
    policy=store.config()
    if not policy.get('database') or not 1<=len(policy['conversations'])<=32:
        raise AXRError('qualified_database_and_private_bindings_required')
    if contacts is not None:
        policy={**policy,'conversations':qualify_existing_contacts(store,policy,contacts),
                'principal':'codex:'+uuid.uuid4().hex}
        # Prior model disclosure taint remains attached to its old principal.
        # This replacement must use a NEW ephemeral model conversation; never
        # reconnect a model retaining the old private chat's memory.
    policy={**policy,'mode':'wcdb','agent_destination':'model:codex',
            'runner':{'enabled':False},'listener':{'listen':True,'wake_agent':True,'auto_execute':False,
            'start_from_now':True,'keywords':['AXR测试','@Codex'],'aggregate_seconds':2,'poll_seconds':5,
            'event_ttl':300,'workflow':'manual'}}
    validate_controls(policy)
    store.guard.revoke_owner('policy-change');store.seal_config(policy)
    for binding in policy['conversations']:
        resource=Resource('wechat',policy['account_id'],binding['conversation_id'])
        store.guard._issue_owner(principal=policy['principal'],resource=resource,
            operations=['messages.read','messages.search','reply.prepare'],purpose=policy.get('purpose','wechat-assistant'),
            expires_at=time.time()+ttl,max_uses=uses,classes=[binding.get('data_class','personal')])
    return {'configured':True,'bindings':len(policy['conversations']),'destination':'model:codex',
            'ttl':ttl,'max_uses_per_binding':uses,'submission':'human','automatic_send':False,
            'fresh_model_conversation_required':contacts is not None,
            'body_disclosure':'exact_owner_approval_per_context','keywords':policy['listener']['keywords']}


def approve_session_task(store,task,policy):
    """Trusted local owner delegation, not an agent-facing issuer endpoint."""
    principal=policy['principal'];row=store.journal.get(task['disclosure_job'],principal)
    if row['state']!='AwaitingApproval' or row['expires']<=store.journal.clock():return False
    action=store.journal.action(row)
    allowed={Resource('wechat',policy['account_id'],b['conversation_id']).key:b for b in policy['conversations']}
    binding=allowed.get(action.resource.key)
    if (binding is None or action.principal!=principal or action.operation!='disclosure.send' or
            action.destination!='model:codex' or action.workflow!='manual' or
            action.purpose!=policy.get('purpose','wechat-assistant') or action.payload.get('runner') or
            task['context_id']!=action.payload.get('context_id')):
        raise AXRError('owner_session_task_outside_scope')
    data=store.journal.context(task['context_id'],principal,action.resource,store.guard.version)
    messages=data.get('messages',[])
    if (len(messages)>6 or sum(len(m.get('text','').encode('utf8')) for m in messages)>24000 or
            any(m.get('data_class')!=binding.get('data_class','personal') for m in messages) or
            any(p.resource!=action.resource or p.data_class!=binding.get('data_class','personal') for p in action.sources) or
            {p.reference for p in action.sources}!={m['reference'] for m in messages} or
            digest(data)!=action.payload.get('context_digest')):
        raise AXRError('owner_session_context_outside_budget')
    # Preserve native exact-intent, one-use, <=300-second disclosure grants.
    approve(store,row['id'],principal)
    return True


def session(store,ttl,uses,batches,contacts=None):
    if type(batches) is not int or not 1<=batches<=12:raise AXRError('owner_session_batch_limit')
    result=setup(store,ttl,uses,contacts);policy=store.config();seal=digest(policy)
    deadline=time.monotonic()+ttl;wall_deadline=time.time()+ttl;version=store.guard.version
    inbox=Inbox(store.journal,store.guard,policy['principal']);seen=set();approved=0
    print(json.dumps({**result,'owner_session_started':True,'max_disclosures':batches}),flush=True)
    try:
        while time.monotonic()<deadline and time.time()<wall_deadline:
            if store.guard.version!=version or digest(store.config())!=seal:
                raise AXRError('owner_session_policy_changed')
            for task in inbox.list():
                if approved>=batches:break
                if task['id'] in seen:continue
                if approve_session_task(store,task,policy):
                    seen.add(task['id']);approved+=1
                    print(json.dumps({'exact_context_approved':True,'count':approved}),flush=True)
                    if approved>=batches:break
            time.sleep(0.5)
    except KeyboardInterrupt:pass
    finally:
        # Removing authority invalidates pending contexts and stops cached work.
        store.guard.revoke_owner('owner-session-ended')
        current=store.config()
        if digest(current)==seal:
            current['listener'].update(listen=False,wake_agent=False,auto_execute=False)
            store.seal_config(current)
        print(json.dumps({'owner_session_ended':True,'approved_contexts':approved,'authority_revoked':True}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',required=True);p.add_argument('--helper',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('setup');init.add_argument('--ttl',type=int,default=1800);init.add_argument('--uses',type=int,default=300)
    pending=sub.add_parser('approve');pending.add_argument('--job',action='append',required=True)
    delegated=sub.add_parser('session');delegated.add_argument('--ttl',type=int,default=3600)
    delegated.add_argument('--uses',type=int,default=400);delegated.add_argument('--batches',type=int,default=12)
    delegated.add_argument('--contact',action='append',help='Exact owner-selected contact labels replacing previous bindings')
    args=p.parse_args()
    try:
        if args.command=='approve':
            # Snapshot and review precise intents before authentication. Newly
            # arriving tasks cannot join this authorization while the UI is open.
            with closing(OwnerStore(args.state)) as store:
                principal=store.config()['principal']
                if not 1<=len(set(args.job))<=8:raise AXRError('exact_batch_approval_limit')
                seals={jid:review(store,jid,principal)['seal'] for jid in set(args.job)}
                for jid in seals:
                    action=store.journal.action(store.journal.get(jid,principal))
                    if action.operation!='disclosure.send' or action.destination!='model:codex' or action.payload.get('runner'):
                        raise AXRError('codex_context_disclosure_only')
        authenticate(args.helper)
        with closing(OwnerStore(args.state)) as store:
            if args.command=='session':session(store,args.ttl,args.uses,args.batches,args.contact);return
            if args.command=='setup':result=setup(store,args.ttl,args.uses)
            else:
                principal=store.config()['principal']
                for jid,seal in seals.items():
                    if review(store,jid,principal)['seal']!=seal:raise AXRError('approval_intent_changed')
                    approve(store,jid,principal)
                result={'approved_exact_contexts':len(seals),'submission':'human','automatic_send':False}
            print(json.dumps(result,ensure_ascii=False))
    except AXRError as exc:p.exit(1,str(exc)+'\n')


if __name__=='__main__':main()
