"""Real MCP transport tests with simulated WeChat only. No UI or live sends."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = Path(__file__).resolve().parent
        scratch = self.root / ".test-work"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.config_path = Path(self.temp.name) / "config.json"
        config = json.loads((self.root / "config.example.json").read_text(encoding="utf-8"))
        self.config_path.write_text(json.dumps(config), encoding="utf-8")

    async def asyncTearDown(self):
        self.temp.cleanup()

    def parameters(self):
        return StdioServerParameters(command=sys.executable, args=[
            str(self.root / "server.py"), "--demo", "--config", str(self.config_path)],
            cwd=str(self.root), env={"PYTHONIOENCODING": "utf-8"})

    async def test_protocol_and_contact_management(self):
        async with asyncio.timeout(30):
            async with stdio_client(self.parameters()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual({t.name for t in tools.tools}, {
                        "wechat_status", "get_reply_contacts", "set_reply_contacts",
                        "poll_messages", "reply_to_message", "dismiss_message"})
                    status = await session.call_tool("wechat_status", {})
                    self.assertFalse(status.isError)
                    contacts = await session.call_tool("get_reply_contacts", {})
                    self.assertFalse(contacts.isError)
                    updated = await session.call_tool("set_reply_contacts", {"remark_names": ["模拟备注"]})
                    self.assertFalse(updated.isError)
                    self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8"))["active_contacts"], ["模拟备注"])
                    polled = await session.call_tool("poll_messages", {})
                    self.assertFalse(polled.isError)
                    resource = await session.read_resource("wechat://policy")
                    self.assertTrue(resource.contents)
                    cleared = await session.call_tool("set_reply_contacts", {"remark_names": []})
                    self.assertFalse(cleared.isError)

    async def test_invalid_contact_and_unknown_message_rejected(self):
        async with asyncio.timeout(30):
            async with stdio_client(self.parameters()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    invalid = await session.call_tool("set_reply_contacts", {"remark_names": [""]})
                    self.assertTrue(invalid.isError)
                    self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8"))["active_contacts"], [])
                    reply = await session.call_tool("reply_to_message", {"message_id": 9999, "text": "不应发送"})
                    self.assertTrue(reply.isError)


if __name__ == "__main__":
    unittest.main()
