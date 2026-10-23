# SPDX-License-Identifier: MIT
"""Offline runtime/install/service checks; never opens or mutates real SCM."""
import hashlib,json,os,shutil,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from axr.aet import AXRError,canonical
from axr import _axr_native as native
from scripts.windows_runtime import imports,inventory
from scripts import install_authority_windows as installer
from scripts.windows_service import ServiceController

class PortablePE(unittest.TestCase):
    def test_wrappers_truncated_or_non_pe_payloads_are_never_native_components(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'program.exe'
            for data in (b'#!/usr/bin/env node',b'MZ'+b'\0'*120,b'PE\0\0'+b'\0'*512):
                path.write_bytes(data)
                with self.assertRaises(ValueError):imports(path)
    def test_inventory_rejects_links_and_hardlinked_payload_before_packaging(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'asset';source.write_bytes(b'synthetic')
            self.assertEqual(inventory(root),{'asset':hashlib.sha256(b'synthetic').hexdigest()})
            os.link(source,root/'alias')
            with self.assertRaisesRegex(ValueError,'file_invalid'):inventory(root)

@unittest.skipUnless(sys.platform=='win32','Windows native content closure')
class NativeContent(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.code=self.root/'code.exe';self.code.write_bytes(b'original fixture code')
        self.files=inventory(self.root);self.write(self.files)
    def write(self,files):(self.root/'installation-review.json').write_bytes(canonical({'version':2,'files':files}))
    def verify(self):return native.verify_windows_runtime_files(str(self.root))
    def test_actual_native_hash_cache_rechecks_same_size_and_reset_mtime(self):
        self.verify();before=self.code.stat();self.code.write_bytes(b'modified fixture code');os.utime(self.code,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(RuntimeError,'build_changed'):self.verify()
    def test_no_unreviewed_code_links_or_parent_escape_is_accepted(self):
        self.verify();extra=self.root/'extra.dll';extra.write_bytes(b'new fixture code')
        with self.assertRaisesRegex(RuntimeError,'unreviewed_file'):self.verify()
        extra.unlink()
        for name in ('../outside','runtime/../../outside','C:/outside','runtime/./code.exe'):
            self.write({name:hashlib.sha256(b'x').hexdigest()})
            with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'manifest_invalid'):self.verify()
        self.write(self.files);os.link(self.code,self.root/'hardlink')
        with self.assertRaisesRegex(RuntimeError,'file_invalid'):self.verify()
    def test_only_fixed_noncode_owner_metadata_is_mutable_and_acl_trust_stays_separate(self):
        runtime=self.root/'runtime';runtime.mkdir();(runtime/'owner-key.json').write_text('public fixture metadata')
        self.verify()
        with self.assertRaisesRegex(RuntimeError,'not_protected'):native.verify_windows_installation(str(self.root))

@unittest.skipUnless(sys.platform=='win32','Windows formal runtime snapshot')
class RuntimePackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value=os.environ.get('WECHAT_TEST_FORMAL_PACKAGE')
        if not value:raise unittest.SkipTest('staged formal runtime required')
        cls.package=Path(value)
    def test_actual_self_contained_runtime_has_no_account_and_passed_own_fixed_host(self):
        value=installer.review(self.package);self.assertFalse(value['account_data_included']);self.assertFalse(value['vendor_codex_binary_included'])
        self.assertIn('python312.dll',imports(self.package/'axr-authority.exe'))
        report=json.loads((self.package/'runtime-validation.json').read_bytes())
        self.assertTrue(report['runtime_valid']);self.assertFalse(report['authority_started']);self.assertFalse(report['owner_enrolled'])
        self.assertTrue(all(report['checks'].values()))
    def test_tampered_or_extra_file_and_reparse_payload_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'package';shutil.copytree(self.package,root)
            marker=root/'runtime/deployment.json';old=marker.read_bytes();marker.write_bytes(b'{}')
            with self.assertRaisesRegex(AXRError,'changed_since_review'):installer.review(root)
            marker.write_bytes(old);extra=root/'unexpected';extra.write_bytes(b'synthetic')
            with self.assertRaisesRegex(AXRError,'changed_since_review'):installer.review(root)
            extra.unlink();marker.unlink();marker.symlink_to(root/'package-review.json')
            with self.assertRaisesRegex(ValueError,'links_denied'):installer.review(root)
    def test_nonadmin_install_refuses_before_reading_package_or_configuration(self):
        with patch.object(installer.ctypes.windll.shell32,'IsUserAnAdmin',return_value=False),patch.object(installer,'review') as review:
            with self.assertRaisesRegex(AXRError,'administrator_install_required'):installer.install('never-read',configuration={},local_assets={})
            review.assert_not_called()
    def test_offline_copy_binds_complete_code_and_keeps_configuration_outside_public_runtime(self):
        # Real rooted file reads and manifest/hash checks, mocked admin/ACL/SCM.
        # No protected directory, real service, credential or provider is used.
        with tempfile.TemporaryDirectory() as directory:
            area=Path(directory).resolve();root=area/'installed';data=area/'private';provider=Path(os.environ['SystemRoot'])/'System32/whoami.exe'
            ca=area/'ca.pem';ca.write_bytes(b'public CA fixture');trust=area/'trust.json';trust.write_bytes(canonical({'version':2,'roots':['a1'*32]}))
            app={'account_id':'fixture','navigation_helper':str(root/'wechat-uia.exe'),'sqlcipher_library':'@resources/bin/sqlcipher.dll',
                'codex_provider':{'binary':'@resources/provider/codex.exe','sha256':hashlib.sha256(provider.read_bytes()).hexdigest(),
                    'workspace':str(data/'source'),
                    'tls_bundle':'@resources/provider/ca-bundle.pem','tls_sha256':hashlib.sha256(ca.read_bytes()).hexdigest()}}
            config={'version':2,'application_module':'axr_applications.wechat','deployment':{'owner_user':'S-1-5-21-1-2-3-4',
                'state':str(data/'state/wechat'),'endpoint':r'\\.\pipe\Stellaria.AXR.fixture','application':app,
                'credential_import':{'path':str(area/'never-read.key'),'sha256':'a1'*32}}}
            def checked(path):
                value=json.loads((Path(path)/'installation-review.json').read_bytes());actual=inventory(path)
                actual.pop('installation-review.json');actual.pop('runtime/owner-key.json',None)
                self.assertEqual(actual,value['files'])
            with patch.object(installer,'administrator'),patch.object(installer,'protect') as acl,patch.object(installer.native,'windows_installation_root',return_value=str(root)),patch.object(
                    installer.native,'windows_data_root',return_value=str(data)),patch.object(installer.native,'verify_windows_installation',side_effect=checked):
                result=installer.install(self.package,configuration=config,local_assets={'codex':provider,'ca':ca,'hello_trust':trust})
            self.assertTrue(result['installed']);self.assertFalse(result['wechat_authorized']);self.assertFalse(result['service_started'])
            self.assertEqual(json.loads((data/'deployment.json').read_bytes()),config)
            self.assertFalse((root/'deployment.json').exists());self.assertFalse((area/'never-read.key').exists())
            self.assertTrue(any(c.kwargs.get('reader')==config['deployment']['owner_user'] and not c.kwargs.get('public') for c in acl.call_args_list))
            self.assertNotIn('credential_import',(root/'installation-review.json').read_text())

@unittest.skipUnless(sys.platform=='win32','Windows fixed service control')
class FixedService(unittest.TestCase):
    def setUp(self):
        self.controller=ServiceController();self.real=self.controller.api;self.api=Mock(wraps=self.real)
        for name in ('SC_MANAGER_CONNECT','SC_MANAGER_CREATE_SERVICE','SERVICE_QUERY_CONFIG','SERVICE_QUERY_STATUS','SERVICE_CHANGE_CONFIG',
            'SERVICE_START','SERVICE_STOP','SERVICE_WIN32_OWN_PROCESS','SERVICE_DEMAND_START','SERVICE_ERROR_NORMAL','SERVICE_ALL_ACCESS',
            'SERVICE_STOPPED','SERVICE_RUNNING','SERVICE_NO_CHANGE','SERVICE_CONTROL_STOP'):
            setattr(self.api,name,getattr(self.real,name))
        self.controller.api=self.api
        self.api.OpenSCManager=Mock(return_value='manager');self.api.OpenService=Mock(return_value='service');self.api.CloseServiceHandle=Mock()
        self.api.QueryServiceConfig=Mock(return_value=(self.real.SERVICE_WIN32_OWN_PROCESS,self.real.SERVICE_DEMAND_START,
            self.real.SERVICE_ERROR_NORMAL,self.controller.command('serve'),'',0,[], 'LocalSystem','AXR'))
        self.api.ChangeServiceConfig=Mock();self.api.StartService=Mock();self.api.ControlService=Mock()
        self.admin=patch('scripts.windows_service.administrator');self.admin.start();self.addCleanup(self.admin.stop)
        self.verify=patch('scripts.windows_service.native.verify_windows_installation');self.verify.start();self.addCleanup(self.verify.stop)
    def state(self,state,exit=0):return (self.real.SERVICE_WIN32_OWN_PROCESS,state,0,exit,0,0,0)
    def test_one_shot_setup_returns_to_demand_service_without_starting_operational_loop(self):
        self.api.QueryServiceStatus=Mock(side_effect=[self.state(self.real.SERVICE_STOPPED)]*3)
        value=self.controller.run('initialize')
        self.assertEqual(value,{'completed':'initialize','authorization_restored':False,'service_started':False})
        self.api.StartService.assert_called_once_with('service',None)
        commands=[c.args[4] for c in self.api.ChangeServiceConfig.call_args_list]
        self.assertEqual(commands,[self.controller.command('initialize'),self.controller.command('serve')])
        self.assertEqual(self.api.CloseServiceHandle.call_count,2)
    def test_failed_setup_is_terminal_and_does_not_retry_or_leave_setup_mode(self):
        self.api.QueryServiceStatus=Mock(side_effect=[self.state(self.real.SERVICE_STOPPED),self.state(self.real.SERVICE_STOPPED,1),self.state(self.real.SERVICE_STOPPED,1)])
        with self.assertRaisesRegex(AXRError,'operation_failed'):self.controller.run('initialize')
        self.api.StartService.assert_called_once();self.assertEqual(self.api.ChangeServiceConfig.call_args.args[4],self.controller.command('serve'))
    def test_running_or_reconfigured_service_is_not_replaced(self):
        self.api.QueryServiceStatus=Mock(return_value=self.state(self.real.SERVICE_RUNNING))
        with self.assertRaisesRegex(AXRError,'must_be_stopped'):self.controller.run('refresh')
        self.api.ChangeServiceConfig.assert_not_called();self.api.StartService.assert_not_called()
        original=self.api.QueryServiceConfig.return_value
        for index,value in [(0,self.real.SERVICE_WIN32_OWN_PROCESS|256),(1,2),(3,'untrusted.exe --service'),(7,'untrusted-owner')]:
            row=list(original);row[index]=value;self.api.QueryServiceConfig.return_value=tuple(row)
            with self.assertRaisesRegex(AXRError,'configuration_changed'):self.controller.status()
    def test_stop_preserves_state_and_never_restarts(self):
        self.api.QueryServiceStatus=Mock(side_effect=[self.state(self.real.SERVICE_RUNNING),self.state(self.real.SERVICE_STOPPED)])
        self.assertTrue(self.controller.stop()['state_retained']);self.api.ControlService.assert_called_once_with('service',self.real.SERVICE_CONTROL_STOP)
        self.api.StartService.assert_not_called();self.api.ChangeServiceConfig.assert_not_called()
