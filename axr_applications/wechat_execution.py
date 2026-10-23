# SPDX-License-Identifier: MIT
"""Actual helper birth binding and v2 authority bridge; no grant issuance.

The installed controller supplies a trusted enrollment/prepare callback. The
business MCP never passes a PID, executable, proof, endpoint or role. Once any
send input could reach the helper, the attempt is permanent and never retried.
"""
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import queue
import threading
import time
from axr.aet import AXRError, canonical, digest
from axr.ipc import process_identity
from .attempts import claim_attempt

class _WindowsNavigationProcess:
    """Fixed native cross-session channel; no subprocess handles are inherited."""
    stdin=stdout=None
    def __init__(self,owner_user,helper,sha,check):
        from axr import _axr_native as native
        self.channel=native.WindowsNavigation(owner_user,str(helper),sha,check)
        self.actual=json.loads(self.channel.identity);self.pid=self.actual['pid'];self.ready=False;self.closed=False
    def read_frame(self,check):
        method=self.channel.result if self.ready else self.channel.ready
        self.ready=True
        return json.loads(method(check))
    def write_frame(self,frame,check):self.channel.submit(frame.decode('utf-8'),check)
    def poll(self):return 0 if self.closed else None
    def terminate(self):
        self.channel.close();self.closed=True
    kill=terminate
    def wait(self,timeout=None):return None

