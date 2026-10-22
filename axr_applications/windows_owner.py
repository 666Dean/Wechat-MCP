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
from axr.aet import AXRError, Action, canonical,digest
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
    if request.get('operation')=='control':
        return service_control(connection,request,emit,connect=connect,owner_key=owner_key,clock=clock)
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


def service_control(connection,request,emit,*,connect,owner_key,clock,confirm=None):
    """Same owner service methods as Mac, using protected Windows review/Hello.

    The native local window replaces Mac's existing owner review surface. No
    model method, server address, executable or arbitrary signing text enters.
    """
    allowed={'start','approve_pending','set_manual_approval','snapshot','stop','manual_draft','assistant_settings','save_assistant_settings',
        'check_target','codex_lifecycle','claim_owner_task','finish_owner_task','queue_owner_prompt','cancel_owner_task'}
    if set(request)!={'operation','method','arguments'} or request['method'] not in allowed or type(request['arguments']) is not dict:
        raise AXRError('wechat_owner_control_request_invalid')
    method=request['method'];args=request['arguments']
    if method=='set_manual_approval':
        if set(args)!={'required'} or type(args['required']) is not bool:raise AXRError('wechat_owner_control_request_invalid')
        class Input:
            raw=canonical({'operation':'set-manual-approval','manual_approval_required':args['required']})+b'\n'
            def readline(self,maximum):value,self.raw=self.raw,b'';return value[:maximum]
        source=Input()
        def reviewed(value):
            if value.get('state')=='AwaitingLocalConfirmation':
                text='微信代理人工审批设置\r\n此设置不会扩大联系人或任务授权，也不会批准旧待办。\r\n'+json.dumps(value,ensure_ascii=False,indent=2)
                accepted=(confirm or native.review_windows_owner)(text,value['expires'])
                source.raw=canonical({'confirm':value['challenge_id'] if accepted else 'cancel'})+b'\n'
            else:emit(value)
        return control(connection,source,reviewed,connect=connect,owner_key=owner_key,clock=clock)
    channel=connect(connection['endpoint'],connection['server'])
    try:
        if method in ('start','approve_pending'):
            if method=='approve_pending' and (set(args)!={'job_id'} or type(args['job_id']) is not str):
                raise AXRError('wechat_owner_control_request_invalid')
            response=channel.request('WeChatOwner',method='review' if method=='start' else 'review_pending',arguments=args)
            challenge=response.get('challenge',{});authority=channel.session.authority;now=clock()
            if (type(challenge) is not dict or challenge.get('version')!=2 or type(challenge.get('version')) is not int
                or not authority or challenge.get('root_id')!=authority['root_id'] or challenge.get('epoch')!=channel.session.authority_epoch
                or type(challenge.get('expires')) not in (int,float) or not now<challenge['expires']<=now+180
                or type(challenge.get('nonce')) is not str or len(challenge['nonce'])!=64
                or any(c not in '0123456789abcdef' for c in challenge['nonce'])
                or challenge.get('kind')!=('wechat-standing-scope' if method=='start' else 'wechat-windows-pending')):
                raise AXRError('wechat_owner_control_review_invalid')
            if method=='approve_pending' and (challenge.get('job_id')!=args['job_id'] or challenge.get('review_digest')!=digest(response.get('review'))):
                raise AXRError('wechat_owner_control_review_invalid')
            review='微信代理授权审查\r\n请核对完整范围或精确内容。关闭窗口或取消不会批准。\r\n'+json.dumps(response,ensure_ascii=False,indent=2)
            if len(review.encode('utf-8'))>65536:raise AXRError('wechat_owner_review_budget')
            accepted=(confirm or native.review_windows_owner)(review,challenge['expires'])
            if not accepted:raise AXRError('wechat_owner_control_cancelled')
            if clock()>=challenge['expires']:raise AXRError('wechat_owner_control_review_expired')
            if owner_key is None:raise AXRError('wechat_owner_enrolled_key_pin_required')
            signature=owner_key().sign(canonical(challenge)).hex()
            if clock()>=challenge['expires']:raise AXRError('wechat_owner_control_review_expired')
            result=channel.request('WeChatOwner',method='activate' if method=='start' else 'approve_pending',
                arguments={'nonce':challenge['nonce'],'signature':signature})
        else:result=channel.request('WeChatOwner',method=method,arguments=args)
        emit(result);return result
    finally:channel.close()
