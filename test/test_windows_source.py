# SPDX-License-Identifier: MIT
"""Real AppContainer boundary with a fake CLI; no credentials or model calls."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from axr import _axr_native as native
from axr.aet import AXRError,Action,Resource,canonical,digest
from axr_applications.codex_source import CodexSourceProvider


@unittest.skipUnless(sys.platform=='win32','Windows source AppContainer')
class WindowsSource(unittest.TestCase):
    def setUp(self):
        probe=os.environ.get('WECHAT_TEST_WINDOWS_SOURCE')
        if not probe:self.skipTest('compiled synthetic Windows source probe required')
        if native.security_release:self.skipTest('reference synthetic executable only; formal host refuses ordinary Python')
        self.directory=tempfile.TemporaryDirectory(prefix='AXR 来源 fixture ');self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve();self.bin=self.root/'bin';self.bin.mkdir()
        self.binary=self.bin/'codex.exe';shutil.copyfile(probe,self.binary)
        self.work=self.root/'workspace';self.work.mkdir()
        self.auth=self.root/'auth.json';self.auth.write_text('{"public":"synthetic non-secret login"}')
        self.ca=self.root/'ca.pem';self.ca.write_text('synthetic trust, no network use')
        self.outside=self.root/'another-source.txt';self.outside.write_text('synthetic other source')
        self.claim=Mock();self.observe=Mock();self.provider=self.make_provider()
    def make_provider(self):
        return CodexSourceProvider(self.binary,hashlib.sha256(self.binary.read_bytes()).hexdigest(),self.auth,self.work,
            tls_bundle=self.ca,claim=self.claim,observe=self.observe,timeout=5)
    def request(self,mode='normal'):
        resource=Resource('wechat','synthetic-owner','synthetic-peer')
        request={'version':2,'context_id':'synthetic-context','contract':'synthetic-contract',
            'records':[{'text':json.dumps({'mode':mode,'outside':str(self.outside),'original_auth':str(self.auth)})}],
            'style':'','allowed_outputs':['ReplyDraft'],'source_keys':[resource.key],'tools':[],'history':[],'parent_context':None}
        action=Action('synthetic',resource,'disclosure.send','synthetic',{'request_digest':digest(request),'context_id':request['context_id']},destination=self.provider.destination)
        return action,request
    def run_source(self,mode='normal',check=lambda:None):
        action,request=self.request(mode);return self.provider.complete(action,request,{},check)
    def test_real_container_reads_only_current_source_and_native_transport_copy(self):
        auth=self.auth.read_bytes();before=self.auth.stat().st_mode
        with patch.dict(os.environ,{'AXR_SYNTHETIC_PARENT_SECRET':'synthetic-parent-value'}):value=self.run_source()
        result=json.loads(value['content'])
        self.assertEqual(result,{'outside_read':False,'original_auth_read':False,'transport_auth_read':True,
            'schema_read':True,'inherited_secret':False,'own_write':True,'other_program':False})
        self.assertEqual(self.auth.read_bytes(),auth);self.assertEqual(self.auth.stat().st_mode,before)
        self.assertEqual(list(self.work.iterdir()),[]);self.claim.assert_called_once();self.observe.assert_called_once()
        with self.assertRaisesRegex(AXRError,'already_consumed'):self.run_source()
    def test_tool_attempt_output_budget_failure_and_wrong_source_never_observe_or_retry(self):
        for mode,code in (('tool','tool_attempt'),('partial_budget','event_budget'),('budget','event_budget'),('fail','inference_failed'),('wrong_source','outside_task_contract')):
            self.provider=self.make_provider();self.claim.reset_mock();self.observe.reset_mock()
            with self.subTest(mode=mode),self.assertRaisesRegex(AXRError,code):self.run_source(mode)
            self.claim.assert_called_once();self.observe.assert_not_called();self.assertEqual(list(self.work.iterdir()),[])
            with self.assertRaisesRegex(AXRError,'already_consumed'):self.run_source(mode)
    def test_revocation_during_child_wait_kills_and_cleans_private_state(self):
        started=time.monotonic()
        def active():
            if time.monotonic()-started>.5:raise AXRError('synthetic_revoked')
        with self.assertRaisesRegex(AXRError,'synthetic_revoked'):self.run_source('wait',active)
        self.assertLess(time.monotonic()-started,4);self.assertEqual(list(self.work.iterdir()),[]);self.observe.assert_not_called()
    def test_long_unicode_workspace_uses_short_system_current_directory(self):
        area=self.work
        while len(str(area))<280:area=area/'synthetic-long-source-component'
        area.mkdir(parents=True);self.work=area;self.provider=self.make_provider()
        self.assertTrue(json.loads(self.run_source()['content'])['own_write']);self.assertEqual(list(area.iterdir()),[])
    def test_junction_in_runtime_is_refused_and_native_private_copy_is_cleaned(self):
        junction=self.bin/'junction'
        result=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(self.root)],capture_output=True)
        self.assertEqual(result.returncode,0)
        try:
            with self.assertRaisesRegex(AXRError,'reparse'):self.run_source()
            self.assertEqual(list(self.work.iterdir()),[])
        finally:junction.rmdir()
    def test_invalid_pe_header_is_refused_before_any_disclosure_claim(self):
        self.binary.write_bytes(b'MZ'+b'\0'*62)
        with self.assertRaisesRegex(AXRError,'executable_invalid'):self.make_provider()
        self.claim.assert_not_called();self.observe.assert_not_called();self.assertEqual(list(self.work.iterdir()),[])
    def test_shared_service_approved_batch_uses_real_native_source_once_and_stays_draft(self):
        from test.test_windows_service import WindowsService
        fixture=WindowsService();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.service.config['codex_provider']=self.provider._windows_configuration()
        fixture.activate(automatic=False,attribution=False)
        _,request=self.request();context=[{'reference':'synthetic-incoming','outgoing':False,'text':request['records'][0]['text']}]
        job={'id':'synthetic-native-source','conversation_id':'fixture-peer','operation':'reply.prepare','state':'Executing',
            'created':time.time(),'expires':time.time()+60,'retry':False}
        with patch.object(native,'run_windows_source',wraps=native.run_windows_source) as run,patch.object(fixture.service.navigation,'invoke') as ui:
            fixture.service.process_incoming(job['id'],job,context);run.assert_not_called()
            self.assertEqual(fixture.service.jobs[job['id']]['state'],'AwaitingDisclosureApproval')
            fixture.approve(job['id']);fixture.service.process_pending();run.assert_called_once()
            result=fixture.service.jobs[job['id']];self.assertEqual(result['state'],'Draft')
            self.assertFalse(json.loads(result['text'])['outside_read']);self.assertNotIn('page',result)
            fixture.service.process_pending();run.assert_called_once();ui.assert_not_called()
        self.assertTrue(fixture.kernel.integrity.verify());self.assertEqual(list(self.work.iterdir()),[])


@unittest.skipUnless(sys.platform=='win32','Windows source native provider routing')
class WindowsSourceRouting(unittest.TestCase):
    def test_native_errors_never_disclose_file_paths_or_arbitrary_exception_text(self):
        self.assertEqual(CodexSourceProvider._windows_error(RuntimeError('windows_source_lpac_required')),'windows_source_lpac_required')
        for message in ('native file failure at C:/synthetic-private/login.json','synthetic private body\nsecret','x'*129):
            self.assertEqual(CodexSourceProvider._windows_error(RuntimeError(message)),'codex_provider_native_failed')
    def test_formal_source_requires_protected_authority_before_inspecting_arguments(self):
        if not native.security_release:self.skipTest('formal SDK only')
        for method,args in ((native.windows_source_readiness,('{}',)),(native.run_windows_source,('{}','{}',lambda:None))):
            with self.assertRaisesRegex(RuntimeError,'protected_authority_required'):method(*args)
