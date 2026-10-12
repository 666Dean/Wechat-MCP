# SPDX-License-Identifier: MIT
"""One local execution authority, authenticated loopback clients and owner control."""
import argparse
import hmac
import inspect
import json
import os
import secrets
import socket
import socketserver
import threading
from pathlib import Path
from axr.aet import AXRError, canonical, digest
from axr.host import Lease
from axr.storage import private_directory
from .lifecycle import DeferredService

MAX_PACKET = 1024 * 1024
METHODS = frozenset({'status','conversations','navigate','read','read_attachment','disclose','prepare',
    'find_attachments','poll_tasks','request_task','wait_tasks','task_context','finish_task','observe_manual_reply',
    'submit_reply_task','acknowledge_review','propose_send','observe_send_record','execute','receipt','cancel_job',
    'simulate','write_workspace','run_batch','read_all'})
CONTROL = frozenset({'snapshot','review','approve','revoke_all','draft','summaries','grant_local','configure_cache'})


def runtime_directory(state):
    return Path(state).resolve()/'desktop-runtime'


def read_connection(state, owner=False):
    root=runtime_directory(state)
    path=root/('owner.json' if owner else 'client.json')
    if path.is_symlink() or path.stat().st_size>4096:
        raise AXRError('broker_connection_invalid')
    if os.name!='nt' and path.stat().st_mode & 0o077:
        raise AXRError('broker_connection_not_private')
    data=json.loads(path.read_bytes())
    if (data.get('host')!='127.0.0.1' or type(data.get('port')) is not int or
            not 1<=data['port']<=65535 or len(data.get('token',''))!=64):
        raise AXRError('broker_connection_invalid')
    return data


