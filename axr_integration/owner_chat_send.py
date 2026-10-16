# SPDX-License-Identifier: MIT
"""Interactive compatibility client for the shared bounded Mac sender.

MCP automatic replies use the same executor through an authenticated broker
session. This CLI does not grant authority to MCP or enable continuous replies.
"""
import argparse,json,sys
from pathlib import Path
from contextlib import closing
from .chat_plan import load_plan
from .chat_executor import claim_attempt
from axr.owner import authenticate
from axr.policy import OwnerStore
from axr.aet import AXRError

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--state',required=True);parser.add_argument('--native-helper',required=True)
 parser.add_argument('--owner-helper',required=True);parser.add_argument('--plan',required=True)
 parser.add_argument('--check-plan',action='store_true')
 args=parser.parse_args(argv);plan=load_plan(args.plan)
 if args.check_plan:
  print(json.dumps({'plan_valid':True,'message_count':len(plan['messages']),'permission_granted':False,'ui_accessed':False}));return 0
 if sys.platform!='darwin':raise AXRError('mac_chat_plan_only')
 if not sys.stdin.isatty() or not sys.stdout.isatty():raise AXRError('owner_interactive_terminal_required')
 STATE=Path(args.state).resolve(strict=True);HELPER=Path(args.native_helper).resolve(strict=True)
 print('Review this exact local plan. Up to 20 minutes; two existing bound private targets only. At most one non-replacing draft insertion and one submission per message, eight searches per target, 40 local metadata probes, 14 readback pages per message. Non-exact draft echo stops sending and preserves the unsent input. Foreground window use is required. No screenshot, injection, model disclosure or configuration changes. Unknown never retries.',flush=True)
 print(json.dumps(plan,ensure_ascii=False),flush=True)
 authenticate(Path(args.owner_helper).resolve(strict=True))
 from .chat_executor import execute_plan
 with closing(OwnerStore(STATE)) as store:
  results=execute_plan(store,STATE,HELPER,plan)
  for result in results:print(json.dumps(result),flush=True)
  print('{"ended":true,"authority_revoked":true}',flush=True)
  return 0 if len(results)==len(plan['messages']) and all(r['exact_database_records']==1 for r in results) else 1



if __name__=='__main__':
 try:sys.exit(main())
 except AXRError as exc:print(json.dumps({'error':str(exc),'retry':False}));sys.exit(1)
 except Exception:print(json.dumps({'error':'owner_plan_failed_safe','retry':False}));sys.exit(1)
