# SPDX-License-Identifier: MIT
"""Synthetic diagnostics contracts; no real window, file, service or owner UI."""
import contextlib,io,json,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(sys.platform=='win32','Windows diagnostic interface')
class WindowsDeviceTest(unittest.TestCase):
    def setUp(self):
        from desktop import windows_device_test as device
        self.device=device;self.windows=[(1,2,Path('C:/synthetic/Weixin.exe'),'synthetic-owner','synthetic-birth')]
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        for name,value in (('_windows',self.windows),('_sha','a'*64),('_version','4.0.0.0'),
                           ('_installation',{'files_present':False,'verified':False,'configuration':False,
                            'owner_initialized':False,'service_state':'Absent','qualification_permit':False})):
            self.stack.enter_context(patch.object(device,name,return_value=value))
        self.stack.enter_context(patch.object(device.native,'process_identity',return_value=json.dumps({'user':'synthetic-owner'})))

    def test_uninstalled_device_is_blocked_without_authentication_or_structure(self):
        with patch.object(self.device,'_structure') as structure:
            result=self.device.inspect_device()
        structure.assert_not_called();self.assertEqual(result['state'],'Blocked')
        self.assertIn('protected_service_installation_required',result['blockers'])
        self.assertEqual(result['structure'],{'state':'NotRequested'})
        for key in ('content_read','input_performed','model_called','send_invoked','authorization_granted','runtime_qualified','retry'):
            self.assertIs(result[key],False)
        self.assertNotIn('synthetic-owner',json.dumps(result));self.assertNotIn('synthetic/',json.dumps(result))

    def test_metadata_presence_never_asserts_qualification(self):
        with patch.object(self.device,'_installation',return_value={'verified':True,'configuration':True,
                'owner_initialized':True,'service_state':'Stopped','qualification_permit':True}):
            result=self.device.inspect_device()
        self.assertEqual(result['state'],'PrerequisitesObserved');self.assertFalse(result['runtime_qualified'])

    def test_ambiguous_window_and_other_owner_do_not_inspect_structure(self):
        with patch.object(self.device,'_structure') as structure:
            for windows in ([],self.windows*2,[(1,2,Path('C:/synthetic/Weixin.exe'),'different-owner','synthetic-birth')]):
                with self.subTest(windows=len(windows)),patch.object(self.device,'_windows',return_value=windows):
                    result=self.device.inspect_device(package='synthetic',wechat_sha256='a'*64)
                    self.assertEqual(result['state'],'Blocked')
            structure.assert_not_called()

    def test_structure_needs_exact_pin_and_detects_epoch_change(self):
        for kwargs in ({'package':'synthetic'},{'wechat_sha256':'a'*64},
                       {'package':'synthetic','wechat_sha256':'b'*64}):
            with self.subTest(kwargs=kwargs),patch.object(self.device,'_structure') as structure:
                with self.assertRaises(Exception):self.device.inspect_device(**kwargs)
                structure.assert_not_called()
        with patch.object(self.device,'_structure',return_value={'nodes':[],'node_budget_reached':False}),patch.object(
                self.device,'_windows',side_effect=[self.windows,[]]):
            with self.assertRaisesRegex(Exception,'device_test_application_changed'):
                self.device.inspect_device(package='synthetic',wechat_sha256='a'*64)

    def test_structure_missing_edit_or_truncation_is_a_blocker(self):
        for truncated,blocker in ((False,'uia_edit_controls_not_exposed'),(True,'uia_structure_budget_reached')):
            with self.subTest(truncated=truncated),patch.object(self.device,'_structure',return_value={
                    'nodes':[{'path':[],'role':'Other','children':0}],'node_budget_reached':truncated}):
                result=self.device.inspect_device(package='synthetic',wechat_sha256='a'*64)
                self.assertIn(blocker,result['blockers'])

    def test_helper_protocol_is_metadata_only_and_drops_identifiers(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as area:
            root=Path(area);nodes=[{'path':[],'role':'Other','identifier':'private-id','children':0}]
            output={'nodes':nodes,'text_redacted':True}
            with patch('scripts.install_authority_windows.review',return_value={'files':{'wechat-uia.exe':'b'*64},
                    'source_revision':'c'*40}),patch.object(self.device.subprocess,'run',return_value=
                    subprocess.CompletedProcess([],0,json.dumps(output).encode(),b'')) as run:
                result=self.device._structure(root,'a'*64)
            self.assertNotIn('private-id',json.dumps(result))
            request=json.loads(run.call_args.kwargs['input'])
            self.assertEqual(request,{'op':'structure','executable_hash':'a'*64})
            self.assertEqual(run.call_args.kwargs['timeout'],25)
            self.assertNotIn('PYTHONPATH',run.call_args.kwargs['env'])
            nodes[0]['value']='private content'
            with patch('scripts.install_authority_windows.review',return_value={'files':{'wechat-uia.exe':'b'*64},
                    'source_revision':'c'*40}),patch.object(self.device.subprocess,'run',return_value=
                    subprocess.CompletedProcess([],0,json.dumps(output).encode(),b'')):
                with self.assertRaisesRegex(Exception,'device_test_structure_invalid'):self.device._structure(root,'a'*64)

    def test_installation_error_is_bounded_and_summary_is_plain_language(self):
        with patch.object(self.device,'_installation',side_effect=RuntimeError('private path')):
            result=self.device.inspect_device()
        self.assertIn('protected_installation_unavailable',result['blockers'])
        self.assertNotIn('private path',json.dumps(result))
        summary=self.device.describe_result(result)
        self.assertIn('尚未',summary);self.assertNotIn('protected_installation',summary)

    def test_command_routes_only_signed_qualification_and_sanitizes_errors(self):
        from scripts.windows_device_test import main
        with (patch('scripts.windows_device_test.inspect_device',side_effect=RuntimeError('C:/private/token')),
                contextlib.redirect_stdout(io.StringIO()) as output):
            self.assertEqual(main(['inspect']),2)
        self.assertNotIn('private',output.getvalue())
        with (patch('axr_applications.windows_navigation.read_json',return_value={'signed':'synthetic'}) as read,
                patch('desktop.windows_lifecycle.qualify_once',return_value={'state':'Recorded'}) as qualify,
                contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(main(['qualify','--permit','synthetic.json']),0)
        read.assert_called_once_with('synthetic.json',20000);qualify.assert_called_once_with({'signed':'synthetic'})

    def test_frozen_output_is_explicit_and_existing_file_prevents_execution(self):
        from tempfile import TemporaryDirectory
        from scripts.windows_device_test import main
        with TemporaryDirectory() as area:
            target=Path(area)/'result.json'
            value={'state':'Blocked','runtime_qualified':False,'retry':False}
            with patch('scripts.windows_device_test.inspect_device',return_value=value),patch('sys.stdout',None):
                self.assertEqual(main(['inspect','--output',str(target)]),2)
            self.assertEqual(json.loads(target.read_bytes()),value)
            with patch('scripts.windows_device_test.inspect_device') as inspect,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['inspect','--output',str(target)]),2)
                inspect.assert_not_called()
            self.assertEqual(json.loads(target.read_bytes()),value)
