import json
import tempfile
import time
import unittest
from pathlib import Path
from bridge import Bridge, MockAdapter
from settings import ConfigStore


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

    def update_config(self, **values):
        config = json.loads(self.path.read_text(encoding="utf-8"))
        config.update(values)
        self.path.write_text(json.dumps(config), encoding="utf-8")

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
        self.update_config(send_enabled=True)
        self.assertEqual(self.bridge.reply(mid, "你好")["status"], "sent")
        with self.assertRaises(ValueError):
            self.bridge.reply(mid, "你好")
        self.assertEqual(len(self.adapter.sent), 1)

    def test_unknown_send_never_retried(self):
        mid = self.event()
        self.update_config(send_enabled=True)
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
        ConfigStore(self.path).set_contacts([])
        with self.assertRaises(ValueError):
            self.bridge.reply(mid, "你好")

    def test_default_list_is_empty(self):
        config = json.loads(Path(__file__).with_name("config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(config["active_contacts"], [])

    def test_update_normalizes_and_persists(self):
        self.bridge.close()
        self.bridge = Bridge(self.path, self.adapter, allow_contact_management=True)
        result = self.bridge.set_contacts([" 新备注 ", "新备注", "第二位"])
        self.assertEqual(result["active_contacts"], ["新备注", "第二位"])
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["active_contacts"], result["active_contacts"])
        self.assertFalse(saved["send_enabled"])
        self.assertTrue(self.bridge.eligible("新备注", "你好"))

    def test_clear_retires_pending_but_keeps_codex_mentions(self):
        self.bridge.close()
        self.bridge = Bridge(self.path, self.adapter, allow_contact_management=True)
        mid = self.event()
        self.add("Codex，你好")
        self.bridge.poll()
        self.bridge.set_contacts([])
        with self.assertRaises(ValueError):
            self.bridge.reply(mid, "你好")
        self.assertEqual(len(self.bridge.poll()["events"]), 1)
        self.assertFalse(self.bridge.eligible("测试联系人", "你好"))

    def test_invalid_update_preserves_configuration(self):
        self.bridge.close()
        self.bridge = Bridge(self.path, self.adapter, allow_contact_management=True)
        before = self.path.read_text(encoding="utf-8")
        for value in ["一个名字", [""], ["\n"], [123], ["a\nb"]]:
            with self.assertRaises(ValueError):
                self.bridge.set_contacts(value)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_contact_management_denied_without_side_effects(self):
        mid = self.event()
        before = self.path.read_bytes()
        with self.assertRaises(PermissionError):
            self.bridge.set_contacts([])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.bridge.db.execute("SELECT status FROM messages WHERE id=?", (mid,)).fetchone()[0], "pending")
        self.assertEqual(self.adapter.sent, [])
        self.assertFalse(self.bridge.status()["permissions"]["mcp_contact_management"])

    def test_live_config_cannot_grant_management_capability(self):
        self.update_config(allow_contact_management=True)
        self.bridge.get_contacts()
        before = self.path.read_bytes()
        with self.assertRaises(PermissionError):
            self.bridge.set_contacts(["未经启动授权的备注"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.bridge.status()["permissions"]["mcp_contact_management"])

    def test_external_contact_update_applies_to_next_poll(self):
        self.bridge.poll()
        ConfigStore(self.path).set_contacts([])
        self.add("普通消息")
        self.assertEqual(self.bridge.poll()["events"], [])
        ConfigStore(self.path).set_contacts(["测试联系人"])
        self.add("恢复后的新消息")
        self.assertEqual([e["text"] for e in self.bridge.poll()["events"]], ["恢复后的新消息"])

    def test_pending_queue_follows_current_chat_and_survives_rebaseline(self):
        mid = self.event()
        original = self.adapter.current
        self.adapter.current = {"peer": "另一个好友", "chat_type": "friend", "messages": []}
        self.assertEqual(self.bridge.poll()["events"], [])
        self.add("Codex，你好")
        other = self.bridge.poll()["events"]
        self.assertEqual([e["peer"] for e in other], ["另一个好友"])
        self.adapter.current = original
        self.adapter.current["messages"][0]["native_id"] = "changed-ui-id"
        self.assertEqual([e["id"] for e in self.bridge.poll()["events"]], [mid])

    def test_expired_queue_does_not_hide_fresh_message(self):
        self.bridge.poll()
        for i in range(55):
            self.add(f"旧待回复 {i}")
        self.bridge.poll()
        self.bridge.db.execute("UPDATE messages SET created=?", (time.time() - 901,))
        self.bridge.db.commit()
        self.add("新的待回复")
        self.assertEqual([e["text"] for e in self.bridge.poll()["events"]], ["新的待回复"])
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM messages WHERE status='expired'").fetchone()[0], 55)
        with self.assertRaises(ValueError):
            self.bridge.reply(1, "过期消息不能发")
        self.assertEqual(self.adapter.sent, [])

    def test_restart_recovers_pending_without_ingesting_history(self):
        mid = self.event()
        self.bridge.close()
        self.add("重启期间的历史消息")
        self.bridge = Bridge(self.path, self.adapter)
        self.assertEqual([e["id"] for e in self.bridge.poll()["events"]], [mid])

    def test_restart_marks_interrupted_send_unknown(self):
        mid = self.event()
        self.bridge.db.execute("UPDATE messages SET status='sending' WHERE id=?", (mid,))
        self.bridge.db.commit()
        self.bridge.close()
        self.bridge = Bridge(self.path, self.adapter)
        self.assertEqual(self.bridge.db.execute("SELECT status FROM messages WHERE id=?", (mid,)).fetchone()[0], "unknown")
        with self.assertRaises(ValueError):
            self.bridge.reply(mid, "不要重复发送")
        self.assertEqual(self.adapter.sent, [])

    def test_invalid_config_blocks_sending_until_repaired(self):
        mid = self.event()
        self.update_config(send_enabled=True)
        self.bridge.get_contacts()
        valid = self.path.read_text(encoding="utf-8")
        for content in ["{broken", valid.replace('"send_enabled": true', '"send_enabled": "false"')]:
            self.path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.bridge.reply(mid, "不能使用缓存的发送权限")
            self.assertEqual(self.adapter.sent, [])
        self.path.write_text(valid, encoding="utf-8")
        self.update_config(send_enabled=False)
        self.assertEqual(self.bridge.reply(mid, "配置恢复后预览")["status"], "preview")

    def test_backend_or_database_change_requires_restart(self):
        for key, value in [("backend", "another_backend"), ("state_file", "another.sqlite3")]:
            original = self.path.read_text(encoding="utf-8")
            self.update_config(**{key: value})
            with self.assertRaisesRegex(ValueError, "重启"):
                self.bridge.poll()
            self.path.write_text(original, encoding="utf-8")
        self.assertFalse((self.path.parent / "another.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
