# SPDX-License-Identifier: MIT
"""Fixed entry of the protected owner host. No business MCP tools or keys."""
import json
import sys
import time
from axr import _axr_native as native
from axr.aet import AXRError, canonical

def main(runtime_root):
    if sys.platform=='win32':
        from .windows_enrollment import main as windows_main
        return windows_main(runtime_root)
    raw=sys.stdin.buffer.readline(32769)
    if len(raw)>32768:raise AXRError('owner_enrollment_frame_budget')
    challenge=json.loads(raw)
    if type(challenge) is dict and challenge.get('operation')=='control':
        return control(runtime_root,challenge)
    if (set(challenge)!={'version','kind','configuration_digest','nonce','expires'} or challenge['version']!=2
        or challenge['kind']!='wechat-owner-enrollment' or len(challenge['nonce'])!=64
        or len(challenge['configuration_digest'])!=64 or not time.time()<challenge['expires']<=time.time()+180):
        raise AXRError('owner_enrollment_challenge_invalid')
    key=native.HardwareSigningKey('Stellaria.AXR.Owner.v2',create=True,user_presence=True,owner_interaction=True)
    signature=key.sign(canonical(challenge))
    if time.time()>=challenge['expires']:raise AXRError('owner_enrollment_challenge_expired')
    print(json.dumps({'version':2,'public_key':key.public_key.hex(),'signature':signature.hex(),
                      'challenge':challenge,'provider':key.provider}),flush=True)

def control(runtime_root,request):
    from pathlib import Path
    from .wechat_frontend import connect
    if set(request)!={'operation','method','arguments'} or type(request['arguments']) is not dict:
        raise AXRError('wechat_owner_request_invalid')
    configuration=json.loads((Path(runtime_root)/'deployment.json').read_bytes())
    client=connect(configuration['deployment']['endpoint'])
    try:
        method=request['method'];args=request['arguments']
        if method=='start':
            reviewed=client.request('WeChatOwner',method='review',arguments=args)
            # Review goes only to the local owner pipe/UI, never an MCP/model.
            # Hardware user presence signs the exact server nonce and scope.
            key=native.HardwareSigningKey('Stellaria.AXR.Owner.v2',user_presence=True,owner_interaction=True)
            challenge=reviewed['challenge'];signature=key.sign(canonical(challenge)).hex()
            result=client.request('WeChatOwner',method='activate',arguments={'nonce':challenge['nonce'],'signature':signature})
        elif method in ('snapshot','stop','manual_draft','assistant_settings','save_assistant_settings','check_target'):
            result=client.request('WeChatOwner',method=method,arguments=args)
        else:raise AXRError('wechat_owner_operation_not_registered')
        print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:client.close()
