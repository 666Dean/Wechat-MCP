# SPDX-License-Identifier: MIT
"""Multiple real MCP clients, one exclusive synthetic executor."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from contextlib import AsyncExitStack
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from axr.aet import Action,Resource
from axr.guard import Guard
from axr.journal import Journal
from axr.storage import Vault

SCRIPT='''import sys,time
from pathlib import Path
from mcp.server import MCPServer
from axr.aet import AXRError
from axr.guard import Guard
from axr.journal import Journal
from axr.storage import Vault
from axr_integration.service import Service,register
from axr_integration import lifecycle
root=Path(sys.argv[1])
class Store:
 def __init__(self,*args):
  self.directory=root;self.vault=Vault(b'v'*32)
  self.guard=Guard(root/'guard.db',b'g'*32);self.journal=Journal(root/'journal.db',self.vault)
 def config(self):return {'principal':'fixture-agent','purpose':'fixture','account_id':'fixture-account',
  'agent_destination':'model:fixture','mode':'wcdb','conversations':[{'conversation_id':'fixture-chat','display_name':'fixture'}]}
 def close(self):self.journal.close();self.guard.close()
class Adapter:
 def status(self):return {'mode':'synthetic-only','send_available':False}
 def search(self,*args,**kwargs):return {'messages':[],'coverage':'synthetic','has_more':False,'cursor':None}
 def close(self):pass
def factory(state,manual_replies=False):
 if len(sys.argv)>2:raise AXRError('fixture_owner_unavailable')
 return Service(root,store=Store(),adapter=Adapter(),leases=root/'leases',manual_replies=manual_replies)
lifecycle.OwnerStore=Store
s=lifecycle.DeferredService(root,manual_replies=True,factory=factory)
s.start_listener()
mcp=MCPServer('deferred fixture');register(mcp,s)
try:mcp.run(transport='stdio')
finally:s.close()
'''


class DeferredProtocol(unittest.IsolatedAsyncioTestCase):
    async def connect(self,stack,root,unavailable=False):
        params=StdioServerParameters(command=sys.executable,args=['-c',SCRIPT,str(root)]+(['unavailable'] if unavailable else []),cwd=str(Path(__file__).parent))
        errors=stack.enter_context(open(os.devnull,'w'))
        r,w=await stack.enter_async_context(stdio_client(params,errlog=errors))
        c=await stack.enter_async_context(ClientSession(r,w));await c.initialize()
        return c

    async def call(self,c,name,args=None):
        result=await c.call_tool(name,args or {})
        self.assertFalse(result.is_error)
        return json.loads(result.content[0].text)

    async def test_two_clients_discover_busy_tool_and_handoff_without_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            async with asyncio.timeout(30),AsyncExitStack() as b_stack,AsyncExitStack() as a_stack:
                b=await self.connect(b_stack,root);a=await self.connect(a_stack,root)
                self.assertEqual(len((await a.list_tools()).tools),26)
                self.assertEqual((await self.call(a,'wechat_status'))['initialization']['state'],'idle')
                self.assertEqual((await self.call(b,'wechat_status'))['initialization']['state'],'idle')
                await self.call(a,'wechat_find_conversations')
                owner=Journal(root/'journal.db',Vault(b'v'*32))
                try:
                    jid=owner.propose(Action('fixture-agent',Resource('wechat','fixture-account','fixture-chat'),'messages.read','fixture',{}))
                    for state in ('PolicyChecked','Ready','Prepared','Executing'):owner.transition(jid,'fixture-agent',state)
                    denied=await b.call_tool('wechat_read_context',{'conversation_id':'fixture-chat'})
                    self.assertTrue(denied.is_error)
                    blocked=await self.call(b,'wechat_status')
                    self.assertEqual(blocked['initialization']['state'],'busy')
                    self.assertEqual(blocked['initialization']['reason'],'account_or_journal_busy')
                    self.assertEqual(owner.get(jid,'fixture-agent')['state'],'Executing')
                    await a_stack.aclose()
                    await self.call(b,'wechat_find_conversations')
                    self.assertEqual(owner.get(jid,'fixture-agent')['state'],'Unknown')
                    self.assertEqual((await self.call(b,'wechat_status'))['initialization']['state'],'active')
                    unread=await self.call(b,'wechat_read_context',{'conversation_id':'fixture-chat'})
                    self.assertEqual(unread['state'],'AwaitingApproval')
                finally:owner.close()

    async def test_unavailable_executor_does_not_close_mcp_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            async with asyncio.timeout(20),AsyncExitStack() as stack:
                c=await self.connect(stack,Path(tmp),True)
                self.assertEqual(len((await c.list_tools()).tools),26)
                failed=await c.call_tool('wechat_find_conversations',{})
                self.assertTrue(failed.is_error)
                status=await self.call(c,'wechat_status')
                self.assertFalse(status['initialization']['operational'])
                self.assertFalse(status['platform']['send_available'])
