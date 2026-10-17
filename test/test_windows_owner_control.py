# SPDX-License-Identifier: MIT
"""Owner control with real challenge signatures; no device keys or WeChat data."""
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from axr.aet import AXRError, canonical
from axr.authority_server import AuthorityServer
from axr.ipc import PeerRegistry, process_identity
from axr_applications.windows_owner import control, frame
from axr_integration.authority_frontend import load_connection
from test.test_authority_mcp import application_fixture


class LocalInput:
    def __init__(self,required,*,cancel=False):
        self.next=canonical({'operation':'set-manual-approval','manual_approval_required':required})+b'\n'
        self.cancel=cancel
        self.outputs=[]
    def readline(self,maximum):
        value,self.next=self.next,b''
        return value[:maximum]
    def emit(self,value):
        self.outputs.append(value)
        if value['state']=='AwaitingLocalConfirmation':
            self.next=canonical({'confirm':'cancel' if self.cancel else value['challenge_id']})+b'\n'


class OwnerControl(unittest.TestCase):
    def setUp(self):
        self.f=application_fixture()
        self.addCleanup(self.f.doCleanups)
        self.channels=[]
        self.signers=[]
    def connect(self,*args):
        fixture=self.f
        class Channel:
            session=SimpleNamespace(authority={'root_id':fixture.k.root_id},authority_epoch=fixture.k.epoch)
            closed=False
            def request(channel,operation,**payload):
                return fixture.call(fixture.owner,operation,**payload)
            def close(channel):channel.closed=True
        value=Channel()
        self.channels.append(value)
        return value
    def key(self):
        self.signers.append(True)
        return self.f.ownerkey
    def run_control(self,source,**options):
        return control({'endpoint':'unused','server':{}},source,source.emit,
                       connect=self.connect,owner_key=self.key,**options)
    def test_exact_local_review_and_signed_setting_changes_in_both_directions(self):
        for generation,required in enumerate((False,True),1):
            source=LocalInput(required)
            result=self.run_control(source)
            self.assertIs(result['manual_approval_required'],required)
            self.assertEqual(result['generation'],generation)
            self.assertEqual([item['state'] for item in source.outputs],['AwaitingLocalConfirmation','Completed'])
        self.assertEqual(self.f.saved_settings,[(False,1),(True,2)])
        self.assertTrue(all(channel.closed for channel in self.channels))
    def test_cancellation_never_opens_signing_key_or_changes_setting(self):
        with self.assertRaisesRegex(AXRError,'cancelled'):
            self.run_control(LocalInput(False,cancel=True))
        self.assertEqual(self.signers,[])
        self.assertEqual(self.f.saved_settings,[])
        self.assertTrue(self.channels[0].closed)
    def test_wrong_service_epoch_is_rejected_before_local_confirmation(self):
        original=self.connect
        def changed(*args):
            channel=original(*args)
            channel.session=SimpleNamespace(authority={'root_id':self.f.k.root_id},authority_epoch='other')
            return channel
        self.connect=changed
        source=LocalInput(False)
        with self.assertRaisesRegex(AXRError,'review_invalid'):self.run_control(source)
        self.assertEqual(source.outputs,[])
        self.assertEqual(self.signers,[])
    def test_expiry_after_local_confirmation_never_opens_key(self):
        now=time.time()+1
        clock=iter((now,now+120))
        with self.assertRaisesRegex(AXRError,'review_expired'):
            self.run_control(LocalInput(False),clock=lambda:next(clock))
        self.assertEqual(self.signers,[])
        self.assertEqual(self.f.saved_settings,[])
    def test_invalid_frames_or_model_style_payload_never_connect(self):
        for raw in (b'{}',b'{"x":1,"x":2}\n',b'[]\n',b'x'*32769):
            with self.subTest(raw=raw[:20]), self.assertRaises(AXRError):frame(io.BytesIO(raw))
        for request in ({'operation':'set-manual-approval','manual_approval_required':'false'},
                        {'operation':'set-manual-approval','manual_approval_required':False,'endpoint':'untrusted'}):
            source=LocalInput(False)
            source.next=canonical(request)+b'\n'
            with self.assertRaisesRegex(AXRError,'request_invalid'):self.run_control(source)
        self.assertEqual(self.channels,[])

    def test_unavailable_presence_provider_does_not_change_setting(self):
        def unavailable():raise RuntimeError('windows_owner_presence_key_requires_enrolled_hello_provider')
        source=LocalInput(False)
        with self.assertRaisesRegex(RuntimeError,'enrolled_hello_provider'):
            control({'endpoint':'unused','server':{}},source,source.emit,
                    connect=self.connect,owner_key=unavailable)
        self.assertEqual(self.f.saved_settings,[])
        self.assertIs(self.f.application.manual_approval_required,True)
        self.assertTrue(self.channels[0].closed)

    @unittest.skipUnless(sys.platform=='win32','Windows owner named pipe')
    def test_signed_control_over_real_os_authenticated_owner_pipe(self):
        actual=process_identity(os.getpid())
        registry=PeerRegistry(self.f.store,development_fixture=True)
        registry.enroll(actual,'owner',self.f.owner.principal,lambda:actual['user'])
        self.f.k.integrity.persist()
        endpoint=r'\\.\pipe\Stellaria.AXR.owner-fixture.'+secrets.token_hex(12)
        server=AuthorityServer(self.f.k,registry,endpoint)
        thread=threading.Thread(target=server.serve,daemon=True)
        thread.start()
        try:
            deadline=time.monotonic()+3
            while server.listener is None:
                if not thread.is_alive() or time.monotonic()>deadline:self.fail('owner fixture listener failed')
                time.sleep(.01)
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'owner-connection.json'
                path.write_bytes(canonical({'version':2,'endpoint':endpoint,'server':actual}))
                connection=load_connection(path)
                source=LocalInput(False)
                result=control(connection,source,source.emit,owner_key=self.key)
                self.assertIs(result['manual_approval_required'],False)
                self.assertEqual(self.f.saved_settings,[(False,1)])
                path.write_bytes(canonical({**connection,'capability':{}}))
                with self.assertRaises(AXRError):load_connection(path)
        finally:
            server.close()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive(),'owner pipe must stop without a dummy authenticated request')

    @unittest.skipUnless(sys.platform=='win32','Windows synchronous pipe cancellation')
    def test_pipe_shutdown_is_bounded_during_accept_handshake_and_idle_session(self):
        script=r'''
import os,secrets,sys,threading,time
import win32file,win32con
from axr.authority_server import AuthorityServer,AuthorityClient
from axr.ipc import PeerRegistry,process_identity
from test.test_authority_mcp import application_fixture
f=application_fixture()
actual=process_identity(os.getpid())
registry=PeerRegistry(f.store,development_fixture=True)
registry.enroll(actual,'owner',f.owner.principal,lambda:actual['user'])
f.k.integrity.persist()
endpoint=r'\\.\pipe\Stellaria.AXR.stop-fixture.'+secrets.token_hex(12)
server=AuthorityServer(f.k,registry,endpoint)
thread=threading.Thread(target=server.serve,daemon=True)
thread.start()
deadline=time.monotonic()+2
while server.listener is None:
    if time.monotonic()>deadline:raise RuntimeError('fixture_listener_failed')
    time.sleep(.01)
client=None
try:
    if sys.argv[1]=='handshake':
        client=win32file.CreateFile(endpoint,win32con.GENERIC_READ|win32con.GENERIC_WRITE,0,None,win32con.OPEN_EXISTING,0x00100000,None)
    elif sys.argv[1]=='idle':client=AuthorityClient.connect(endpoint,actual)
    time.sleep(.03)
    server.close()
    thread.join(timeout=2)
    assert not thread.is_alive(),'authority pipe shutdown blocked'
    server.close()
finally:
    if client:
        client.close() if hasattr(client,'close') else client.Close()
    f.doCleanups()
'''
        for mode in ('accept','handshake','idle'):
            with self.subTest(mode=mode):
                result=subprocess.run([sys.executable,'-c',script,mode],
                    cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=8)
                self.assertEqual(result.returncode,0,result.stderr.decode('utf8',errors='replace'))
