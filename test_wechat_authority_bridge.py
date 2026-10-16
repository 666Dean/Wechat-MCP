# SPDX-License-Identifier: MIT
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from axr.aet import AXRError,Action,Resource,canonical,digest
from axr_applications.wechat_execution import AuthorityNavigation

class Process:
    def __init__(self,path):
        import io
        self.pid=79;self.stdin=io.BytesIO();self.stdout=io.BytesIO();self.closed=False;self.path=path
    def poll(self):return 0 if self.closed else None
    def wait(self,timeout=None):self.closed=True;return 0
    def terminate(self):self.closed=True
    def kill(self):self.closed=True

@unittest.skipIf(os.name=='nt','macOS native helper protocol')
class AuthorityBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.helper=Path(self.tmp.name)/'helper';self.helper.write_bytes(b'synthetic helper image, never executed')
        self.sha=hashlib.sha256(self.helper.read_bytes()).hexdigest();self.proc=Process(self.helper)
        self.identity={'pid':79,'birth':'fixture-birth','image':str(self.helper),'image_sha256':self.sha}
        self.action=Action('fixture-controller',Resource('wechat','fixture-owner','fixture-peer'),'messages.send','fixture',{'mode':'send','text':'fixture only','visual_binding':{'fixture':True}})
        self.events=[]
        def enroll(actual):self.events.append('enroll');self.assertEqual(actual,self.identity)
        def prepare(action,actual):self.events.append('prepare');return {'body':{'helper_pid':actual['pid'],'helper_birth':actual['birth'],'seal':action.seal},'signature':'fixture'}
        self.bridge=AuthorityNavigation(self.helper,self.sha,'fixture.sock',Path(self.tmp.name)/'attempts',enroll_handler=enroll,prepare=prepare,receipt=lambda eid:{'state':'Unknown','execution_id':eid})
        self.patches=[patch('axr_applications.wechat_execution.subprocess.Popen',return_value=self.proc),patch('axr_applications.wechat_execution.process_identity',return_value=self.identity)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def test_actual_birth_ready_before_proof_and_no_retry(self):
        ready={'version':2,'ready':True,'input_received':False}
        with patch.object(self.bridge,'_frame',side_effect=[ready,{'send_invoked':True}]):
            result=self.bridge.invoke(self.action,check=lambda:None)
        self.assertEqual(self.events,['enroll','prepare']);self.assertEqual(result['receipt']['state'],'Unknown');self.assertFalse(result['retry']);self.assertFalse(result['delivery_confirmed'])
        with self.assertRaisesRegex(AXRError,'never_retry'):self.bridge.invoke(self.action,check=lambda:None)
    def test_lost_native_response_is_unknown_not_false_send(self):
        with patch.object(self.bridge,'_frame',side_effect=[{'version':2,'ready':True,'input_received':False},AXRError('lost')]):
            result=self.bridge.invoke(self.action,check=lambda:None)
        self.assertIsNone(result['native']);self.assertEqual(result['receipt']['state'],'Unknown');self.assertNotIn('send_invoked',result)
    def test_unready_never_enrolls_or_submits(self):
        with patch.object(self.bridge,'_frame',return_value={'ready':True}),self.assertRaisesRegex(AXRError,'ready_required'):
            self.bridge.invoke(self.action,check=lambda:None)
        self.assertEqual(self.events,[]);self.assertEqual(list((Path(self.tmp.name)/'attempts').iterdir()),[])
    def test_changed_image_or_scope_denied(self):
        self.helper.write_bytes(b'changed')
        with self.assertRaisesRegex(AXRError,'build_changed'):self.bridge.invoke(self.action,check=lambda:None)
        with self.assertRaisesRegex(AXRError,'operation_mismatch'):self.bridge.invoke(Action('x',self.action.resource,'messages.send','x',{'mode':'navigate'}),check=lambda:None)

class SourceProviderTests(unittest.TestCase):
    def test_snapshot_masks_credentials_and_filters_outbound(self):
        from axr_applications.wechat_database import actor_records
        records=actor_records({'messages':[
            {'reference':'inbound-fixture','outgoing':False,'text':'密码：fixture-secret'},
            {'reference':'outbound-fixture','outgoing':True,'text':'owner text'}]})
        self.assertEqual(len(records),1);self.assertNotIn('fixture-secret',records[0]['text'])
        with self.assertRaisesRegex(AXRError,'bounded_page'):
            actor_records({'messages':[{'reference':'fixture','outgoing':False,'text':'字'*2000}]})
    def test_seal_and_history_cannot_be_substituted(self):
        from axr_applications.codex_source import CodexSourceProvider
        provider=object.__new__(CodexSourceProvider);provider.used=False;provider.lock=__import__('threading').Lock()
        action=Action('fixture-controller',Resource('wechat','fixture-owner','fixture-peer'),'disclosure.send','incoming-inference',{'request_digest':'invalid','context_id':'fixture'},destination=provider.destination)
        request={'version':2,'context_id':'fixture','contract':'fixture','records':[],'style':'','allowed_outputs':['ReplyDraft'],'source_keys':[action.resource.key],'tools':[],'history':[],'parent_context':None}
        with self.assertRaisesRegex(AXRError,'seal_or_context'):provider.complete(action,request,{},lambda:None)
        request['parent_context']='developer-history'
        with self.assertRaisesRegex(AXRError,'seal_or_context'):provider.complete(action,request,{},lambda:None)
        self.assertFalse(provider.used)
    def test_consumed_context_cannot_make_second_model_call(self):
        from axr_applications.codex_source import CodexSourceProvider
        provider=object.__new__(CodexSourceProvider);provider.used=True;provider.lock=__import__('threading').Lock()
        with self.assertRaisesRegex(AXRError,'already_consumed'):provider.complete(None,{},None,lambda:None)

@unittest.skipUnless(sys.platform=='darwin','macOS Seatbelt provider witness')
class SourceSandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil,subprocess
        compiler=shutil.which('clang')
        if not compiler:raise unittest.SkipTest('native synthetic witness needs clang')
        cls.temporary=tempfile.TemporaryDirectory();cls.root=Path(cls.temporary.name).resolve()
        cls.binary=cls.root/'bin/probe';cls.binary.parent.mkdir()
        subprocess.run([compiler,str(Path(__file__).parent/'test/fixtures/source_sandbox_probe.c'),'-o',str(cls.binary)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()
    def test_own_workspace_read_but_no_foreign_file_or_other_executable(self):
        import subprocess
        from axr_applications.codex_source import CodexSourceProvider
        auth=self.root/'synthetic-auth';auth.write_text('public fixture, no token')
        work=self.root/'workspace';work.mkdir(exist_ok=True)
        private=self.root/'another-source';private.write_text('synthetic other source')
        allowed=work/'source.txt';allowed.write_text('synthetic current source')
        provider=CodexSourceProvider(self.binary,hashlib.sha256(self.binary.read_bytes()).hexdigest(),auth,work,claim=lambda *a:None,observe=lambda *a:None)
        profile=provider._profile(work)
        def run(*arguments):
            result=subprocess.run(['/usr/bin/sandbox-exec','-p',profile,str(self.binary),*arguments],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr);return result.stdout.strip()
        self.assertEqual(run('read',str(allowed)),'allowed')
        self.assertEqual(run('read',str(private)),'denied')
        self.assertEqual(run('exec'),'denied')