class AuthorityNavigation:
    def __init__(self, helper, helper_sha256, endpoint, attempt_directory,
                 *, enroll_handler, prepare, receipt, release_handler=lambda actual:None,owner_user=None):
        self.helper=Path(helper).resolve(strict=True);self.sha=helper_sha256
        self.endpoint=str(endpoint);self.attempts=Path(attempt_directory)
        self.enroll=enroll_handler;self.prepare=prepare;self.receipt=receipt
        self.release=release_handler
        self.owner_user=owner_user
        self.attempts.mkdir(mode=0o700,parents=True,exist_ok=True)
    @staticmethod
    def _frame(process, timeout, check=lambda:None):
        if isinstance(process,_WindowsNavigationProcess):return process.read_frame(check)
        if os.name=='nt':return AuthorityNavigation._windows_frame(process,timeout,check)
        deadline=time.monotonic()+timeout;raw=bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            while time.monotonic()<deadline:
                check()
                if not selector.select(min(.05,max(.001,deadline-time.monotonic()))):continue
                chunk=os.read(process.stdout.fileno(),4096)
                if not chunk:raise AXRError('wechat_native_bridge_closed')
                raw.extend(chunk)
                if len(raw)>1024*1024:raise AXRError('wechat_native_bridge_frame_budget')
                if b'\n' in raw:
                    line,tail=raw.split(b'\n',1)
                    if tail.strip():raise AXRError('wechat_native_bridge_unsolicited_frame')
                    try:
                        value=json.loads(line)
                        if type(value) is not dict:raise ValueError()
                        return value
                    except ValueError:raise AXRError('wechat_native_bridge_protocol') from None
        raise AXRError('wechat_native_bridge_timeout')
    @staticmethod
    def _windows_frame(process, timeout, check=lambda:None):
        # Windows anonymous subprocess pipes cannot be registered with select().
        # A bounded reader thread owns this single frame; invoke() terminates the
        # child on timeout, releasing the pending read before another invocation.
        completed=queue.Queue(maxsize=1)
        def read():
            try:
                raw=bytearray()
                while True:
                    chunk=os.read(process.stdout.fileno(),4096)
                    if not chunk:raise AXRError('wechat_native_bridge_closed')
                    raw.extend(chunk)
                    if len(raw)>1024*1024:raise AXRError('wechat_native_bridge_frame_budget')
                    if b'\n' in raw:
                        line,tail=raw.split(b'\n',1)
                        if tail.strip():raise AXRError('wechat_native_bridge_unsolicited_frame')
                        try:value=json.loads(line)
                        except ValueError:raise AXRError('wechat_native_bridge_protocol') from None
                        if type(value) is not dict:raise AXRError('wechat_native_bridge_protocol')
                        completed.put((value,None));return
            except Exception as error:completed.put((None,error))
        threading.Thread(target=read,daemon=True).start()
        deadline=time.monotonic()+timeout
        while True:
            check();remaining=deadline-time.monotonic()
            if remaining<=0:raise AXRError('wechat_native_bridge_timeout')
            try:value,error=completed.get(timeout=min(.05,remaining));break
            except queue.Empty:continue
        if error:raise error
        return value
    @staticmethod
    def _write_frame(process, frame, check, timeout=5):
        if isinstance(process,_WindowsNavigationProcess):return process.write_frame(frame,check)
        completed=queue.Queue(maxsize=1)
        def write():
            try:
                pending=memoryview(frame)
                while pending:
                    written=process.stdin.write(pending)
                    if not written:raise AXRError('wechat_native_bridge_closed')
                    pending=pending[written:]
                process.stdin.close();completed.put(None)
            except Exception as error:completed.put(error)
        threading.Thread(target=write,daemon=True).start()
        deadline=time.monotonic()+timeout
        while True:
            check();remaining=deadline-time.monotonic()
            if remaining<=0:raise AXRError('wechat_native_bridge_write_timeout')
            try:error=completed.get(timeout=min(.05,remaining));break
            except queue.Empty:continue
        if error:raise error
    def _instance(self,process):
        actual=process_identity(process.pid)
        if (actual['image_sha256']!=self.sha or Path(actual['image']).resolve()!=self.helper or
                (os.name=='nt' and self.owner_user is not None and actual['user']!=self.owner_user)):
            raise AXRError('wechat_native_bridge_instance_changed')
        return actual
    @staticmethod
    def _close(process):
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for stream in (process.stdin,process.stdout):
            if stream and not stream.closed:stream.close()
    def readiness(self,executable_sha256,*,check=lambda:None):
        """Content-free pre-consent probe in the fixed owner's interactive session.

        Transport authentication permits only the fixed metadata request. It
        never enrolls a handler, prepares a proof, claims a task or reads text.
        Ordinary subprocess/stdin fallback is deliberately unavailable.
        """
        if os.name!='nt' or self.owner_user is None:raise AXRError('wechat_interactive_owner_user_required')
        if (type(executable_sha256) is not str or len(executable_sha256)!=64 or
                any(ch not in '0123456789abcdef' for ch in executable_sha256)):
            raise AXRError('wechat_readiness_executable_pin_required')
        check()
        if hashlib.sha256(self.helper.read_bytes()).hexdigest()!=self.sha:raise AXRError('wechat_native_bridge_build_changed')
        process=_WindowsNavigationProcess(self.owner_user,self.helper,self.sha,check)
        try:
            if self._frame(process,5,check)!={'version':2,'ready':True,'input_received':False}:
                raise AXRError('wechat_native_bridge_ready_required')
            actual=self._instance(process)
            request={'mode':'readiness','executable_hash':executable_sha256}
            check()
            if process_identity(process.pid)!=actual:raise AXRError('wechat_native_bridge_instance_changed')
            self._write_frame(process,canonical(request)+b'\n',check)
            result=self._frame(process,15,check);check()
            fields={'running','ambiguous_process','accessibility','send_invoked','content_disclosed'}
            if (type(result) is not dict or set(result)!=fields or any(type(value) is not bool for value in result.values()) or
                    result['send_invoked'] or result['content_disclosed'] or
                    (result['accessibility'] and (not result['running'] or result['ambiguous_process']))):
                raise AXRError('wechat_readiness_metadata_required')
            return result
        finally:self._close(process)
    def invoke(self, action, *, check):
        mode=action.payload.get('mode');operations={'binding':'status.read','navigate':'application.navigate','stage_draft':'application.draft','read_draft':'messages.read','send':'messages.send'}
        if os.name=='nt':operations['read_draft']='status.read' # Local comparison metadata; keep DB read handler distinct.
        if mode not in operations or action.operation!=operations[mode]:raise AXRError('wechat_native_bridge_operation_mismatch')
        check()
        if hashlib.sha256(self.helper.read_bytes()).hexdigest()!=self.sha:raise AXRError('wechat_native_bridge_build_changed')
        marker=self.attempts/('send-'+digest([action.resource.key,action.execution_id])+'.json')
        if mode=='send' and (marker.exists() or marker.is_symlink()):raise AXRError('previous_attempt_never_retry')
        if os.name=='nt' and self.owner_user is not None:
            process=_WindowsNavigationProcess(self.owner_user,self.helper,self.sha,check)
        else:
            if os.name=='nt' and process_identity(os.getpid())['user']=='S-1-5-18':
                raise AXRError('wechat_interactive_owner_user_required')
            process=subprocess.Popen([str(self.helper),'--authority-v2'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,bufsize=0,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        proof=None;submitted=False;actual=None
        try:
            if self._frame(process,5,check)!={'version':2,'ready':True,'input_received':False}:raise AXRError('wechat_native_bridge_ready_required')
            actual=self._instance(process)
            # These callbacks are installed root code, never MCP parameters.
            self.enroll(actual)
            proof=self.prepare(action,actual)
            if proof['body']['helper_pid']!=actual['pid'] or proof['body']['helper_birth']!=actual['birth'] or proof['body']['seal']!=action.seal:raise AXRError('wechat_native_bridge_proof_changed')
            request={'mode':mode,'operation':action.operation,'expected_text':action.payload['text'],
                'account':action.resource.account_id,'identity':action.resource.conversation_id,
                'visual_binding':action.payload['visual_binding'],
                'guard_context':{'authority_endpoint':self.endpoint,'proof':canonical(proof).decode()}}
            if mode=='navigate' and 'phase' in action.payload.get('navigation_binding',{}):
                request['navigation_phase']=action.payload['navigation_binding']['phase']
            frame=canonical(request)+b'\n'
            if len(frame)>1024*1024:raise AXRError('wechat_native_bridge_frame_budget')
            check()
            if process_identity(process.pid)!=actual:raise AXRError('wechat_native_bridge_instance_changed')
            if mode=='send':claim_attempt(marker)
            # Any loss from this point on is conservatively Unknown for sends.
            submitted=True
            self._write_frame(process,frame,check)
            result=self._frame(process,15,check);process.wait(timeout=2);check()
            state=self.receipt(action.execution_id)
            return {'receipt':state,'native':result,'retry':False,'delivery_confirmed':False}
        except Exception:
            # Never guess send_invoked=false when the response was lost.
            if submitted and mode=='send':return {'receipt':{'state':'Unknown','execution_id':action.execution_id},'native':None,'retry':False,'delivery_confirmed':False}
            raise
        finally:
            self._close(process)
            if actual is not None:self.release(actual)
