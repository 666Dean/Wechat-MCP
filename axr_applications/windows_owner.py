# SPDX-License-Identifier: MIT
"""Fixed Windows owner-host control, separate from model-facing MCP.

Installation pins the connection file. Local input can only request the approval
setting, then confirm the exact reviewed challenge. It cannot select a server,
key, role, method, script or arbitrary payload to sign.
"""
import json
from pathlib import Path
import sys
import time
from axr import _axr_native as native
from axr.aet import AXRError, Action, canonical
from axr.authority_server import AuthorityClient
from axr_integration.authority_frontend import load_connection


def enrolled_key(runtime_root):
    """Read only the protected install pin; never provision from a control call.

    Deployment writes this after validating enrollment/hardware evidence. This
    file does not itself attest hardware, confer a role, or replace the service's
    enrolled public key. Native code checks the owner host and entire install
    before it opens the credential or invokes any WinRT API.
    """
    path=Path(runtime_root)/'owner-key.json'
    try:
        with path.open('rb') as source:value=frame(source)
        if (set(value)!={'version','provider','public_key'} or
                type(value['version']) is not int or value['version']!=2 or
                value['provider']!='WindowsHello/RSA2048' or
                type(value['public_key']) is not str or len(value['public_key'])!=588):raise ValueError()
        public=bytes.fromhex(value['public_key'])
        if len(public)!=294 or public.hex()!=value['public_key']:raise ValueError()
    except (OSError,ValueError,TypeError,AXRError):
        raise AXRError('wechat_owner_enrolled_key_pin_required') from None
    return native.WindowsHelloOwnerKey(public)


