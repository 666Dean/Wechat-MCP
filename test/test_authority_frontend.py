# SPDX-License-Identifier: MIT
"""Windows named-pipe authority behind real MCP stdio, using synthetic data."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from axr.aet import AXRError
from axr_integration.authority_frontend import AuthorityFrontend,load_profile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SCRIPT = r'''
import os,secrets,sys,threading,time
from mcp.server import MCPServer
from axr.aet import canonical
from axr.ipc import PeerRegistry,process_identity
from axr.authority_server import AuthorityServer
from axr_integration.authority_frontend import AuthorityFrontend,register
from test.test_authority_mcp import application_fixture
f=application_fixture()
review=f.call(f.owner,'Authorize',phase='review-approval-setting',manual_approval_required=False)
f.call(f.owner,'Authorize',phase='approve-approval-setting',manual_approval_required=False,
    challenge_id=review['challenge']['nonce'],owner_signature=f.ownerkey.sign(canonical(review['challenge'])).hex())
actual=process_identity(os.getpid())
registry=PeerRegistry(f.store,development_fixture=True)
registry.enroll(actual,'client',f.client.principal,lambda:actual['user'])
f.k.integrity.persist()
endpoint=r'\\.\pipe\Stellaria.AXR.mcp-fixture.'+secrets.token_hex(12)
server=AuthorityServer(f.k,registry,endpoint)
thread=threading.Thread(target=server.serve,daemon=True)
thread.start()
deadline=time.monotonic()+3
while server.listener is None:
    if not thread.is_alive() or time.monotonic()>deadline:raise RuntimeError('fixture_listener_failed')
    time.sleep(.01)
expected=dict(actual)
if len(sys.argv)>1 and sys.argv[1]=='changed-peer':expected['birth']+='1'
frontend=AuthorityFrontend({'endpoint':endpoint,'server':expected,'capability':f.capability})
mcp=MCPServer('Windows independent authority fixture')
register(mcp,frontend)
try:mcp.run(transport='stdio')
finally:
    frontend.close();server.close();thread.join(timeout=2);f.doCleanups()
'''


class FrontendFailure(unittest.TestCase):
    def test_transport_loss_never_reconnects_or_replays_the_request(self):
        calls=[]
        class Channel:
            def request(self,*args,**kwargs):
                calls.append(True)
                raise AXRError('ipc_pipe_disconnected')
            def close(self):pass
        frontend=AuthorityFrontend({'endpoint':'unused','server':{},'capability':{}},connect=lambda *args:Channel())
        self.addCleanup(frontend.close)
        with self.assertRaisesRegex(AXRError,'ipc_pipe_disconnected'):frontend.call('read_context')
        with self.assertRaisesRegex(AXRError,'restart_required'):frontend.call('read_context')
        self.assertEqual(calls,[True])

    @unittest.skipUnless(sys.platform=='win32','Windows authority peer profile')
    def test_owner_profile_accepts_only_local_pipe_and_exact_os_peer_fields(self):
        import os
        from axr.ipc import process_identity
        profile={'version':2,'endpoint':r'\\.\pipe\Stellaria.AXR.fixture',
                 'server':process_identity(os.getpid()),'capability':{'fixture':True}}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'authority-profile.json'
            path.write_text(json.dumps(profile),encoding='utf8')
            self.assertEqual(load_profile(path),profile)
            for change in ({'version':2.0},{'endpoint':r'\\remote-host\pipe\fixture'},
                           {'owner':True},{'server':{**profile['server'],'signature_valid':'true'}}):
                with self.subTest(change=change):
                    path.write_text(json.dumps({**profile,**change}),encoding='utf8')
                    with self.assertRaises(AXRError):load_profile(path)
            path.write_text('{"version":2,"version":2}',encoding='utf8')
            with self.assertRaises(AXRError):load_profile(path)


@unittest.skipUnless(sys.platform=='win32','Windows MCP named-pipe integration')
class WindowsMCPProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_read_disclose_and_draft_through_stdio_and_authenticated_pipe(self):
        parameters=StdioServerParameters(command=sys.executable,args=['-c',SCRIPT],
                                         cwd=str(Path(__file__).resolve().parents[1]))
        async with asyncio.timeout(40):
            async with stdio_client(parameters) as (reader,writer):
                async with ClientSession(reader,writer) as client:
                    await client.initialize()
                    names={tool.name for tool in (await client.list_tools()).tools}
                    self.assertEqual(names,{'wechat_status','wechat_read_context','wechat_disclose_context',
                                            'wechat_prepare_reply','wechat_submit_reply','wechat_reply_status',
                                            'axr_execute','axr_receipt'})
                    status=await client.call_tool('wechat_status',{})
                    self.assertFalse(status.is_error)
                    self.assertFalse(json.loads(status.content[0].text)['manual_approval_required'])
                    read=await client.call_tool('wechat_read_context',{'conversation_id':'fixture-peer'})
                    self.assertFalse(read.is_error)
                    metadata=json.loads(read.content[0].text)
                    self.assertNotIn('synthetic message',json.dumps(metadata))
                    handle=metadata['result']['context_id']
                    disclosed=await client.call_tool('wechat_disclose_context',{'conversation_id':'fixture-peer','context_id':handle})
                    self.assertFalse(disclosed.is_error)
                    body=json.loads(disclosed.content[0].text)
                    self.assertIn('synthetic message',json.dumps(body))
                    self.assertNotIn('fixture-secret',json.dumps(body))
                    draft=await client.call_tool('wechat_prepare_reply',{'conversation_id':'fixture-peer',
                        'text':'synthetic reply','context_ids':[handle]})
                    self.assertFalse(draft.is_error)
                    result=json.loads(draft.content[0].text)
                    self.assertEqual(result['result']['submission'],'human')
                    self.assertFalse(result['agent_sent'])
                    receipt=await client.call_tool('axr_receipt',{'execution_id':result['execution_id']})
                    self.assertFalse(receipt.is_error)
                    self.assertEqual(json.loads(receipt.content[0].text)['state'],'Completed')

    async def test_changed_os_server_instance_never_returns_data(self):
        parameters=StdioServerParameters(command=sys.executable,args=['-c',SCRIPT,'changed-peer'],
                                         cwd=str(Path(__file__).resolve().parents[1]))
        async with asyncio.timeout(30):
            async with stdio_client(parameters) as (reader,writer):
                async with ClientSession(reader,writer) as client:
                    await client.initialize()
                    status=await client.call_tool('wechat_status',{})
                    value=json.loads(status.content[0].text)
                    self.assertFalse(value['authority_connected'])
                    read=await client.call_tool('wechat_read_context',{'conversation_id':'fixture-peer'})
                    self.assertTrue(read.is_error)
                    self.assertNotIn('synthetic message',str(read.content))
