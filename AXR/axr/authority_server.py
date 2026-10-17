# SPDX-License-Identifier: AGPL-3.0-only
"""Local authority transport, separate from business MCP and model workers.

This server accepts only owner-enrolled native peers. Endpoint discovery is not
trust: clients must obtain the exact server identity from trusted installation.
No command, shell, secret export, policy path or self-declared role is accepted.
"""
import os,socket,threading,time
from pathlib import Path
from .aet import AXRError
from .ipc import SecureSession,SocketTransport,PipeTransport,create_pipe

class AuthorityServer:
    def __init__(self,kernel,registry,endpoint,*,maximum_connections=16):
        if registry.development_fixture!=kernel.development_fixture:raise AXRError('authority_profile_mismatch')
        self.kernel=kernel;self.registry=registry;self.endpoint=str(endpoint)
        self.stop_event=threading.Event();self.slots=threading.BoundedSemaphore(maximum_connections)
        self.sessions=set();self.lock=threading.Lock();self.listener=None;self.inode=None;self.windows_thread=None
    def _serve(self,transport):
        session=None
        try:
            session=SecureSession.server_handshake(transport,self.registry,self.kernel.epoch,authority={'public_key':self.kernel.root_public_key.hex(),'root_id':self.kernel.root_id})
            with self.lock:self.sessions.add(session)
            window=time.monotonic();count=0
            while not self.stop_event.is_set():
                packet=session.receive()
                if self.registry.accept(session.identity)!=session.peer:raise AXRError('ipc_peer_enrollment_revoked')
                now=time.monotonic()
                if now-window>=1:window=now;count=0
                count+=1
                if count>32:raise AXRError('authority_connection_rate_limited')
                try:result={'ok':True,'result':self.kernel.dispatch(session.peer,packet)}
                except AXRError as exc:
                    code=str(exc)
                    if len(code)>100 or not all(c.isalnum() or c=='_' for c in code):code='authority_request_denied'
                    result={'ok':False,'error':code}
                except Exception:result={'ok':False,'error':'authority_request_invalid'}
                session.send(result)
        except Exception:pass # No message/credential body ever enters diagnostic logs.
        finally:
            if session:
                with self.lock:self.sessions.discard(session)
                session.close()
            else:transport.close()
            self.slots.release()
    def serve(self):
        if os.name=='nt':return self._windows()
        path=Path(self.endpoint)
        if len(os.fsencode(path))>100:raise AXRError('authority_socket_path_too_long')
        parent=path.parent
        st=parent.lstat()
        if parent.is_symlink() or st.st_uid!=os.getuid() or st.st_mode&0o077:raise AXRError('authority_endpoint_directory_not_private')
        if path.exists() or path.is_symlink():raise AXRError('authority_endpoint_already_exists')
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.listener=listener
        listener.bind(str(path));os.chmod(path,0o600);self.inode=path.lstat().st_ino
        listener.listen(16);listener.settimeout(.5)
        try:
            while not self.stop_event.is_set():
                try:sock,_=listener.accept()
                except socket.timeout:continue
                except OSError:
                    if self.stop_event.is_set():break
                    raise
                sock.settimeout(10)
                if not self.slots.acquire(False):sock.close();continue
                threading.Thread(target=self._serve,args=(SocketTransport(sock),),daemon=True).start()
        finally:
            listener.close()
            if path.exists() and not path.is_symlink() and path.lstat().st_ino==self.inode:path.unlink()
    def _windows(self):
        import win32api,win32pipe,pywintypes
        thread=win32api.OpenThread(0x0001,False,threading.get_native_id()) # THREAD_TERMINATE for CancelSynchronousIo
        with self.lock:self.windows_thread=thread
        try:
            while not self.stop_event.is_set():
                listener=create_pipe(self.endpoint,(self.registry.user,));self.listener=listener
                try:
                    if self.stop_event.is_set():listener.Close();break
                    try:win32pipe.ConnectNamedPipe(listener,None)
                    except pywintypes.error as exc:
                        if exc.winerror!=535:raise
                    if self.stop_event.is_set():listener.Close();break
                    if not self.slots.acquire(False):listener.Close();continue
                    # FIRST_PIPE_INSTANCE intentionally permits one live pipe;
                    # handle this connection before accepting a replacement.
                    self._serve(PipeTransport(listener))
                except Exception:
                    listener.Close()
                    if not self.stop_event.is_set():raise
        finally:
            with self.lock:self.windows_thread=None;thread.Close()
    def close(self):
        self.stop_event.set()
        if os.name=='nt':
            import ctypes,win32file,win32con
            # Closing a handle from another thread can wait forever on its
            # synchronous ConnectNamedPipe/ReadFile. Cancel the serving thread's
            # pending I/O; that thread owns transport cleanup.
            with self.lock:
                if self.windows_thread:
                    cancel=ctypes.WinDLL('kernel32',use_last_error=True).CancelSynchronousIo
                    cancel.argtypes=[ctypes.c_void_p];cancel.restype=ctypes.c_int
                    cancel(int(self.windows_thread))
            # Covers cancellation racing just before ConnectNamedPipe starts.
            # No data is sent and anonymous SQOS denies impersonation.
            try:
                wake=win32file.CreateFile(self.endpoint,win32con.GENERIC_READ|win32con.GENERIC_WRITE,
                    0,None,win32con.OPEN_EXISTING,0x00100000,None)
                wake.Close()
            except Exception:pass
            return
        with self.lock:sessions=list(self.sessions)
        for session in sessions:session.close()
        if self.listener:
            try:self.listener.close() if os.name!='nt' else self.listener.Close()
            except Exception:pass

class AuthorityClient:
    def __init__(self,session):self.session=session;self.lock=threading.RLock()
    @classmethod
    def connect(cls,endpoint,expected_server):
        if os.name=='nt':
            import win32file,win32pipe,win32con
            handle=win32file.CreateFile(str(endpoint),win32con.GENERIC_READ|win32con.GENERIC_WRITE,0,None,win32con.OPEN_EXISTING,0x00100000|0x00010000,None)
            win32pipe.SetNamedPipeHandleState(handle,win32pipe.PIPE_READMODE_MESSAGE,None,None)
            transport=PipeTransport(handle)
        else:
            sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.settimeout(10);sock.connect(str(endpoint));transport=SocketTransport(sock)
        return cls(SecureSession.client_handshake(transport,expected_server))
    def request(self,operation,**payload):
        with self.lock:
            self.session.send({'operation':operation,'payload':payload});reply=self.session.receive()
            if type(reply) is not dict or reply.get('ok') is not True:raise AXRError(reply.get('error','authority_response_invalid') if isinstance(reply,dict) else 'authority_response_invalid')
            return reply['result']
    def close(self):self.session.close()
