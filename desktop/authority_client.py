# SPDX-License-Identifier: MIT
"""Desktop owner controls use the pinned native owner, never a bearer token."""
import json
import re
import sys
from pathlib import Path
import subprocess
from axr.aet import AXRError,canonical

if sys.platform=='win32':
    from axr import _axr_native as native
    OWNER=Path(native.windows_installation_root())/'axr-owner.exe'
else:OWNER=Path('/Library/Application Support/Stellaria AXR/AXR Owner.app/Contents/MacOS/axr-owner')

def installed():return OWNER.is_file()

def control(method,arguments=None,timeout=180):
    process=subprocess.run([str(OWNER),'--owner-control' if sys.platform=='win32' else '--owner-enroll'],input=canonical({'operation':'control','method':method,
        'arguments':arguments or {}})+b'\n',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,
        **({'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}))
    if process.returncode:
        # Preserve a bounded machine code so the UI can explain a missing OS
        # permission before another authentication is attempted. Never display
        # arbitrary stderr, a traceback or native credential diagnostics.
        for line in process.stderr[:16384].splitlines():
            try:code=json.loads(line).get('error_code')
            except (ValueError,AttributeError):continue
            if isinstance(code,str) and re.fullmatch('[a-z][a-z0-9_]{0,99}',code):raise AXRError(code)
        raise AXRError('independent_authority_control_unavailable')
    if len(process.stdout)>1024*1024:raise AXRError('owner_response_budget')
    value=json.loads(process.stdout)
    if value.get('error'):raise AXRError(value['error'])
    return value

def call(state,method,args=(),kwargs=None,*,owner=False,timeout=180):
    if not owner and method!='status':raise AXRError('managed_mcp_frontend_required')
    if method=='control.snapshot':
        value=control('snapshot');status=value['status'];scope=status.get('scope') or {}
        status['automatic_reply']={'active':status['automatic_reply'],'supported':sys.platform in ('darwin','win32'),
            'ready':all(status.get('permissions',{}).get(k,False) for k in ('database','accessibility')),
            'expires':scope.get('expires',0),
            'remaining':max(0,scope['max_replies']-status['reply_count']) if scope.get('max_replies') else None,
            'targets':scope.get('reply_targets',[])}
        value['grants']=[{'conversation_id':identity,'operations':['messages.read','reply.prepare']+(['messages.send'] if identity in scope.get('reply_targets',[]) else []),
            'expires':scope.get('expires',0),'remaining':status['automatic_reply']['remaining'],
            'destinations':['Codex'] if scope.get('disclose') else [],'exact_intent':True} for identity in scope.get('targets',[])]
        return value
    if method in ('control.revoke_all','control.stop_automatic'):return control('stop')
    if method=='control.approve_pending':return control('approve_pending',{'job_id':args[0]})
    if method=='control.set_manual_approval':return control('set_manual_approval',{'required':args[0]})
    if method=='control.start_automatic':
        targets,seconds,count=args[:3]
        return control('start',{'targets':'all' if not targets or targets==['*'] else targets,'seconds':seconds,
            'max_replies':count,'automatic':True,'disclose':True,'overwrite_drafts':bool(args[3]) if len(args)>3 else False,
            'self_agent':bool(args[4]) if len(args)>4 else False},timeout=180)
    if method=='control.codex_models':
        from axr_integration.codex_bridge import models
        return models()
    if method=='control.codex_threads':
        from axr_integration.codex_bridge import threads
        return threads(args[0] if args else None)
    if method in ('control.claim_owner_task','control.finish_owner_task','control.queue_owner_prompt','control.cancel_owner_task'):
        return control(method.split('.',1)[1],dict(args[0]) if args else {})
    if method=='control.assistant_settings':return control('assistant_settings')
    if method=='control.save_assistant_settings':return control('save_assistant_settings',dict(args[0]))
    if method in ('control.draft','control.manual_draft'):
        return control('manual_draft',{'job_id':args[0]})
    if method=='status':return control('snapshot')['status']
    raise AXRError('independent_owner_feature_unavailable')
