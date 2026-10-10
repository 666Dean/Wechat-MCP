# SPDX-License-Identifier: MIT
"""Real stdio protocol, synthetic adapter, out-of-band trusted approval."""
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
try:
    import axr
except ModuleNotFoundError as exc:
    if exc.name=="axr":raise unittest.SkipTest("AXR optional: install requirements.axr.txt and native SDK to run these gates") from exc
    raise
from axr.guard import Guard
from axr.journal import Journal
from axr.storage import Vault
from axr.owner import approve

SCRIPT='''from pathlib import Path
import sys,time
from mcp.server import MCPServer
from axr.guard import Guard
from axr.journal import Journal
from axr.storage import Vault
from axr_integration.service import Service,register
root=Path(sys.argv[1])
class Store:
    directory=root
    vault=Vault(b'v'*32)
    guard=Guard(root/'guard.db',b'g'*32)
    journal=Journal(root/'journal.db',vault)
    def config(self):return {'principal':'fixture-agent','purpose':'fixture','account_id':'fixture-account','agent_destination':'model:fixture','mode':'wcdb','conversations':[{'conversation_id':'fixture-chat','display_name':'fixture'}]}
    def close(self):self.journal.close();self.guard.close()
class Adapter:
    def status(self):return {'mode':'synthetic-only','send_available':False}
    def search(self,cid,**kwargs):return {'messages':[{'reference':'fixture-ref','text':'synthetic untrusted content','created':time.time(),'outgoing':False}],'coverage':'synthetic','cursor':None,'has_more':False}
    def close(self):pass
store=Store();service=Service(root,store=store,adapter=Adapter(),leases=root/'leases')
store.guard._issue_owner(principal='fixture-agent',resource=service.resource('fixture-chat'),operations=['messages.read'],purpose='fixture',expires_at=time.time()+120,max_uses=10)
mcp=MCPServer('AXR fixture');register(mcp,service)
try:mcp.run(transport='stdio')
finally:service.close()
'''
class Protocol(unittest.IsolatedAsyncioTestCase):
    async def test_scoped_read_disclosure_out_of_band_approval_and_no_owner_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            args=StdioServerParameters(command=sys.executable,args=['-c',SCRIPT,tmp],cwd=str(Path(__file__).parent))
            async with asyncio.timeout(30):
                async with stdio_client(args) as (read,write):
                    async with ClientSession(read,write) as client:
                        await client.initialize();tools=await client.list_tools()
                        names={t.name for t in tools.tools};self.assertIn('axr_execute',names)
                        self.assertNotIn('approve',names);self.assertNotIn('grant',names)
                        result=await client.call_tool('wechat_read_context',{'conversation_id':'fixture-chat'})
                        self.assertFalse(result.is_error);metadata=json.loads(result.content[0].text)
                        self.assertEqual(metadata['state'],'Completed');self.assertNotIn('synthetic untrusted content',json.dumps(metadata))
                        proposed=await client.call_tool('wechat_disclose_context',{'conversation_id':'fixture-chat','context_id':metadata['result']['context_id']})
                        job=json.loads(proposed.content[0].text);self.assertEqual(job['state'],'AwaitingApproval')
                        denied=await client.call_tool('axr_execute',{'job_id':job['id']});self.assertTrue(denied.is_error)
                        # Fixture-only parent acts as trusted owner; production uses OS-authenticated CLI.
                        owner=SimpleNamespace(guard=Guard(root/'guard.db',b'g'*32),journal=Journal(root/'journal.db',Vault(b'v'*32)))
                        try:approve(owner,job['id'],'fixture-agent')
                        finally:owner.guard.close();owner.journal.close()
                        result=await client.call_tool('axr_execute',{'job_id':job['id']})
                        self.assertFalse(result.is_error);body=json.loads(result.content[0].text)
                        self.assertEqual(body['state'],'Completed');self.assertEqual(body['result']['messages'][0]['text'],'synthetic untrusted content')
                        forbidden=await client.call_tool('wechat_read_context',{'conversation_id':'forged-chat'});self.assertTrue(forbidden.is_error)
if __name__=='__main__':unittest.main()
