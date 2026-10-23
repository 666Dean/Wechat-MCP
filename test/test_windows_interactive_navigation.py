# SPDX-License-Identifier: MIT
"""Synthetic native-channel wiring and ordinary-host refusal; no UI operations."""
import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from axr import _axr_native as native
from axr.aet import AXRError,Action,Resource
from axr_applications.wechat_execution import AuthorityNavigation

@unittest.skipUnless(sys.platform=='win32','Windows interactive navigation')
class WindowsInteractiveNavigation(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);self.root=Path(directory.name)
        self.helper=self.root/'wechat-uia.exe';self.helper.write_bytes(b'synthetic helper; never executed')
        self.actual={'pid':123,'birth':'synthetic-birth','image':str(self.helper),'user':'S-1-5-21-1-2-3-4',
            'image_sha256':hashlib.sha256(self.helper.read_bytes()).hexdigest()}
        self.channel=Mock(identity=json.dumps(self.actual));self.channel.ready.return_value=json.dumps({'version':2,'ready':True,'input_received':False})
        self.channel.result.return_value=json.dumps({'send_invoked':False,'content_disclosed':False})
        self.events=[]
        self.bridge=AuthorityNavigation(self.helper,self.actual['image_sha256'],'unused',self.root/'attempts',
            owner_user=self.actual['user'],enroll_handler=lambda value:self.events.append(('enroll',value)),
            prepare=lambda action,actual:{'body':{'helper_pid':actual['pid'],'helper_birth':actual['birth'],'seal':action.seal}},
            receipt=lambda execution:{'state':'Unknown'},release_handler=lambda value:self.events.append(('release',value)))
    def action(self,mode='binding'):
        return Action('synthetic',Resource('wechat','synthetic-owner','synthetic-peer'),
            'messages.send' if mode=='send' else 'status.read','synthetic',{'mode':mode,'text':'Synthetic text','visual_binding':{}})
    def test_native_channel_keeps_ready_enroll_exact_submit_receipt_cleanup_order(self):
        with patch.object(native,'WindowsNavigation',return_value=self.channel) as launch,patch(
                'axr_applications.wechat_execution.process_identity',return_value=self.actual),patch(
                'axr_applications.wechat_execution.subprocess.Popen') as popen:
            result=self.bridge.invoke(self.action(),check=lambda:None)
        popen.assert_not_called();self.assertEqual(launch.call_args.args[:3],(self.actual['user'],str(self.bridge.helper),self.actual['image_sha256']))
        self.assertEqual([name for name,value in self.events],['enroll','release'])
        submitted=json.loads(self.channel.submit.call_args.args[0]);self.assertEqual(submitted['mode'],'binding')
        self.assertEqual(submitted['guard_context']['authority_endpoint'],'unused')
        self.assertFalse(result['retry']);self.channel.close.assert_called_once()
    def test_response_loss_after_send_is_unknown_and_permanent_attempt_prevents_relaunch(self):
        self.channel.result.side_effect=RuntimeError('synthetic pipe closed')
        with patch.object(native,'WindowsNavigation',return_value=self.channel) as launch,patch(
                'axr_applications.wechat_execution.process_identity',return_value=self.actual):
            action=self.action('send');result=self.bridge.invoke(action,check=lambda:None)
            self.assertEqual(result['receipt']['state'],'Unknown')
            with self.assertRaisesRegex(AXRError,'previous_attempt_never_retry'):self.bridge.invoke(action,check=lambda:None)
        launch.assert_called_once();self.channel.close.assert_called_once()
    def test_cancelled_ready_closes_native_process_without_submitting_or_enrolling(self):
        self.channel.ready.side_effect=AXRError('synthetic_stop')
        with patch.object(native,'WindowsNavigation',return_value=self.channel):
            with self.assertRaisesRegex(AXRError,'synthetic_stop'):self.bridge.invoke(self.action(),check=lambda:None)
        self.channel.submit.assert_not_called();self.channel.close.assert_called_once();self.assertEqual(self.events,[])
    def test_system_without_owner_binding_cannot_fall_back_to_popen(self):
        self.bridge.owner_user=None
        with patch('axr_applications.wechat_execution.process_identity',return_value={'user':'S-1-5-18'}),patch(
                'axr_applications.wechat_execution.subprocess.Popen') as popen:
            with self.assertRaisesRegex(AXRError,'interactive_owner_user_required'):self.bridge.invoke(self.action(),check=lambda:None)
        popen.assert_not_called()
    def metadata(self,**changes):
        return {'running':True,'ambiguous_process':False,'accessibility':True,
            'send_invoked':False,'content_disclosed':False,**changes}
    def test_readiness_uses_owner_channel_without_task_enrollment_or_authority(self):
        self.channel.result.return_value=json.dumps(self.metadata())
        self.bridge.enroll=Mock();self.bridge.prepare=Mock();self.bridge.receipt=Mock();self.bridge.release=Mock()
        with patch.object(native,'WindowsNavigation',return_value=self.channel) as launch,patch(
                'axr_applications.wechat_execution.process_identity',return_value=self.actual),patch(
                'axr_applications.wechat_execution.subprocess.Popen') as popen:
            self.assertEqual(self.bridge.readiness('a'*64),self.metadata())
        self.assertEqual(launch.call_args.args[:3],(self.actual['user'],str(self.bridge.helper),self.actual['image_sha256']))
        self.assertEqual(json.loads(self.channel.submit.call_args.args[0]),{'mode':'readiness','executable_hash':'a'*64})
        popen.assert_not_called();self.channel.close.assert_called_once()
        for callback in (self.bridge.enroll,self.bridge.prepare,self.bridge.receipt,self.bridge.release):callback.assert_not_called()
        self.assertEqual(list(self.bridge.attempts.iterdir()),[])
    def test_readiness_rejects_missing_owner_pin_and_changed_helper_before_launch(self):
        with patch.object(native,'WindowsNavigation') as launch,patch('axr_applications.wechat_execution.subprocess.Popen') as popen:
            for pin in (None,'',True,'a'*63,'A'*64,'x'*64):
                with self.subTest(pin=pin),self.assertRaisesRegex(AXRError,'executable_pin_required'):self.bridge.readiness(pin)
            self.helper.write_bytes(b'changed synthetic image')
            with self.assertRaisesRegex(AXRError,'build_changed'):self.bridge.readiness('a'*64)
            self.bridge.owner_user=None
            with self.assertRaisesRegex(AXRError,'owner_user_required'):self.bridge.readiness('a'*64)
        launch.assert_not_called();popen.assert_not_called()
    def test_readiness_rejects_wrong_user_and_changed_birth_before_submit(self):
        for identities in ([{**self.actual,'user':'S-1-5-18'}],[self.actual,{**self.actual,'birth':'reused-pid'}]):
            self.channel.reset_mock()
            with self.subTest(identities=identities),patch.object(native,'WindowsNavigation',return_value=self.channel),patch(
                    'axr_applications.wechat_execution.process_identity',side_effect=identities):
                with self.assertRaisesRegex(AXRError,'instance_changed'):self.bridge.readiness('a'*64)
            self.channel.submit.assert_not_called();self.channel.close.assert_called_once()
    def test_readiness_denies_extra_content_invalid_metadata_and_response_loss(self):
        for value in (self.metadata(text='Synthetic private content'),self.metadata(accessibility=1),
                self.metadata(send_invoked=True),self.metadata(content_disclosed=True),self.metadata(running=False),
                self.metadata(ambiguous_process=True),{'error':'synthetic_uia_failure'}):
            self.channel.reset_mock();self.channel.result.return_value=json.dumps(value)
            with self.subTest(value=value),patch.object(native,'WindowsNavigation',return_value=self.channel),patch(
                    'axr_applications.wechat_execution.process_identity',return_value=self.actual):
                with self.assertRaisesRegex(AXRError,'metadata_required'):self.bridge.readiness('a'*64)
            self.channel.close.assert_called_once()
        self.channel.reset_mock();self.channel.result.side_effect=RuntimeError('synthetic response loss')
        with patch.object(native,'WindowsNavigation',return_value=self.channel),patch(
                'axr_applications.wechat_execution.process_identity',return_value=self.actual):
            with self.assertRaisesRegex(RuntimeError,'response loss'):self.bridge.readiness('a'*64)
        self.channel.close.assert_called_once();self.channel.submit.assert_called_once()
    def test_readiness_cancellation_closes_channel_without_submitting(self):
        self.channel.ready.side_effect=AXRError('synthetic_cancelled')
        with patch.object(native,'WindowsNavigation',return_value=self.channel):
            with self.assertRaisesRegex(AXRError,'cancelled'):self.bridge.readiness('a'*64)
        self.channel.close.assert_called_once();self.channel.submit.assert_not_called()
    def test_readiness_absent_or_ambiguous_window_is_unavailable_metadata(self):
        with patch.object(native,'WindowsNavigation',return_value=self.channel),patch(
                'axr_applications.wechat_execution.process_identity',return_value=self.actual):
            for ambiguous in (False,True):
                value=self.metadata(running=False,accessibility=False,ambiguous_process=ambiguous)
                self.channel.result.return_value=json.dumps(value)
                self.assertEqual(self.bridge.readiness('a'*64),value)
    def test_normal_python_is_rejected_before_token_selection_or_process_launch(self):
        with self.assertRaisesRegex(RuntimeError,'windows_navigation_authority_host_required'):
            native.WindowsNavigation(self.actual['user'],str(self.helper),self.actual['image_sha256'],lambda:None)
    def test_uninstalled_native_pipe_entry_rejects_before_any_ui_action(self):
        helper=os.environ.get('WECHAT_TEST_WINDOWS_UIA')
        if not helper:self.skipTest('explicit Windows native helper build required')
        result=subprocess.run([helper,'--authority-pipe',r'\\.\pipe\Stellaria.AXR.Navigation.'+'a'*32],capture_output=True,timeout=5)
        value=json.loads(result.stdout);self.assertEqual(value['error'],'windows_navigation_denied')
        self.assertIs(value['send_invoked'],False);self.assertIs(value['content_disclosed'],False)
