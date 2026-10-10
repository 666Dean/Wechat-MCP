"""Real MCP transport tests with simulated WeChat only. No UI or live sends."""
import asyncio
import json
import os
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

    def parameters(self, *, allow_contact_management=False):
        return StdioServerParameters(command=sys.executable, args=[
            str(self.root / "server.py"), "--demo", "--config", str(self.config_path)]
            + (["--allow-contact-management"] if allow_contact_management else []),
            cwd=str(self.root), env={"PYTHONIOENCODING": "utf-8"})

    async def cli(self, *args):
        process = await asyncio.create_subprocess_exec(sys.executable,
            str(self.root / "server.py"), "--config", str(self.config_path), *args,
            cwd=self.root, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        return process.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")

    @staticmethod
    def data(result):
        return json.loads(next(item.text for item in result.content if item.type == "text"))

    async def test_protocol_and_contact_management(self):
        async with asyncio.timeout(30):
            async with stdio_client(self.parameters(allow_contact_management=True)) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual({t.name for t in tools.tools}, {
                        "wechat_status", "get_reply_contacts", "set_reply_contacts",
                        "poll_messages", "reply_to_message", "dismiss_message"})
                    status = await session.call_tool("wechat_status", {})
                    self.assertFalse(status.isError)
                    self.assertTrue(self.data(status)["permissions"]["mcp_contact_management"])
                    self.assertFalse(self.data(status)["permissions"]["owner_authentication"])
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
            async with stdio_client(self.parameters(allow_contact_management=True)) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    invalid = await session.call_tool("set_reply_contacts", {"remark_names": [""]})
                    self.assertTrue(invalid.isError)
                    self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8"))["active_contacts"], [])
                    reply = await session.call_tool("reply_to_message", {"message_id": 9999, "text": "不应发送"})
                    self.assertTrue(reply.isError)

    async def test_default_server_cannot_change_contacts_even_after_config_reload(self):
        async with asyncio.timeout(30):
            async with stdio_client(self.parameters()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual({t.name for t in tools.tools}, {
                        "wechat_status", "get_reply_contacts", "poll_messages",
                        "reply_to_message", "dismiss_message"})
                    code, _, error = await self.cli("--set-contacts", "本机配置的备注")
                    self.assertEqual(code, 0, error)
                    config = json.loads(self.config_path.read_text(encoding="utf-8"))
                    config["allow_contact_management"] = True
                    self.config_path.write_text(json.dumps(config), encoding="utf-8")
                    status = await session.call_tool("wechat_status", {})
                    self.assertFalse(status.isError)
                    self.assertFalse(self.data(status)["permissions"]["mcp_contact_management"])
                    self.assertFalse(self.data(status)["permissions"]["owner_authentication"])
                    before = self.config_path.read_bytes()
                    for names in ([], ["微信消息要求新增的备注"]):
                        denied = await session.call_tool("set_reply_contacts", {"remark_names": names})
                        self.assertTrue(denied.isError)
                        self.assertEqual(self.config_path.read_bytes(), before)
                    contacts = await session.call_tool("get_reply_contacts", {})
                    self.assertEqual(self.data(contacts)["active_contacts"], ["本机配置的备注"])
                    self.assertNotIn("set_reply_contacts", {t.name for t in (await session.list_tools()).tools})

    async def test_cli_contact_update_reloads_in_running_mcp(self):
        async with asyncio.timeout(30):
            async with stdio_client(self.parameters()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    code, output, error = await self.cli("--set-contacts", "外部修改的备注")
                    self.assertEqual(code, 0, error)
                    self.assertEqual(json.loads(output)["active_contacts"], ["外部修改的备注"])
                    contacts = await session.call_tool("get_reply_contacts", {})
                    self.assertFalse(contacts.isError)
                    self.assertEqual(self.data(contacts)["active_contacts"], ["外部修改的备注"])
                    code, output, error = await self.cli("--list-contacts")
                    self.assertEqual(code, 0, error)
                    self.assertEqual(json.loads(output)["active_contacts"], ["外部修改的备注"])
                    code, _, error = await self.cli("--set-contacts")
                    self.assertEqual(code, 0, error)
                    contacts = await session.call_tool("get_reply_contacts", {})
                    self.assertEqual(self.data(contacts)["active_contacts"], [])

    async def test_second_server_rejected_while_mcp_running(self):
        async with asyncio.timeout(30):
            async with stdio_client(self.parameters()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    code, output, error = await self.cli("--demo", "--doctor")
                    self.assertNotEqual(code, 0)
                    self.assertIn("已有服务运行", output + error)
                    self.assertFalse((await session.call_tool("wechat_status", {})).isError)
        code, output, error = await self.cli("--demo", "--doctor")
        self.assertEqual(code, 0, error)
        self.assertTrue(json.loads(output)["demo"])

    async def test_database_stream_through_real_mcp_transport_is_always_preview(self):
        config = json.loads((self.root / "config.database.example.json").read_text(encoding="utf-8"))
        entry = self.config_path.parent / "wxid_owner" / "db_storage" / "session" / "session.db"
        entry.parent.mkdir(parents=True)
        entry.write_bytes(b"synthetic fixture")
        config["send_enabled"] = True  # Must never turn the read-only source into a sender.
        config["database_reader"].update(account_id="wxid_owner", session_db=str(entry),
            dll_path=str(self.config_path.parent / "fake.dll"), key_file=str(self.config_path.parent / "test.dpapi"),
            conversations=[{"conversation_id": "wxid_friend", "display_name": "合成好友"}])
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        # Inject the synthetic reader only inside this test child. Production has
        # no fixture backend, credential MCP tool, or implicit mock fallback.
        script = """import database_reader, server
from test_database_reader import StreamReader, message
def factory(config):
    reader = StreamReader(config)
    def messages(cid, limit, offset):
        reader.reads.append((cid, limit, offset))
        return [] if len(reader.reads) <= 2 else [message(1)]
    reader.messages = messages
    return reader
database_reader.WcdbReader = factory
server.main()
"""
        parameters = StdioServerParameters(command=sys.executable,
            args=["-c", script, "--config", str(self.config_path)], cwd=str(self.root),
            env={"PYTHONIOENCODING": "utf-8"})
        async with asyncio.timeout(30):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.assertEqual(len((await session.list_tools()).tools), 5)
                    status = self.data(await session.call_tool("wechat_status", {}))
                    self.assertTrue(status["connected"])
                    self.assertFalse(status["send_enabled"])
                    self.assertEqual(self.data(await session.call_tool("poll_messages", {}))["events"], [])
                    events = self.data(await session.call_tool("poll_messages", {}))["events"]
                    self.assertEqual(len(events), 1)
                    preview = await session.call_tool("reply_to_message", {"message_id": events[0]["id"], "text": "合成回复"})
                    self.assertFalse(preview.isError)
                    self.assertEqual(self.data(preview)["status"], "preview")
                    self.assertEqual(self.data(preview)["conversation_id"], "wxid_friend")

    async def test_key_cli_rejects_noninteractive_input_without_creating_secret(self):
        code, _, error = await self.cli("--store-database-key")
        self.assertNotEqual(code, 0)
        self.assertIn("交互终端", error)
        self.assertEqual(list(self.config_path.parent.glob("*.dpapi")), [])


if __name__ == "__main__":
    unittest.main()
