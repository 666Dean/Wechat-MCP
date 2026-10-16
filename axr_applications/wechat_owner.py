# SPDX-License-Identifier: MIT
"""Fixed entry of the protected owner host. No business MCP tools or keys."""
import json
import sys
import time
from axr import _axr_native as native
from axr.aet import AXRError, canonical

def main(runtime_root):
    raw=sys.stdin.buffer.readline(32769)
    if len(raw)>32768:raise AXRError('owner_enrollment_frame_budget')
    challenge=json.loads(raw)
    if (set(challenge)!={'version','kind','configuration_digest','nonce','expires'} or challenge['version']!=2
        or challenge['kind']!='wechat-owner-enrollment' or len(challenge['nonce'])!=64
        or len(challenge['configuration_digest'])!=64 or not time.time()<challenge['expires']<=time.time()+180):
        raise AXRError('owner_enrollment_challenge_invalid')
    key=native.HardwareSigningKey('Stellaria.AXR.Owner.v2',create=True,user_presence=True,owner_interaction=True)
    signature=key.sign(canonical(challenge))
    if time.time()>=challenge['expires']:raise AXRError('owner_enrollment_challenge_expired')
    print(json.dumps({'version':2,'public_key':key.public_key.hex(),'signature':signature.hex(),
                      'challenge':challenge,'provider':key.provider}),flush=True)
