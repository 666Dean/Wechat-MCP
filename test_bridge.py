import json
import tempfile
import unittest
from pathlib import Path
from bridge import Bridge, MockAdapter


class BridgeTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parent / ".test-work"
        scratch.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        config = json.loads(Path(__file__).with_name("config.example.json").read_text(encoding="utf-8"))
        config["state_file"] = "test.sqlite3"
        config["active_contacts"] = ["测试联系人"]
        self.path = Path(self.tmp.name) / "config.json"
        self.path.write_text(json.dumps(config), encoding="utf-8")
        self.adapter = MockAdapter()
        self.bridge = Bridge(self.path, self.adapter)

    def tearDown(self):
        self.bridge.close()
        self.tmp.cleanup()

    def add(self, text, source="friend", msg_type="text"):
        rows = self.adapter.current["messages"]
        rows.append({"native_id": str(len(rows)+1), "source": source, "type": msg_type, "text": text})

    def event(self):
        self.bridge.poll()
        self.add("你好")
        return self.bridge.poll()["events"][0]["id"]

    def test_history_not_replied(self):
        self.add("历史消息")
        self.assertEqual(self.bridge.poll()["events"], [])

    def test_active_contact_and_duplicate_poll(self):
        mid = self.event()
        self.assertEqual(len(self.bridge.poll()["events"]), 1)
        self.assertEqual(self.bridge.poll()["events"][0]["id"], mid)

    def test_other_friend_needs_explicit_codex(self):
        self.adapter.current["peer"] = "另一个好友"
        self.bridge.poll()
        self.add("你好")
        self.assertEqual(self.bridge.poll()["events"], [])
        self.add("Codex，你好")
        self.assertEqual(len(self.bridge.poll()["events"]), 1)

    def test_self_and_media_filtered(self):
        self.bridge.poll()
        self.add("我的回复", "self")
        self.add("图片", msg_type="image")
        self.assertEqual(self.bridge.poll()["events"], [])

    def test_group_filtered(self):
        self.adapter.current["chat_type"] = "group"
        self.bridge.poll()
        self.add("Codex 你好")
        self.assertEqual(self.bridge.poll()["events"], [])

    def test_preview_identity_no_send(self):
        result = self.bridge.reply(self.event(), "我可以帮你查资料。")
        self.assertEqual(result["status"], "preview")
        self.assertIn("我是 Codex", result["text"])
        self.assertEqual(self.adapter.sent, [])

    def test_send_idempotency(self):
        mid = self.event()
        self.bridge.config["send_enabled"] = True
        self.assertEqual(self.bridge.reply(mid, "你好")["status"], "sent")
        with self.assertRaises(ValueError):
            self.bridge.reply(mid, "你好")
        self.assertEqual(len(self.adapter.sent), 1)

    def test_unknown_send_never_retried(self):
        mid = self.event()
        self.bridge.config["send_enabled"] = True
        def fail(peer, text):
            raise RuntimeError("模拟发送后连接丢失")
        self.adapter.send = fail
        with self.assertRaises(RuntimeError):
            self.bridge.reply(mid, "你好")
        with self.assertRaises(ValueError):
            self.bridge.reply(mid, "重试")

    def test_manual_reply_does_not_disable_agent(self):
        self.bridge.poll()
        self.add("本人回复", "self")
        self.bridge.poll()
        self.add("Codex 继续")
        self.assertEqual(len(self.bridge.poll()["events"]), 1)

    def test_revoked_contact_cannot_send_pending(self):
        mid = self.event()
        self.bridge.config["active_contacts"] = []
        with self.assertRaises(ValueError):
            self.bridge.reply(mid, "你好")

    def test_default_list_is_empty(self):
        config = json.loads(Path(__file__).with_name("config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(config["active_contacts"], [])

    def test_update_normalizes_and_persists(self):
        result = self.bridge.set_contacts([" 新备注 ", "新备注", "第二位"])
        self.assertEqual(result["active_contacts"], ["新备注", "第二位"])
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["active_contacts"], result["active_contacts"])
        self.assertFalse(saved["send_enabled"])
        self.assertTrue(self.bridge.eligible("新备注", "你好"))

    def test_clear_retires_pending_but_keeps_codex_mentions(self):
        mid = self.event()
        self.add("Codex，你好")
        self.bridge.poll()
        self.bridge.set_contacts([])
        with self.assertRaises(ValueError):
            self.bridge.reply(mid, "你好")
        self.assertEqual(len(self.bridge.poll()["events"]), 1)
        self.assertFalse(self.bridge.eligible("测试联系人", "你好"))

    def test_invalid_update_preserves_configuration(self):
        before = self.path.read_text(encoding="utf-8")
        for value in ["一个名字", [""], ["\n"], [123], ["a\nb"]]:
            with self.assertRaises(ValueError):
                self.bridge.set_contacts(value)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
