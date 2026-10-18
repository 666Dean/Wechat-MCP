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

    def test_local_job_review_signs_only_the_exact_server_action(self):
        read=self.f.application.dispatch(self.f.client,{'method':'read_context',
            'parameters':{'conversation_id':'fixture-peer'},'capability':self.f.capability})
        proposed=self.f.application.dispatch(self.f.client,{'method':'disclose_context',
            'parameters':{'conversation_id':'fixture-peer','context_id':read['result']['context_id']},
            'capability':self.f.capability})
        source=LocalInput(False)
        source.next=canonical({'operation':'approve-job','job_id':proposed['id']})+b'\n'
        result=self.run_control(source)
        self.assertTrue(result['approved'])
        self.assertEqual(source.outputs[0]['review']['action']['operation'],'disclosure.send')
        self.assertEqual(len(self.signers),1)
        self.assertNotIn('fixture-secret',json.dumps(source.outputs))

    def test_changed_exact_job_preview_is_refused_before_requesting_a_key(self):
        read=self.f.application.dispatch(self.f.client,{'method':'read_context',
            'parameters':{'conversation_id':'fixture-peer'},'capability':self.f.capability})
        proposed=self.f.application.dispatch(self.f.client,{'method':'disclose_context',
            'parameters':{'conversation_id':'fixture-peer','context_id':read['result']['context_id']},
            'capability':self.f.capability})
        original=self.connect
        def changed(*args):
            channel=original(*args);request=channel.request
            def tampered(*a,**kw):
                result=request(*a,**kw)
                if kw.get('phase')=='review-application':result['review']['action']['purpose']='changed'
                return result
            channel.request=tampered
            return channel
        self.connect=changed
        source=LocalInput(False)
        source.next=canonical({'operation':'approve-job','job_id':proposed['id']})+b'\n'
        with self.assertRaisesRegex(AXRError,'review_invalid'):self.run_control(source)
        self.assertEqual(self.signers,[]);self.assertEqual(source.outputs,[])

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
    def test_idle_connection_does_not_block_independent_owner_or_helper_connection(self):
        script=r'''
import os,secrets,threading,time
from axr.authority_server import AuthorityServer,AuthorityClient
from axr.ipc import PeerRegistry,process_identity
from test.test_authority_mcp import application_fixture
f=application_fixture()
actual=process_identity(os.getpid())
registry=PeerRegistry(f.store,development_fixture=True)
registry.enroll(actual,'owner',f.owner.principal,lambda:actual['user'])
f.k.integrity.persist()
endpoint=r'\\.\pipe\Stellaria.AXR.concurrent-fixture.'+secrets.token_hex(12)
server=AuthorityServer(f.k,registry,endpoint)
thread=threading.Thread(target=server.serve,daemon=True);thread.start()
first=second=None
try:
    deadline=time.monotonic()+3
    while server.listener is None:
        if time.monotonic()>deadline:raise RuntimeError('fixture_listener_failed')
        time.sleep(.01)
    first=AuthorityClient.connect(endpoint,actual)
    second=AuthorityClient.connect(endpoint,actual)
    response=second.request('Authorize',phase='review-approval-setting',manual_approval_required=False)
    assert response['challenge']['kind']=='wechat-approval-setting'
finally:
    if first:first.close()
    if second:second.close()
    server.close();thread.join(3)
    assert not thread.is_alive()
    assert not server.io_threads
    f.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

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
