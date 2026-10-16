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
import subprocess
import signal
import sys
from pathlib import Path
from axr.aet import AXRError, canonical, digest
from axr.host import Lease
from axr.storage import private_directory
from .lifecycle import DeferredService

MAX_PACKET = 1024 * 1024
METHODS = frozenset({'status','conversations','navigate','read','read_attachment','disclose','prepare',
    'find_attachments','poll_tasks','request_task','wait_tasks','task_context','finish_task','observe_manual_reply',
    'submit_reply_task','acknowledge_review','propose_send','observe_send_record','execute','receipt','cancel_job',
    'simulate','write_workspace','run_batch','read_all','assistant_profile','request_authorization','authorization_status'})
CONTROL = frozenset({'snapshot','review','approve','revoke_all','draft','summaries','grant_local','configure_cache','start_automatic','stop_automatic','assistant_settings','save_assistant_settings','codex_threads','install_hooks','codex_lifecycle','approve_authorization'})


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
    def __init__(self,state,*,helper=None,manual_replies=True,service=None,chat_helper=None):
        self.state=Path(state).resolve();self.helper=helper;self.chat_helper=chat_helper
        self.service=service or DeferredService(self.state,manual_replies=manual_replies)
        self.root=private_directory(runtime_directory(state))
        self.lease=Lease(self.root,['desktop-broker',str(self.state)])
        self.lease.__enter__()
        self.tokens={'client':secrets.token_hex(32),'owner':secrets.token_hex(32)}
        self.epoch=secrets.token_hex(16);self.gate=threading.BoundedSemaphore(12)
        self.control_lock=threading.RLock();self.automatic_worker=None;self.worker_hook_token=None
        from .thread_router import ThreadRouter
        self.router=ThreadRouter(self);self.router_stop=threading.Event();self.router_thread=None
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
            if method[8:]=='codex_lifecycle':
                # Hooks have a short deadline and carry metadata only. Do not
                # queue a user's priority/Stop event behind database or GUI work.
                return self.router.event(*args,**kwargs)
            if method[8:] in {'approve','grant_local','configure_cache','start_automatic','approve_authorization'}:
                return self.authenticated_control(method[8:],*args,**kwargs)
            if method[8:] in {'stop_automatic','revoke_all'}:
                active=getattr(self.service,'_delegate',None)
                if active:active.stop_automatic()
                self.stop_worker()
                if method[8:]=='stop_automatic':return {'stopped':True,'retry':False}
            with self.control_lock:return self.control(method[8:],*args,**kwargs)
        if method not in METHODS:raise AXRError('broker_method_not_exposed')
        if method=='wait_tasks':
            with self.control_lock:fn=getattr(self.service,method);inspect.signature(fn).bind(*args,**kwargs)
            return fn(*args,**kwargs)
        with self.control_lock:
            fn=getattr(self.service,method);inspect.signature(fn).bind(*args,**kwargs)
            result=fn(*args,**kwargs)
            return self.capabilities(result) if method=='status' else result

    def capabilities(self,status):
        supported=(sys.platform=='darwin' and bool(self.chat_helper) and Path(self.chat_helper).is_file() and
                   status.get('platform',{}).get('mode')=='wcdb')
        return {**status,'automatic_reply':{**status.get('automatic_reply',{}),'supported':supported}}

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
                elif method=='start_automatic':
                    from .automatic_reply import validate_scope
                    targets,ttl,replies=args
                    from .assistant_settings import load
                    preferences=load(service.store)
                    if (ttl==0 or replies==0) and not preferences['thread_id']:raise AXRError('unlimited_requires_bound_codex_thread')
                    all_users=targets==['*']
                    helper=validate_scope(service,list(service.bindings)[:2] if all_users else targets,ttl,replies,self.chat_helper)
                    helper_seal=digest(helper.read_bytes().hex())
                elif method=='approve_authorization':
                    from .authorization_requests import list_requests
                    key,=args
                    authorization=next((v for v in list_requests(service) if v['id']==key and v['state']=='AwaitingOwner'),None)
                    if not authorization:raise AXRError('authorization_request_missing_or_expired')
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
                if method=='start_automatic':
                    if digest(helper.read_bytes().hex())!=helper_seal:raise AXRError('native_helper_changed')
                    self.stop_worker()
                    if all_users:
                        from .authorization_requests import catalog,add_bindings
                        found=catalog(service);add_bindings(service,found);targets=[b['conversation_id'] for b in found]
                    status=service.start_automatic(targets,ttl,replies,helper)
                    service.automatic.all_users=all_users
                    from .assistant_settings import load
                    preferences=load(service.store);service.automatic.preferences=preferences
                    self.router.bind(preferences['thread_id'])
                    try:
                        if not preferences['thread_id']:self.start_worker(ttl or 3600)
                        self.start_router()
                    except Exception:
                        service.stop_automatic();raise AXRError('automatic_reply_worker_start_failed') from None
                    return status
                if method=='approve_authorization':
                    from .owner_codex import qualify_existing_contacts
                    from .authorization_requests import add_bindings
                    found=qualify_existing_contacts(service.store,policy,[authorization['target']]);add_bindings(service,found)
                    cid=found[0]['conversation_id']
                    if service.automatic and service.automatic.status()['active']:
                        auto=service.automatic;auto.targets=tuple(dict.fromkeys([*auto.targets,cid]))
                        auto.policy={**auto.policy,'conversations':[service.bindings[c] for c in auto.targets]};auto.ensure_access(cid)
                    else:
                        service.guard._issue_owner(principal=service.principal,resource=service.resource(cid),
                            operations=['messages.read','messages.search','reply.prepare'],purpose=service.purpose,
                            expires_at=service.journal.clock()+900,max_uses=400,classes=['personal'])
                    service.journal.db.execute("UPDATE authorization_requests SET state='Approved' WHERE id=? AND principal=?",(key,service.principal))
                    return {'approved':True,'authority_granted':True}
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
            if method=='assistant_settings':
                from .assistant_settings import load
                return load(service.store)
            if method=='save_assistant_settings':
                if service.automatic and service.automatic.status()['active']:raise AXRError('stop_automatic_before_settings_change')
                from .assistant_settings import save
                value=save(service.store,args[0]);self.router.bind(value['thread_id']);return {'saved':True}
            if method=='codex_threads':
                from .codex_bridge import threads
                return threads(*args)
            if method=='install_hooks':
                from .thread_router import install_hooks
                return install_hooks(self.state,Path(__file__).resolve().parents[1],sys.executable)
            if method=='codex_lifecycle':
                return self.router.event(*args)
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
                return {'status':self.capabilities(service.status()),'jobs':jobs,'drafts':list_drafts(service.store),
                        'grants':grants,'conversations':[{'conversation_id':b['conversation_id'],'display_name':b['display_name'],
                        'data_class':b.get('data_class','personal')} for b in service.bindings.values()],
                        'attachments':{'enabled':service.config.get('attachments',{}).get('enabled',False)},
                        'thread_binding':self.router.status(),
                        'authorization_requests':__import__('axr_integration.authorization_requests',fromlist=['list_requests']).list_requests(service),
                        'automatic_worker':{'running':self.automatic_worker is not None and self.automatic_worker.poll() is None},
                        'scope':'work_and_daily_assistance'}
        raise AXRError('broker_control_not_exposed')

    def start_worker(self,duration,thread_id=None):
        command=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/run_codex_manual.py'),
            '--state',str(self.state),'--broker','--automatic','--duration',str(duration)]
        if thread_id:command+=['--thread',thread_id]
        self.worker_hook_token=secrets.token_hex(32)
        env={**os.environ,'AXR_CODEX_WORKER_HOOK_TOKEN':self.worker_hook_token}
        self.automatic_worker=subprocess.Popen(command,cwd=str(Path(__file__).resolve().parents[1]),env=env,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)

    def start_router(self):
        if self.router_thread and self.router_thread.is_alive():return
        def loop():
            while not self.router_stop.wait(1):
                try:
                    if self.automatic_worker is not None and self.automatic_worker.poll() is not None:self.router.worker_finished()
                    self.router.schedule()
                except Exception:pass
        self.router_thread=threading.Thread(target=loop,daemon=True);self.router_thread.start()

    def stop_worker(self):
        process=self.automatic_worker
        if process is not None and process.poll() is None:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass

    def serve(self):self.server.serve_forever(poll_interval=0.2)
    def close(self):
        self.router_stop.set()
        self.stop_worker()
        if self.router_thread and self.router_thread is not threading.current_thread():self.router_thread.join(timeout=2)
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
    parser.add_argument('--chat-helper',help='Owner-installed bounded macOS main-window sender')
    parser.add_argument('--allow-approved-sends',action='store_true')
    parser.add_argument('--listener',action='store_true')
    args=parser.parse_args()
    broker=Broker(args.state,helper=args.helper,manual_replies=not args.allow_approved_sends,chat_helper=args.chat_helper)
    if args.listener:broker.service.start_listener()
    try:broker.serve()
    except KeyboardInterrupt:pass
    finally:broker.close()


if __name__=='__main__':main()
