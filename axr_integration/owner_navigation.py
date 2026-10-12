# SPDX-License-Identifier: MIT
"""Interactive one-command navigation qualification. Never an MCP approval tool."""
import argparse
from contextlib import closing
import json
import sys
from pathlib import Path
from axr.aet import AXRError, Action, Resource
from axr.host import Lease
from axr.owner import authenticate, approve
from axr.policy import OwnerStore
from axr.runtime import Runtime
from adapters.macos.navigation import NavigationAdapter, CATALOG, APPLICATION_SCOPE


def cleanup(store,jid,principal,gid):
    try:
        if gid:store.guard.revoke_owner(gid)
    finally:
        # Do not retain qualification results until TTL, even if revocation
        # fails. Scope cleanup to this job; leave other transactions intact.
        store.journal.db.execute('UPDATE results SET payload=NULL,expires=0 WHERE id=? AND principal=?',(jid,principal))
        store.journal.purge()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',required=True)
    parser.add_argument('--helper',required=True)
    parser.add_argument('--command',choices=sorted(CATALOG),required=True)
    args=parser.parse_args()
    adapter=NavigationAdapter({'native_helper':str(Path(args.helper).resolve(strict=True)), 'actions':[args.command]})
    gid=None
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():raise AXRError('owner_interactive_terminal_required')
        binding=adapter.binding(args.command)
        print(json.dumps({'review':args.command,'navigation_binding':binding,'ttl_seconds':240,'uses':1,
            'content_read':False,'message_sent':False,'capture':False},ensure_ascii=False),flush=True)
        authenticate(args.helper)
        with closing(OwnerStore(args.state)) as store:
            policy=store.config()
            if any(policy.get('listener',{}).get(k,False) for k in ('listen','wake_agent','auto_execute')) or policy.get('runner',{}).get('enabled',False):
                raise AXRError('qualification_requires_listener_and_runner_disabled')
            leases=Path.home()/'.stellaria-axr'/'leases'
            with Lease(leases,['journal',str(store.directory)]):
                if not store.journal.verify_audit():raise AXRError('journal_audit_integrity_failed')
                action=Action('owner:navigation-probe',Resource('wechat',policy['account_id'],APPLICATION_SCOPE),
                    'application.navigate','wechat-menu-qualification',{'command':args.command,'navigation_binding':binding})
                errors=[]
                def execute(action,check,epoch):
                    try:return adapter.execute(action,check,epoch)
                    except AXRError as exc:
                        errors.append(str(exc));raise
                runtime=Runtime(store.guard,store.journal,leases,{'application.navigate':execute})
                proposal=runtime.propose(action)
                try:
                    gid=approve(store,proposal['id'],action.principal)
                    receipt=runtime.execute(proposal['id'],action.principal)
                    result={'state':receipt['state'],'audit_valid':store.journal.verify_audit(),
                            'content_read':False,'message_sent':False}
                    if receipt['state']=='Completed':
                        result['observation']=store.journal.result(proposal['id'],action.principal,store.guard.version)
                    if errors:result['error']=errors[-1]
                    print(json.dumps(result,ensure_ascii=False),flush=True)
                    return 0 if receipt['state']=='Completed' else 1
                finally:
                    cleanup(store,proposal['id'],action.principal,gid)
    finally:adapter.cancel()


if __name__=='__main__':
    try:sys.exit(main())
    except AXRError as exc:print(json.dumps({'error':str(exc)}));sys.exit(1)