def frame(stream):
    raw=stream.readline(32769)
    if not raw.endswith(b'\n') or len(raw)>32768:
        raise AXRError('wechat_owner_control_frame_invalid')
    def unique(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError()
            result[key]=value
        return result
    try:
        value=json.loads(raw,object_pairs_hook=unique)
        if type(value) is not dict:raise ValueError()
        return value
    except (ValueError,TypeError):
        raise AXRError('wechat_owner_control_frame_invalid') from None


def control(connection, source, emit, *, connect=AuthorityClient.connect,
            owner_key=None, clock=time.time):
    request=frame(source)
    if request.get('operation')=='approve-job':
        if (set(request)!={'operation','job_id'} or not isinstance(request['job_id'],str) or
                not 1<=len(request['job_id'])<=512):raise AXRError('wechat_owner_control_request_invalid')
        return approve_job(connection,request['job_id'],source,emit,
                           connect=connect,owner_key=owner_key,clock=clock)
    if (set(request)!={'operation','manual_approval_required'} or
            request['operation']!='set-manual-approval' or
            type(request['manual_approval_required']) is not bool):
        raise AXRError('wechat_owner_control_request_invalid')
    required=request['manual_approval_required']
    channel=connect(connection['endpoint'],connection['server'])
    try:
        response=channel.request('Authorize',phase='review-approval-setting',manual_approval_required=required)
        challenge=response.get('challenge',{})
        authority=channel.session.authority
        now=clock()
        fields={'version','kind','root_id','epoch','nonce','peer','owner','required','generation','expires'}
        if (type(challenge) is not dict or set(challenge)!=fields or
                type(challenge['version']) is not int or challenge['version']!=2 or challenge['kind']!='wechat-approval-setting' or
                not authority or challenge['root_id']!=authority['root_id'] or
                challenge['epoch']!=channel.session.authority_epoch or
                challenge['required'] is not required or
                type(challenge['generation']) is not int or challenge['generation']<0 or
                not isinstance(challenge['nonce'],str) or len(challenge['nonce'])!=32 or
                type(challenge['expires']) not in (int,float) or not now<challenge['expires']<=now+60):
            raise AXRError('wechat_owner_control_review_invalid')
        emit({'state':'AwaitingLocalConfirmation','challenge_id':challenge['nonce'],
            'manual_approval_required':required,'generation':challenge['generation'],
            'expires':challenge['expires'],'task_scope_unchanged':True,'agent_sent':False})
        confirmation=frame(source)
        if confirmation!={'confirm':challenge['nonce']}:
            raise AXRError('wechat_owner_control_cancelled')
        if clock()>=challenge['expires']:raise AXRError('wechat_owner_control_review_expired')
        # No creation or silent fallback here. Windows owner-presence provider
        # must be enrolled; current unsupported hardware/provider fails closed.
        if owner_key is None:raise AXRError('wechat_owner_enrolled_key_pin_required')
        key=owner_key()
        signature=key.sign(canonical(challenge))
        if clock()>=challenge['expires']:raise AXRError('wechat_owner_control_review_expired')
        result=channel.request('Authorize',phase='approve-approval-setting',
            manual_approval_required=required,challenge_id=challenge['nonce'],owner_signature=signature.hex())
        if (type(result) is not dict or result.get('manual_approval_required') is not required or
                type(result.get('generation')) is not int or result['generation']!=challenge['generation']+1):
            raise AXRError('wechat_owner_control_outcome_unknown_no_retry')
        emit({'state':'Completed','manual_approval_required':required,
            'generation':result['generation'],'agent_sent':False})
        return result
    finally:channel.close()


def approve_job(connection, handle, source, emit, *, connect, owner_key, clock):
    channel=connect(connection['endpoint'],connection['server'])
    try:
        response=channel.request('Authorize',phase='review-application',job_id=handle)
        challenge=response.get('challenge',{});review=response.get('review',{})
        authority=channel.session.authority;now=clock()
        fields={'version','kind','root_id','epoch','nonce','peer','owner','job_id','seal','contract','expires'}
        if (type(challenge) is not dict or set(challenge)!=fields or type(challenge['version']) is not int or
                challenge['version']!=2 or challenge['kind']!='wechat-application-review' or
                not authority or challenge['root_id']!=authority['root_id'] or
                challenge['epoch']!=channel.session.authority_epoch or challenge['job_id']!=handle or
                not isinstance(challenge['nonce'],str) or len(challenge['nonce'])!=32 or
                type(challenge['expires']) not in (int,float) or not now<challenge['expires']<=now+60 or
                type(review) is not dict or 'action' not in review):
            raise AXRError('wechat_owner_control_review_invalid')
        try:
            action=Action.from_dict(review['action'])
            if action.operation not in ('disclosure.send','messages.send') or action.seal!=challenge['seal']:
                raise ValueError()
        except Exception:raise AXRError('wechat_owner_control_review_invalid') from None
        # Only the protected local owner surface receives this exact preview.
        # It is never a diagnostic log, MCP response or arbitrary signing API.
        emit({'state':'AwaitingLocalConfirmation','challenge_id':challenge['nonce'],
              'expires':challenge['expires'],'review':review,'agent_sent':False})
        if frame(source)!={'confirm':challenge['nonce']}:raise AXRError('wechat_owner_control_cancelled')
        if clock()>=challenge['expires']:raise AXRError('wechat_owner_control_review_expired')
        if owner_key is None:raise AXRError('wechat_owner_enrolled_key_pin_required')
        key=owner_key()
        signature=key.sign(canonical(challenge))
        if clock()>=challenge['expires']:raise AXRError('wechat_owner_control_review_expired')
        result=channel.request('Authorize',phase='approve-application',job_id=handle,
            challenge_id=challenge['nonce'],owner_signature=signature.hex())
        if type(result) is not dict or result.get('approved') is not True or result.get('job_id')!=handle:
            raise AXRError('wechat_owner_control_outcome_unknown_no_retry')
        emit({'state':'Completed','job_id':handle,'approved':True,'agent_sent':False})
        return result
    finally:channel.close()


def main(runtime_root):
    if sys.platform!='win32' or native.security_release is not True:
        raise AXRError('formal_windows_owner_host_required')
    # The native owner host verified the immutable installation before import.
    # No caller-selected config path or startup arguments are accepted.
    connection=load_connection(Path(runtime_root)/'owner-connection.json')
    return control(connection,sys.stdin.buffer,
        lambda value:print(json.dumps(value,ensure_ascii=False),flush=True),
        owner_key=lambda:enrolled_key(runtime_root))
