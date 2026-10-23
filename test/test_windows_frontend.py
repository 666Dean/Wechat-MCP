# SPDX-License-Identifier: MIT
"""Real no-network client isolation plus fixed MCP routing; synthetic data only."""
import io,json,os,shutil,socket,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from axr import _axr_native as native
from axr.aet import AXRError,canonical
from axr.ipc import PeerRegistry,process_identity,windows_client_sandbox
from axr.storage import Vault
from axr.deployment import OwnerDeployment
from test.test_security_authority import ProtectedStore
from axr_applications import wechat_frontend as frontend


@unittest.skipUnless(sys.platform=='win32','Windows native MCP frontend')
class WindowsFrontend(unittest.TestCase):
    def setUp(self):
        probe=os.environ.get('WECHAT_TEST_WINDOWS_FRONTEND')
        if not probe:self.skipTest('compiled frontend witness required')
        if native.security_release:self.skipTest('reference fixture image only')
        self.directory=tempfile.TemporaryDirectory(prefix='AXR 客户端 fixture ');self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve();self.bin=self.root/'bin';self.bin.mkdir()
        self.program=self.bin/'axr-frontend.exe';shutil.copyfile(probe,self.program)
        for dependency in Path(probe).parent.glob('*.dll'):shutil.copyfile(dependency,self.bin/dependency.name)
        import win32con,win32security
        sid=win32security.ConvertStringSidToSid('S-1-15-2-2')
        for path in (self.bin,*self.bin.iterdir()):
            descriptor=win32security.GetNamedSecurityInfo(str(path),win32security.SE_FILE_OBJECT,win32security.DACL_SECURITY_INFORMATION)
            acl=descriptor.GetSecurityDescriptorDacl();acl.AddAccessAllowedAce(win32security.ACL_REVISION,win32con.GENERIC_READ|win32con.GENERIC_EXECUTE,sid)
            win32security.SetNamedSecurityInfo(str(path),win32security.SE_FILE_OBJECT,win32security.DACL_SECURITY_INFORMATION,None,None,acl,None)
        self.outside=self.root/'other-source.txt';self.outside.write_text('synthetic other source')
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen();self.addCleanup(self.listener.close)
    def run_client(self,**changes):
        request={'outside':str(self.outside),'port':self.listener.getsockname()[1],**changes}
        with patch.dict(os.environ,{'AXR_SYNTHETIC_PARENT_SECRET':'synthetic-parent-value'}):
            result=subprocess.run([str(self.program)],input=canonical(request)+b'\n',capture_output=True,timeout=10)
        frames=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(result.returncode,0,frames)
        return frames
    def test_actual_client_has_no_network_or_other_source_and_only_forwards_stdio(self):
        ready,value=self.run_client();self.assertTrue(ready['ready'])
        self.assertEqual(ready['sandbox']['profile'],'windows-appcontainer-mcp-v2')
        self.assertIs(ready['sandbox']['network_allowed'],False);self.assertIs(ready['sandbox']['all_application_packages_access'],False)
        self.assertEqual(value,{'outside_read':False,'inherited_secret':False,'loopback_connected':False})
        other,_=self.run_client();self.assertNotEqual(other['sandbox']['appcontainer_sid'],ready['sandbox']['appcontainer_sid'])
    def test_hidden_child_entry_cannot_run_in_an_ordinary_process(self):
        result=subprocess.run([str(self.program),'--sandbox-mcp'],capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0);self.assertEqual(json.loads(result.stdout)['error'],'windows_frontend_sandbox_required')
    def test_real_client_registration_and_acceptance_revalidate_os_token_and_exact_package(self):
        process=subprocess.Popen([str(self.program)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        try:
            ready=json.loads(process.stdout.readline());actual=process_identity(ready['sandbox']['pid']);witness=windows_client_sandbox(actual)
            store=SimpleNamespace(directory=self.root/'registry',vault=Vault(b'v'*32));store.directory.mkdir()
            deployment=OwnerDeployment(ProtectedStore(),store.vault,development_fixture=True)
            deployment.enroll(self.bin,[{'path':self.program.name,'roles':['client']}],lambda:actual['user'])
            registry=PeerRegistry(store,owner_user=actual['user'],owner_deployment=deployment)
            registry.enroll(actual,'client','synthetic:client',lambda:actual['user'],managed_sandbox=witness)
            self.assertEqual(registry.accept(actual).role,'client')
            registry.rows[0]['sandbox']={**witness,'appcontainer_sid':'S-1-15-2-1'}
            with self.assertRaisesRegex(AXRError,'not_enrolled'):registry.accept(actual)
            process.communicate(canonical({'outside':str(self.outside),'port':self.listener.getsockname()[1]})+b'\n',timeout=5)
            self.assertEqual(process.returncode,0)
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=3)
            for stream in (process.stdin,process.stdout):stream.close()
    def test_lpac_can_reach_identity_checked_low_integrity_pipe_without_network(self):
        endpoint=r'\\.\pipe\Stellaria.AXR.frontend-fixture-'+os.urandom(12).hex()
        server=subprocess.Popen([str(self.program),'--pipe-server',endpoint],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        try:
            actual=json.loads(server.stdout.readline())
            ready,result=self.run_client(pipe=endpoint);self.assertTrue(result['pipe_connected']);self.assertEqual(result['server_identity'],actual)
            output=server.communicate(timeout=5)[0];self.assertEqual(server.returncode,0)
            self.assertEqual(json.loads(output),{'received':'probe'})
        finally:
            if server.poll() is None:server.kill();server.wait(timeout=3)
            server.stdout.close()


@unittest.skipUnless(sys.platform=='win32','Windows fixed frontend protocol')
class WindowsFrontendProtocol(unittest.TestCase):
    def test_pinned_build_cannot_enroll_an_ordinary_process_using_self_reported_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            actual=process_identity(os.getpid());owner=Mock(return_value=actual['user'])
            store=SimpleNamespace(directory=Path(directory),vault=Vault(b'v'*32))
            deployment=OwnerDeployment(ProtectedStore(),store.vault,development_fixture=True)
            image=Path(actual['image']);deployment.enroll(image.parent,[{'path':image.name,'roles':['client']}],lambda:actual['user'])
            registry=PeerRegistry(store,owner_user=actual['user'],owner_deployment=deployment)
            with self.assertRaisesRegex(AXRError,'managed_sandbox_required'):
                registry.enroll(actual,'client','synthetic:client',owner,managed_sandbox={'pid':actual['pid'],'birth':actual['birth'],'profile':'trusted'})
            owner.assert_not_called();self.assertEqual(registry.rows,[])
    def run_protocol(self,requests,connect=None):
        source=io.BytesIO(b''.join(canonical(value)+b'\n' for value in requests));output=io.BytesIO()
        with patch.object(frontend.sys,'stdin',SimpleNamespace(buffer=source)),patch.object(frontend.sys,'stdout',SimpleNamespace(buffer=output)),patch.object(
                frontend,'connect_windows',side_effect=connect) as connector:
            frontend.main('synthetic-runtime')
        return [json.loads(line) for line in output.getvalue().splitlines()],connector
    def test_discovery_is_available_without_service_configuration_or_authority(self):
        values,connector=self.run_protocol([{'id':1,'method':'initialize'},{'id':2,'method':'tools/list'}])
        self.assertEqual(values[0]['result']['serverInfo']['name'],'wechat-axr');self.assertEqual(len(values[1]['result']['tools']),6)
        connector.assert_not_called()
    def test_fixed_tools_route_and_close_without_accepting_policy_or_paths(self):
        client=Mock();client.request.return_value={'owner_authorized':False}
        values,connector=self.run_protocol([{'id':1,'method':'tools/call','params':{'name':'wechat_status'}},
            {'id':2,'method':'tools/call','params':{'name':'wechat_status','arguments':{'endpoint':'untrusted'}}}],lambda *args:client)
        client.request.assert_called_once_with('WeChat',method='wechat_status',arguments={});client.close.assert_called_once()
        self.assertFalse(values[0]['result']['isError']);self.assertIn('error',values[1]);connector.assert_called_once()
    def test_connection_failure_is_terminal_and_does_not_retry(self):
        values,connector=self.run_protocol([{'id':1,'method':'tools/call','params':{'name':'wechat_status'}}],AXRError('synthetic_closed'))
        connector.assert_called_once();value=json.loads(values[0]['result']['content'][0]['text']);self.assertFalse(value['retry']);self.assertEqual(value['error'],'synthetic_closed')
    def test_server_profile_requires_fixed_system_host(self):
        root=Path(native.windows_installation_root());server={'user':'S-1-5-18','image':str(root/'axr-authority.exe'),'app_container':False}
        connection={'endpoint':r'\\.\pipe\Stellaria.AXR.fixture','server':server}
        with patch('axr_integration.authority_frontend.load_connection',return_value=connection),patch.object(frontend.AuthorityClient,'connect') as connect:
            frontend.connect_windows('synthetic-runtime');connect.assert_called_once_with(connection['endpoint'],server)
            for values in ({'user':'S-1-5-21-1-2-3-4'},{'image':str(root/'other.exe')},{'app_container':True}):
                with patch('axr_integration.authority_frontend.load_connection',return_value={**connection,'server':{**server,**values}}):
                    with self.assertRaisesRegex(AXRError,'installed_identity_required'):frontend.connect_windows('synthetic-runtime')
