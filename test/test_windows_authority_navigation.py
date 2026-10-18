# SPDX-License-Identifier: MIT
"""Windows native v2 plumbing; invalid synthetic proofs cannot reach UI actions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from axr.aet import AXRError,Action,Resource,canonical
from axr_applications.wechat_execution import AuthorityNavigation
from axr_applications.attempts import claim_attempt


@unittest.skipUnless(sys.platform=='win32','Windows anonymous helper pipes')
class WindowsFrames(unittest.TestCase):
    def child(self,script):
        process=subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        def cleanup():
            if process.poll() is None:process.kill()
            process.wait(timeout=3)
            process.stdout.close()
        self.addCleanup(cleanup)
        return process
    def test_partial_pipe_reads_reassemble_a_single_metadata_frame(self):
        process=self.child("import os,time; os.write(1,b'{\"ok\":'); time.sleep(.03); os.write(1,b'true}\\n')")
        self.assertEqual(AuthorityNavigation._frame(process,3),{'ok':True})
    def test_eof_and_non_object_frames_are_rejected(self):
        for script,code in (("pass",'closed'),("print('[]')",'protocol'),("print('bad json')",'protocol')):
            with self.subTest(code=code),self.assertRaisesRegex(AXRError,code):
                AuthorityNavigation._frame(self.child(script),3)
    def test_pipe_reader_timeout_does_not_treat_live_child_as_completed(self):
        process=self.child('import time; time.sleep(30)')
        with self.assertRaisesRegex(AXRError,'timeout'):AuthorityNavigation._frame(process,.05)
        self.assertIsNone(process.poll())


@unittest.skipUnless(sys.platform=='win32','Windows durable attempt marker')
class WindowsAttempts(unittest.TestCase):
    def test_directory_traversal_does_not_request_write_or_delete_on_a_shared_directory(self):
        from axr import windows_files as files
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            handle=files.kernel.CreateFileW(str(path),0x80000000,0x1,None,3,0x02000000,None)
            self.assertNotEqual(handle,__import__('ctypes').c_void_p(-1).value)
            try:
                opened=files.open_root(path)
                files.close(opened)
            finally:files.close(handle)
    def test_concurrent_claims_have_one_winner_and_cannot_overwrite_marker(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic-attempt.json'
            def claim(_):
                try:claim_attempt(path);return True
                except FileExistsError:return False
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(claim,range(8))),1)
            self.assertEqual(json.loads(path.read_bytes()),{'attempted':True,'retry':False})
    def test_flush_failure_retains_marker_and_prevents_second_claim(self):
        from axr import windows_files
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic-uncertain.json'
            with patch.object(windows_files.kernel,'FlushFileBuffers',return_value=0):
                with self.assertRaisesRegex(AXRError,'flush_failed'):claim_attempt(path)
            self.assertTrue(path.exists())
            with self.assertRaises(FileExistsError):claim_attempt(path)


@unittest.skipUnless(sys.platform=='win32','Windows native UIA v2 helper')
class WindowsNativeBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('WECHAT_TEST_WINDOWS_UIA')
        if not path:raise unittest.SkipTest('explicit Windows UIA build required')
        cls.helper=Path(path).resolve(strict=True)
    def test_actual_ready_birth_protocol_and_invalid_proof_stop_before_ui(self):
        events=[]
        def enroll(actual):events.append(('enroll',actual))
        def prepare(action,actual):
            events.append(('prepare',actual))
            return {'body':{'helper_pid':actual['pid'],'helper_birth':actual['birth'],'seal':action.seal},'signature':'synthetic-invalid'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=AuthorityNavigation(self.helper,hashlib.sha256(self.helper.read_bytes()).hexdigest(),
                r'\\.\pipe\Stellaria.AXR.never-created-fixture',Path(directory),
                enroll_handler=enroll,prepare=prepare,receipt=lambda eid:{'state':'Unknown','execution_id':eid})
            action=Action('fixture',Resource('wechat','fixture-account','fixture-peer'),'status.read',
                'fixture',{'mode':'read_draft','text':'synthetic draft, never inserted','visual_binding':{}})
            result=bridge.invoke(action,check=lambda:None)
            self.assertEqual([row[0] for row in events],['enroll','prepare'])
            self.assertEqual(events[0][1],events[1][1])
            self.assertEqual(result['native']['error'],'authority_or_scope_changed')
            self.assertIs(result['native']['send_invoked'],False)
            self.assertIs(result['native']['content_disclosed'],False)
            self.assertFalse(result['retry'])
    def test_mode_operation_mismatch_and_extra_arguments_never_act(self):
        request={'mode':'stage_draft','operation':'messages.send','expected_text':'synthetic',
            'account':'fixture','identity':'fixture','visual_binding':{},
            'guard_context':{'authority_endpoint':'unused','proof':'{}'}}
        result=subprocess.run([str(self.helper),'--authority-v2'],input=canonical(request)+b'\n',
            capture_output=True,timeout=5)
        frames=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(frames[0],{'version':2,'ready':True,'input_received':False})
        self.assertEqual(frames[1]['error'],'authority_operation_mismatch')
        self.assertIs(frames[1]['send_invoked'],False)
        denied=subprocess.run([str(self.helper),'--script','untrusted'],capture_output=True,timeout=5)
        self.assertEqual(json.loads(denied.stdout),{'error':'fixed_entrypoint_required'})

    def test_send_requires_mac_equivalent_cached_recipient_witness_before_ui(self):
        request={'mode':'send','operation':'messages.send','expected_text':'synthetic fixture only',
            'account':'fixture-account','identity':'fixture-peer','visual_binding':{},
            'guard_context':{'authority_endpoint':'unused','proof':'{}'}}
        for binding in ({}, {'recipient_assurance':'cached_exact_draft_and_fresh_search'},
                        {'recipient_assurance':'cached_exact_draft_and_fresh_search','recipient_witness':'A'*64},
                        {'recipient_assurance':'cached_exact_draft_and_fresh_search','recipient_witness':'a'*63+'g'},
                        {'recipient_assurance':'wrong','recipient_witness':'a'*64}):
            with self.subTest(binding=binding):
                request['visual_binding']=binding
                result=subprocess.run([str(self.helper),'--authority-v2'],input=canonical(request)+b'\n',
                    capture_output=True,timeout=5)
                frames=[json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(frames[0],{'version':2,'ready':True,'input_received':False})
                self.assertEqual(frames[1]['error'],'recipient_witness_required')
                self.assertIs(frames[1]['send_invoked'],False)
                self.assertIs(frames[1]['content_disclosed'],False)
        request['visual_binding']={'recipient_assurance':'cached_exact_draft_and_fresh_search',
                                   'recipient_witness':'a'*64}
        result=subprocess.run([str(self.helper),'--authority-v2'],input=canonical(request)+b'\n',
            capture_output=True,timeout=5)
        frames=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(frames[1]['error'],'authority_or_scope_changed')
        self.assertIs(frames[1]['send_invoked'],False)
