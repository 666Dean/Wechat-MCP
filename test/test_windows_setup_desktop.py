# SPDX-License-Identifier: MIT
"""Windows setup metadata and UAC protocol, with no real admin or Hello action."""
import hashlib,json,os,shutil,ssl,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from axr import _axr_native as native
from axr.aet import AXRError,canonical
from desktop import windows_setup as setup,windows_provisioning as provisioning
from axr_applications import windows_enrollment as enrollment
from test.test_windows_attestation import Evidence,public

@unittest.skipUnless(sys.platform=='win32','Windows machine public trust')
class PublicTrust(unittest.TestCase):
    def test_actual_machine_public_ca_bundle_parses_without_any_private_key(self):
        pem=native.windows_public_ca_bundle();self.assertIn('BEGIN CERTIFICATE',pem);self.assertNotIn('PRIVATE KEY',pem)
        self.assertLessEqual(len(pem),2*1024**2)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.load_verify_locations(cadata=pem)
        self.assertGreater(context.cert_store_stats()['x509_ca'],0)
    def test_peer_supplied_software_root_is_not_trusted_by_machine_mode(self):
        e=Evidence()
        self.assertTrue(native.verify_windows_hello_attestation(public(e.owner),e.statement(),e.chain(),e.roots))
        self.assertFalse(native.verify_windows_hello_attestation_machine(public(e.owner),e.statement(),e.chain()))
    def test_only_exact_protected_machine_marker_selects_machine_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'hello-trust.json';file.write_bytes(canonical(enrollment.MACHINE_TRUST))
            self.assertEqual(enrollment.trust_roots(root),'local-machine-root')
            for value in ({'version':2,'source':'current-user-root'},{'version':2.0,'source':'local-machine-root'},{'version':2,'source':'local-machine-root','trusted':True}):
                file.write_bytes(canonical(value))
                with self.assertRaisesRegex(AXRError,'trust_roots_required'):enrollment.trust_roots(root)