def call(state, method, args=(), kwargs=None, *, owner=False, timeout=50):
    try:
        connection=read_connection(state,owner)
        request=canonical({'token':connection['token'],'epoch':connection['epoch'],
                           'method':method,'args':list(args),'kwargs':kwargs or {}})+b'\n'
        if len(request)>MAX_PACKET:raise AXRError('broker_request_budget')
        with socket.create_connection((connection['host'],connection['port']),timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(request)
            with sock.makefile('rb') as stream:raw=stream.readline(MAX_PACKET+1)
        if len(raw)>MAX_PACKET or not raw.endswith(b'\n'):raise AXRError('broker_response_budget')
        response=json.loads(raw)
        if response.get('error'):raise AXRError(response['error'])
        return response['result']
    except AXRError:raise
    except Exception as exc:raise AXRError('local_broker_unavailable') from exc


class RemoteService:
    """Pure client: never opens a journal, keychain or adapter."""
    def __init__(self,state):self.state=state
    def __getattr__(self,name):
        if name not in METHODS:raise AttributeError(name)
        return lambda *args,**kwargs:call(self.state,name,args,kwargs)
    def status(self):
        try:return call(self.state,'status')
        except AXRError:return {'axr':True,'initialization':{'state':'broker_unavailable','operational':False},
                              'send_available':False,'body_disclosed':False,'unknown_retry':False}
    def close(self):pass


class Broker:
    def __init__(self,state,*,helper=None,manual_replies=True,service=None):
        self.state=Path(state).resolve();self.helper=helper
        self.service=service or DeferredService(self.state,manual_replies=manual_replies)
        self.root=private_directory(runtime_directory(state))
        self.lease=Lease(self.root,['desktop-broker',str(self.state)])
        self.lease.__enter__()
        self.tokens={'client':secrets.token_hex(32),'owner':secrets.token_hex(32)}
        self.epoch=secrets.token_hex(16);self.gate=threading.BoundedSemaphore(12)
        self.control_lock=threading.RLock()
        broker=self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(50)
                if not broker.gate.acquire(blocking=False):return
                try:
                    raw=self.rfile.readline(MAX_PACKET+1)
                    if len(raw)>MAX_PACKET or not raw.endswith(b'\n'):raise AXRError('broker_request_budget')
                    request=json.loads(raw)
                    owner=hmac.compare_digest(str(request.get('token','')),broker.tokens['owner'])
                    if (not owner and not hmac.compare_digest(str(request.get('token','')),broker.tokens['client'])) or request.get('epoch')!=broker.epoch:
                        raise AXRError('broker_authentication_failed')
                    result=broker.dispatch(request,owner)
                    response=canonical({'result':result})+b'\n'
                    if len(response)>MAX_PACKET:raise AXRError('broker_response_budget')
                except AXRError as exc:
                    # AXR errors are fixed codes; never forward arbitrary parser exceptions.
                    value=str(exc)
                    if not value.replace('_','').isalnum() or len(value)>100:value='broker_operation_failed_safe'
                    response=canonical({'error':value})+b'\n'
                except Exception:response=b'{"error":"broker_operation_failed_safe"}\n'
                finally:broker.gate.release()
                try:self.wfile.write(response)
                except OSError:pass
        class Server(socketserver.ThreadingTCPServer):
            daemon_threads=True
            block_on_close=False
            allow_reuse_address=False
        try:
            self.server=Server(('127.0.0.1',0),Handler)
            for role,token in self.tokens.items():
                data=canonical({'host':'127.0.0.1','port':self.server.server_address[1],
                                'token':token,'epoch':self.epoch})
                path=self.root/(role+'.json')
                if path.is_symlink():raise AXRError('broker_connection_link_rejected')
                descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                with os.fdopen(descriptor,'wb') as stream:stream.write(data)
                if os.name!='nt':path.chmod(0o600)
        except BaseException:self.lease.__exit__();raise

    def dispatch(self,request,owner):
        method=request.get('method');args=request.get('args',[]);kwargs=request.get('kwargs',{})
        if type(args) is not list or type(kwargs) is not dict:raise AXRError('broker_arguments_invalid')
        if method.startswith('control.'):
            if not owner or method[8:] not in CONTROL:raise AXRError('broker_owner_channel_required')
            if method[8:] in {'approve','grant_local','configure_cache'}:
                return self.authenticated_control(method[8:],*args,**kwargs)
            with self.control_lock:return self.control(method[8:],*args,**kwargs)
        if method not in METHODS:raise AXRError('broker_method_not_exposed')
        if method=='wait_tasks':
            with self.control_lock:fn=getattr(self.service,method);inspect.signature(fn).bind(*args,**kwargs)
            return fn(*args,**kwargs)
        with self.control_lock:
            fn=getattr(self.service,method);inspect.signature(fn).bind(*args,**kwargs)
            return fn(*args,**kwargs)

    def authenticated_control(self,method,*args,**kwargs):
        from axr.host import Supervisor
        from axr.owner import approve,review
        from .policy import validate_controls
        if kwargs:raise AXRError('owner_control_positional_arguments_required')
        if not self.helper:raise AXRError('owner_helper_required')
        with self.control_lock:
            service=self.service._active()
            with service.runtime.lock:
                service.ensure_policy();version=service.guard.version;policy=service.store.config();policy_seal=digest(policy)
                if method=='approve':
                    jid,seal=args
                    if review(service.store,jid,service.principal)['seal']!=seal:raise AXRError('review_intent_changed')
                elif method=='grant_local':
                    cid,ttl=args
                    if cid not in service.bindings or type(ttl) is not int or not 60<=ttl<=3600:
                        raise AXRError('owner_local_grant_scope_invalid')
                elif method=='configure_cache':
                    root=Path(args[0])
                    if len(args)!=1 or not root.is_absolute() or root.is_symlink() or not root.is_dir() or root.resolve()!=root:
                        raise AXRError('attachment_cache_root_not_canonical')
                else:raise AXRError('broker_control_not_exposed')
        # Release the request gate during OS authentication. Emergency revocation
        # and status must remain available, and pending auth cannot revive grants.
        result=Supervisor(timeout=65).invoke([str(Path(self.helper).resolve(strict=True))],{'op':'owner_auth'})['result']
        if result.get('verified') is not True:raise AXRError('owner_os_authentication_failed')
        with self.control_lock:
            if getattr(self.service,'_delegate',None) is not service:
                raise AXRError('owner_runtime_changed_review_again')
            with service.runtime.lock:
                if service.guard.version!=version or digest(service.store.config())!=policy_seal:
                    raise AXRError('owner_policy_changed_review_again')
                service.ensure_policy()
                if method=='approve':
                    if review(service.store,jid,service.principal)['seal']!=seal:raise AXRError('review_intent_changed')
                    approve(service.store,jid,service.principal)
                    return {'approved':True,'job_id':jid}
                if method=='grant_local':
                    binding=service.bindings[cid];operations=['messages.read','messages.search','reply.prepare']
                    if policy.get('attachments',{}).get('enabled'):operations+=['files.read']
                    grant=service.guard._issue_owner(principal=service.principal,resource=service.resource(cid),
                        operations=operations,purpose=service.purpose,expires_at=service.journal.clock()+ttl,
                        max_uses=100,classes=[binding.get('data_class','personal')])
                    return {'grant_id':grant,'ttl':ttl,'uses':100,'model_disclosure':False,'send':False}
                policy['attachments']={'enabled':True,'cache_roots':[str(root)]};validate_controls(policy)
                service.guard.revoke_owner('desktop-cache-configuration');service.store.seal_config(policy)
            self.service.close()
            return {'configured':True,'previous_authority_revoked':True}

    def control(self,method,*args,**kwargs):
        service=self.service._active()
        with service.runtime.lock:
            if method=='review':
                from axr.owner import review
                value=review(service.store,args[0],service.principal)
                value['expires']=service.journal.get(args[0],service.principal)['expires']
                return value
            if method=='draft':
                from .manual_reply import review_draft
                return review_draft(service.store,args[0])
            if method=='revoke_all':
                service.stop_event.set();service.guard.revoke_owner('desktop-emergency-stop')
                policy=service.store.config()
                policy.setdefault('listener',{}).update(listen=False,wake_agent=False,auto_execute=False)
                service.store.seal_config(policy)
                return {'revoked':True,'restart_required':True}
            if method=='summaries':
                rows=service.journal.db.execute('SELECT id,payload FROM review_notes WHERE principal=? AND version=? AND expires>? ORDER BY rowid DESC LIMIT 50',
                    (service.principal,service.guard.version,service.journal.clock())).fetchall()
                return {'summaries':[service.store.vault.open(r['payload'],r['id']+':review') for r in rows]}
            if method=='snapshot':
                from .manual_reply import list_drafts
                rows=service.journal.db.execute('SELECT id,state,created,expires FROM jobs WHERE principal=? ORDER BY created DESC LIMIT 80',
                    (service.principal,)).fetchall()
                jobs=[]
                for row in rows:
                    item=dict(row)
                    try:
                        action=service.journal.action(service.journal.get(item['id'],service.principal))
                        item.update(operation=action.operation,target=service.bindings[action.resource.conversation_id]['display_name'])
                    except Exception:item.update(operation='expired',target='')
                    jobs.append(item)
                import sqlite3
                with sqlite3.connect(Path(service.guard.path).resolve().as_uri()+'?mode=ro',uri=True) as observer:
                    rows=observer.execute('SELECT id,body,used,revoked FROM grants ORDER BY rowid DESC LIMIT 100').fetchall()
                grants=[]
                for gid,body,used,revoked in rows:
                    body=json.loads(body)
                    if body['principal']!=service.principal or revoked or body['policy_version']!=service.guard.version or body['expires_at']<=service.journal.clock():continue
                    grants.append({'id':gid,'conversation_id':body['resource']['conversation_id'],'operations':body['operations'],'expires':body['expires_at'],
                                   'remaining':max(0,body['max_uses']-used),'classes':body['classes'],
                                   'destinations':body['destinations'],'exact_intent':body['intent'] is not None})
                return {'status':service.status(),'jobs':jobs,'drafts':list_drafts(service.store),
                        'grants':grants,'conversations':[{'conversation_id':b['conversation_id'],'display_name':b['display_name'],
                        'data_class':b.get('data_class','personal')} for b in service.bindings.values()],
                        'attachments':{'enabled':service.config.get('attachments',{}).get('enabled',False)},
                        'scope':'work_and_daily_assistance'}
        raise AXRError('broker_control_not_exposed')

    def serve(self):self.server.serve_forever(poll_interval=0.2)
    def close(self):
        self.server.server_close()
        with self.control_lock:self.service.close()
        for role in self.tokens:
            path=self.root/(role+'.json')
            if path.exists() and not path.is_symlink():
                try:
                    if json.loads(path.read_bytes()).get('epoch')==self.epoch:path.unlink()
                except Exception:pass
        self.lease.__exit__()


def main():
    parser=argparse.ArgumentParser(description='WeChat MCP local single-authority broker')
    parser.add_argument('--state',required=True);parser.add_argument('--helper')
    parser.add_argument('--allow-approved-sends',action='store_true')
    parser.add_argument('--listener',action='store_true')
    args=parser.parse_args()
    broker=Broker(args.state,helper=args.helper,manual_replies=not args.allow_approved_sends)
    if args.listener:broker.service.start_listener()
    try:broker.serve()
    except KeyboardInterrupt:pass
    finally:broker.close()


if __name__=='__main__':main()