@unittest.skipUnless(sys.platform=='win32','Windows fixed UAC request')
class SetupRequest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.owner=json.loads(native.process_identity(os.getpid()))['user']
        profile=patch.object(setup,'profile_for_sid',return_value=self.root/'profile');profile.start();self.addCleanup(profile.stop)
        admin=patch('scripts.install_authority_windows.administrator');admin.start();self.addCleanup(admin.stop)
    def test_held_directory_roundtrip_is_bound_to_exact_operation_nonce_owner_and_sha(self):
        request,sha,value=setup.prepare_request('initialize',{})
        with patch.object(setup,'execute',return_value={'initialized':True,'authorization_restored':False}) as execute:
            self.assertEqual(setup.admin_main(request,sha),0);execute.assert_called_once_with('initialize',{})
        result=json.loads((request.parent/'outcome.json').read_bytes());self.assertEqual(result['nonce'],value['nonce']);self.assertEqual(result['operation'],'initialize')
        self.assertEqual(result['result'],{'initialized':True,'authorization_restored':False})
    def test_tampered_digest_arbitrary_location_or_operation_never_executes(self):
        request,sha,value=setup.prepare_request('stop',{})
        with patch.object(setup,'execute') as execute:
            with self.assertRaisesRegex(AXRError,'request_changed'):setup.admin_main(request,'a1'*32)
            outside=self.root/'request.json';outside.write_bytes(request.read_bytes())
            with self.assertRaisesRegex(AXRError,'request_invalid'):setup.admin_main(outside,sha)
            value['operation']='run-shell';raw=canonical(value);request.write_bytes(raw)
            with self.assertRaisesRegex(AXRError,'request_invalid'):setup.admin_main(request,hashlib.sha256(raw).hexdigest())
            execute.assert_not_called()
    def test_failed_operation_returns_only_bounded_error_without_private_exception_text(self):
        request,sha,value=setup.prepare_request('recover',{})
        with patch.object(setup,'execute',side_effect=RuntimeError('synthetic private exception detail')):
            self.assertEqual(setup.admin_main(request,sha),1)
        result=(request.parent/'outcome.json').read_bytes();self.assertNotIn(b'private exception',result)
        self.assertEqual(json.loads(result)['error'],'windows_setup_operation_failed')
    def test_parent_wait_does_not_retry_when_result_is_missing_or_expired(self):
        import win32api,win32event,win32process
        with patch.object(setup,'shell_execute',return_value=123),patch.object(win32api,'CloseHandle'),patch.object(
                win32event,'WaitForSingleObject',return_value=win32event.WAIT_OBJECT_0),patch.object(win32process,'GetExitCodeProcess',return_value=0):
            with self.assertRaisesRegex(AXRError,'unknown_no_retry'):setup.invoke('start')
            with self.assertRaisesRegex(AXRError,'unknown_no_retry'):setup.invoke('start',timeout=0)
    def test_admin_bootstrap_has_fixed_executable_hidden_window_and_no_caller_command(self):
        from win32com.shell import shell
        request,sha,_=setup.prepare_request('stop',{})
        with patch.object(shell,'ShellExecuteEx',return_value={'hProcess':123}) as launch:
            self.assertEqual(setup.shell_execute(request,sha),123)
        values=launch.call_args.kwargs;self.assertEqual(values['lpVerb'],'runas');self.assertEqual(values['nShow'],0)
        self.assertEqual(values['lpFile'],sys.executable);self.assertIn('--windows-setup-request',values['lpParameters']);self.assertNotIn('cmd /c',values['lpParameters'])
    def test_initialize_and_start_share_one_admin_action_without_restoring_authority(self):
        service=Mock();service.run.side_effect=[{'completed':'initialize','authorization_restored':False},{'service_started':True,'authorization_restored':False}]
        with patch('scripts.windows_service.ServiceController',return_value=service):value=setup.execute('initialize',{})
        self.assertTrue(value['initialized']);self.assertTrue(value['service_started']);self.assertFalse(value['authorization_restored'])
        self.assertEqual([c.args for c in service.run.call_args_list],[('initialize',),()])

@unittest.skipUnless(sys.platform=='win32','Windows setup configuration builder')
class Configuration(unittest.TestCase):
    def test_account_metadata_preparation_never_parses_raw_credentials_or_login_file(self):
        with tempfile.TemporaryDirectory() as directory:
            area=Path(directory).resolve();profile=area/'profile';(profile/'.codex').mkdir(parents=True)
            auth=profile/'.codex/auth.json';auth.write_bytes(b'synthetic login bytes, never parsed')
            root=area/'wxid_fixture_owner_install/db_storage'
            for name in ('contact/contact.db','session/session.db','general/general.db','message/message_0.db'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'1'*4096)
            credential=area/'selected.key';credential.write_bytes(b'a'*64)
            program=area/'synthetic-provider.exe'
            shutil.copyfile(Path(os.environ['SystemRoot'])/'System32/whoami.exe',program)
            read=Path.read_bytes
            def guarded(path):
                if path in (credential,auth):raise AssertionError('raw credential reached Python')
                return read(path)
            with patch.object(Path,'home',return_value=profile),patch.object(Path,'read_bytes',guarded),patch.object(
                    native,'windows_installation_root',return_value=str(area/'installed')),patch.object(native,'windows_data_root',return_value=str(area/'private')):
                config,assets=provisioning.configuration(root,'wxid_fixture_owner',credential,program,area/'local',key_mode='password')
            value=config['deployment'];self.assertEqual(value['state'],str(area/'private/state/wechat'))
            self.assertEqual(value['application']['codex_provider']['workspace'],str(area/'private/source'))
            self.assertEqual(value['credential_import']['key_mode'],'password');self.assertEqual(len(value['credential_import']['sha256']),64)
            self.assertEqual(len(value['application']['shards']),4);self.assertEqual(set(assets),{'codex','ca'})
            self.assertFalse((area/'private').exists());self.assertNotIn('synthetic login',str(config))
