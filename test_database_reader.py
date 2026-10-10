"""Synthetic WCDB ABI and message-stream tests. Never loads a real WeChat DLL."""
import copy
import ctypes as C
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge import Bridge, MockAdapter
from database_reader import (ReaderError, WcdbReader, account_binding,
                             normalize_message, reconcile, validate_database_config)
from local_credentials import load_key, store_key
from settings import ConfigStore, validate_config


def message(local, **values):
    return {"local_id": local, "server_id": 10000 + local, "source_db": "message_1.db",
            "create_time": int(time.time()), "sort_seq": local, "local_type": 1,
            "computed_is_send": 0, "sender_username": "wxid_friend", "message_content": "Codex 你好",
            **values}


class StreamReader:
    def __init__(self, config):
        self.account_id = config["account_id"]
        self.binding = account_binding(config)
        self.rows = []
        self.names = {"wxid_friend": "合成好友"}
        self.sessions_rows = [{"username": "wxid_friend"}]
        self.reads = []
        self.hook = None
        self.closed = False

    def sessions(self):
        return copy.deepcopy(self.sessions_rows), dict(self.names)

    def messages(self, conversation, limit, offset):
        self.reads.append((conversation, limit, offset))
        if self.hook:
            self.hook(self, offset)
        return copy.deepcopy(self.rows[offset:offset + limit])

    def close(self):
        self.closed = True


class FakeNative:
    """Real ctypes C callback signatures, synthetic returned memory and handles."""
    def __init__(self):
        self.buffers = {}
        self.freed = []
        self.closed = []
        self.shutdowns = 0
        self.code = 0
        self.payload = b'[{"username":"wxid_friend"}]'
        self.names = {"wxid_friend": "合成好友"}
        self.null = False
        self.open_code = 0
        self.large_handle = 2 ** 40 + 7

        def output(pointer, payload):
            if not self.null:
                buffer = C.create_string_buffer(payload)
                address = C.addressof(buffer)
                self.buffers[address] = buffer
                pointer[0] = address
            return self.code

        def open_account(path, key, pointer):
            pointer[0] = self.large_handle
            return self.open_code

        def free(pointer):
            self.freed.append(pointer)
            self.buffers.pop(pointer)

        def close(handle):
            self.closed.append(handle)
            return 0

        def shutdown():
            self.shutdowns += 1
            return 0

        out = C.POINTER(C.c_void_p)
        self.wcdb_init = C.CFUNCTYPE(C.c_int32)(lambda: 0)
        self.wcdb_shutdown = C.CFUNCTYPE(C.c_int32)(shutdown)
        self.wcdb_open_account = C.CFUNCTYPE(C.c_int32, C.c_char_p, C.c_char_p, C.POINTER(C.c_int64))(open_account)
        self.wcdb_close_account = C.CFUNCTYPE(C.c_int32, C.c_int64)(close)
        self.wcdb_free_string = C.CFUNCTYPE(None, C.c_void_p)(free)
        self.wcdb_get_sessions = C.CFUNCTYPE(C.c_int32, C.c_int64, out)(lambda h, p: output(p, self.payload))
        self.wcdb_get_messages = C.CFUNCTYPE(C.c_int32, C.c_int64, C.c_char_p, C.c_int32, C.c_int32, out)(
            lambda h, u, l, o, p: output(p, self.payload))
        self.wcdb_get_display_names = C.CFUNCTYPE(C.c_int32, C.c_int64, C.c_char_p, out)(
            lambda h, u, p: output(p, json.dumps(self.names).encode("utf-8")))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parent / ".test-work"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.entry = self.root / "wxid_owner" / "db_storage" / "session" / "session.db"
        self.entry.parent.mkdir(parents=True)
        self.entry.write_bytes(b"synthetic fixture, not a WeChat database")
        self.config = json.loads(Path(__file__).with_name("config.database.example.json").read_text(encoding="utf-8"))
        self.config["active_contacts"] = ["合成好友"]
        self.config["database_reader"].update(account_id="wxid_owner", session_db=str(self.entry),
            dll_path=str(self.root / "fake.dll"), key_file=str(self.root / "test.dpapi"), page_size=4, max_pages=30,
            conversations=[{"conversation_id": "wxid_friend", "display_name": "合成好友"}])
        self.path = self.root / "config.json"
        self.path.write_text(json.dumps(self.config), encoding="utf-8")
        self.reader = StreamReader(self.config["database_reader"])
        self.bridge = Bridge(self.path, reader=self.reader)

    def tearDown(self):
        self.bridge.close()
        self.temp.cleanup()

    def update(self):
        self.path.write_text(json.dumps(self.config), encoding="utf-8")

    def event(self, **values):
        self.bridge.poll()
        self.reader.rows.insert(0, message(1, **values))
        return self.bridge.poll()["events"][0]

    def restart(self):
        self.bridge.close()
        self.reader.closed = False
        self.bridge = Bridge(self.path, reader=self.reader)

    def test_history_baseline_and_new_messages_survive_restart(self):
        self.reader.rows = [message(1, message_content="历史不入队")]
        self.assertEqual(self.bridge.poll()["events"], [])
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_seen").fetchone()[0], 1)
        self.restart()
        self.reader.rows.insert(0, message(2))
        events = self.bridge.poll()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["conversation_id"], "wxid_friend")
        self.bridge.dismiss(events[0]["id"])
        self.restart()
        self.assertEqual(self.bridge.poll()["events"], [])
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM messages").fetchone()[0], 1)

    def test_pending_and_saved_preview_survive_restart_and_send_switch(self):
        event = self.event()
        self.config["send_enabled"] = True
        self.update()
        result = self.bridge.reply(event["id"], "合成预览")
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["account_id"], "wxid_owner")
        self.assertIsNone(self.bridge.adapter)
        self.assertFalse(self.bridge.status()["send_enabled"])
        self.restart()
        self.assertEqual(self.bridge.poll()["events"], [])
        self.assertEqual(self.bridge.list_queue()["items"][0]["id"], event["id"])
        self.assertIn("合成预览", self.bridge.db.execute("SELECT reply FROM messages").fetchone()[0])

    def test_offline_database_queue_does_not_open_reader_or_credentials(self):
        event = self.event()
        draft = self.bridge.reply(event["id"], "离线预览")
        self.bridge.close()
        with patch("database_reader.WcdbReader", side_effect=AssertionError("must remain offline")):
            self.bridge = Bridge(self.path)
            queue = self.bridge.list_queue()
            self.assertEqual(queue["items"][0]["preview"], draft["text"])
            self.assertEqual(queue["items"][0]["conversation_id"], "wxid_friend")
            self.assertFalse(queue["live_identity_verified"])
            self.assertIsNone(self.bridge.reader)
            self.bridge.dismiss(event["id"])
            self.assertEqual(self.bridge.list_queue()["items"], [])

    def test_offline_queue_rechecks_config_and_does_not_expose_removed_binding(self):
        event = self.event()
        self.bridge.reply(event["id"], "保密草稿")
        self.config["database_reader"]["conversations"] = []
        self.update()
        with self.assertRaisesRegex(ValueError, "重启"):
            self.bridge.list_queue()
        self.restart()
        self.assertEqual(self.bridge.list_queue()["items"], [])

    def test_offline_queue_does_not_expose_foreign_account_rows(self):
        self.event()
        self.bridge.db.execute("""INSERT INTO messages
            (peer,native_id,text,eligible,created,source,account_id,conversation_id,reply)
            VALUES(?,?,?,?,?,'wcdb',?,?,?)""",
            ("合成好友", "foreign-account", "其他账号的合成消息", 1, time.time(),
             "wxid_other_owner", "wxid_friend", "其他账号草稿"))
        self.bridge.db.commit()
        queue = self.bridge.list_queue()
        self.assertEqual(len(queue["items"]), 1)
        self.assertNotIn("其他账号", str(queue))

    def test_session_catalog_strips_native_preview_and_diagnoses_rename(self):
        native = FakeNative()
        native.payload = json.dumps([{"username": "wxid_friend", "last_message": "不可导出的合成正文"}]).encode("utf-8")
        native.names["wxid_friend"] = "已改名"
        reader = self.native_reader(native)
        try:
            catalog = reader.session_catalog()
            self.assertNotIn("不可导出", str(catalog))
            self.assertEqual(catalog["sessions"][0]["display_name"], "已改名")
            self.assertTrue(catalog["sessions"][0]["configured"])
            self.assertFalse(catalog["sessions"][0]["binding_matches"])
            with self.assertRaises(ReaderError):
                reader.sessions()  # Normal ingestion must still reject the rename.
            self.assertEqual(native.buffers, {})
        finally:
            reader.close()

    def test_session_catalog_flags_duplicate_missing_and_excluded_ids(self):
        native = FakeNative()
        ids = ["wxid_friend", "wxid_duplicate", "wxid_missing", "wxid_owner", "group@chatroom", "gh_public"]
        native.payload = json.dumps([{"username": cid} for cid in ids]).encode("utf-8")
        native.names.update(wxid_duplicate="合成好友", wxid_owner="本人", gh_public="公众号",
                            **{"group@chatroom": "合成群"})
        reader = self.native_reader(native)
        try:
            rows = {s["conversation_id"]: s for s in reader.session_catalog()["sessions"]}
            self.assertTrue(all(not row["can_bind"] for row in rows.values()))
            self.assertEqual(rows["wxid_friend"]["reason"], "duplicate_display_name")
            self.assertEqual(rows["wxid_missing"]["reason"], "missing_or_invalid_display_name")
            self.assertEqual(rows["wxid_owner"]["reason"], "excluded_conversation_id")
        finally:
            reader.close()

    def test_shard_local_id_collisions_and_same_second_messages(self):
        self.bridge.poll()
        self.reader.rows = [message(1, source_db="message_1.db", server_id=0),
                            message(1, source_db="message_2.db", server_id=-1), message(2)]
        self.assertEqual(len(self.bridge.poll()["events"]), 3)
        self.reader.rows[0]["server_id"] = 123456  # Later server acknowledgement.
        self.assertEqual(len(self.bridge.poll()["events"]), 3)
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_seen").fetchone()[0], 3)

    def test_unknown_shard_and_server_id_blocks_without_checkpoint(self):
        self.bridge.poll()
        self.reader.rows = [message(1, source_db=None, server_id=0)]
        with self.assertRaisesRegex(ReaderError, "分库标识"):
            self.bridge.poll()
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_seen").fetchone()[0], 0)
        self.reader.rows[0]["server_id"] = "12345"
        self.assertEqual(len(self.bridge.poll()["events"]), 1)

    def test_self_media_unknown_direction_and_compressed_filtered(self):
        self.bridge.poll()
        self.reader.rows = [message(1, sender_username="wxid_owner"),
            message(2, computed_is_send=1), message(3, local_type=3),
            message(4, sender_username=None, computed_is_send=None),
            message(5, compress_content="compressed fixture"),
            message(6, sender_username="unexpected_sender"), message(7)]
        self.assertEqual(len(self.bridge.poll()["events"]), 1)
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_seen").fetchone()[0], 7)

    def test_other_friend_mention_rule_and_revocation(self):
        self.config["active_contacts"] = []
        self.update()
        self.bridge.poll()
        self.reader.rows = [message(1, message_content="普通消息"), message(2)]
        self.assertEqual(len(self.bridge.poll()["events"]), 1)
        self.config["active_contacts"] = ["合成好友"]
        self.update()
        self.assertEqual(len(self.bridge.poll()["events"]), 1)  # No history replay after grant.
        self.reader.rows.insert(0, message(3, message_content="新的普通消息"))
        ordinary = self.bridge.poll()["events"][-1]
        ConfigStore(self.path).set_contacts([])
        with self.assertRaises(ValueError):
            self.bridge.reply(ordinary["id"], "已撤销")

    def test_duplicate_name_rename_and_missing_conversation_stop_reads(self):
        for rows, names in [
            ([{"username": "wxid_friend"}, {"username": "wxid_other"}],
             {"wxid_friend": "合成好友", "wxid_other": "合成好友"}),
            ([{"username": "wxid_friend"}], {"wxid_friend": "已改名"}),
            ([], {})]:
            self.reader.sessions_rows, self.reader.names = rows, names
            with self.subTest(names=names), self.assertRaises(ReaderError):
                self.bridge.poll()
            self.assertEqual(self.reader.reads, [])

    def test_only_explicit_scope_is_queried(self):
        self.reader.sessions_rows += [{"username": "wxid_unbound"}, {"username": "room@chatroom"}]
        self.reader.names.update(wxid_unbound="未授权好友", **{"room@chatroom": "合成群"})
        self.bridge.poll()
        self.assertEqual({r[0] for r in self.reader.reads}, {"wxid_friend"})

    def test_multi_conversation_identity_and_atomic_failure(self):
        self.bridge.close()
        self.config["database_reader"]["conversations"].append(
            {"conversation_id": "wxid_other", "display_name": "另一合成好友"})
        self.config["active_contacts"].append("另一合成好友")
        self.update()
        self.reader.sessions_rows.append({"username": "wxid_other"})
        self.reader.names["wxid_other"] = "另一合成好友"
        original = self.reader.messages
        def per_conversation(cid, limit, offset):
            if cid == "wxid_other" and self.reader.rows:
                raise ReaderError("第二会话失败")
            return original(cid, limit, offset)
        self.reader.messages = per_conversation
        self.bridge = Bridge(self.path, reader=self.reader)
        self.bridge.poll()
        self.reader.rows = [message(1)]
        with self.assertRaises(ReaderError):
            self.bridge.poll()
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_seen").fetchone()[0], 0)
        self.reader.messages = lambda cid, limit, offset: [dict(m, sender_username=cid) for m in original(cid, limit, offset)]
        events = self.bridge.poll()["events"]
        self.assertEqual({e["conversation_id"] for e in events}, {"wxid_friend", "wxid_other"})

    def test_pagination_insertion_overlap_and_reconciliation(self):
        self.bridge.poll()
        self.reader.rows = [message(i) for i in range(12, 0, -1)]
        changed = False
        def hook(reader, offset):
            nonlocal changed
            if offset and not changed:
                reader.rows.insert(0, message(13))
                changed = True
        self.reader.hook = hook
        self.assertEqual(len(self.bridge.poll()["events"]), 13)
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_seen").fetchone()[0], 13)

    def test_unstable_scan_and_limit_never_advance_baseline(self):
        self.reader.rows = [message(i) for i in range(8, 0, -1)]
        with self.assertRaisesRegex(ReaderError, "max_pages"):
            reconcile(self.reader, "wxid_friend", {"page_size": 4, "max_pages": 1})
        counter = 20
        def mutate(reader, offset):
            nonlocal counter
            if offset == 0:
                counter += 1
                reader.rows.insert(0, message(counter))
        self.reader.hook = mutate
        with self.assertRaisesRegex(ReaderError, "持续变化"):
            self.bridge.poll()
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_conversations").fetchone()[0], 0)

    def test_old_and_future_timestamps_do_not_gain_fresh_ttl(self):
        self.bridge.poll()
        self.reader.rows = [message(1, create_time=int(time.time()) - 1000),
                            message(2, create_time=int(time.time()) + 1000)]
        self.assertEqual(self.bridge.poll()["events"], [])
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_seen").fetchone()[0], 2)

    def test_queue_insert_failure_rolls_back_seen_and_baseline(self):
        self.bridge.poll()
        self.reader.rows = [message(1)]
        self.bridge.db.execute("CREATE TRIGGER reject_queue BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        self.bridge.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.bridge.poll()
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_seen").fetchone()[0], 0)
        self.bridge.db.execute("DROP TRIGGER reject_queue")
        self.bridge.db.commit()
        self.assertEqual(len(self.bridge.poll()["events"]), 1)

    def test_account_change_during_scan_cannot_commit(self):
        def change(reader, offset):
            reader.account_id = "wxid_other_owner"
        self.reader.hook = change
        with self.assertRaisesRegex(ReaderError, "账号"):
            self.bridge.poll()
        self.assertEqual(self.bridge.db.execute("SELECT count(*) FROM reader_conversations").fetchone()[0], 0)

    def test_live_reader_config_change_requires_restart(self):
        self.config["database_reader"]["account_id"] = "changed"
        self.update()
        with self.assertRaisesRegex(ValueError, "重启"):
            self.bridge.poll()

    def test_state_binding_rejects_other_account_and_entry(self):
        self.bridge.close()
        other = self.entry.with_name("another.db")
        other.write_bytes(b"synthetic")
        self.config["database_reader"]["session_db"] = str(other)
        self.update()
        with self.assertRaisesRegex(ValueError, "独立 state_file"):
            Bridge(self.path, reader=self.reader)
        self.config["database_reader"]["session_db"] = str(self.entry)
        self.update()
        self.bridge = Bridge(self.path, reader=self.reader)  # Failure released lock.

    def test_path_binding_rejects_mismatched_owner(self):
        with self.assertRaises(ReaderError):
            account_binding({**self.config["database_reader"], "account_id": "another"})

    def test_configuration_rejects_secret_ambiguous_and_nonprivate_bindings(self):
        database = self.config["database_reader"]
        bad = [None, {**database, "key": "never put secrets in config"},
               {**database, "page_size": True}, {**database, "max_pages": 0},
               {**database, "session_db": "relative.db"},
               {**database, "key_file": str(self.entry)},
               {**database, "conversations": database["conversations"] * 2}]
        for cid in ("room@chatroom", "gh_public", "filehelper", "wxid_owner"):
            bad.append({**database, "conversations": [{"conversation_id": cid, "display_name": "合成"}]})
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_database_config(value)
        with self.assertRaises(ValueError):
            validate_config({**self.config, "backend": "wxauto4"})

    def test_runtime_file_aliases_cannot_overwrite_credentials_or_database(self):
        self.bridge.close()
        for target in (self.config["database_reader"]["key_file"], str(self.entry), str(self.path)):
            self.config["state_file"] = target
            self.update()
            with self.assertRaises(ValueError):
                Bridge(self.path, reader=self.reader)
        self.assertEqual(self.entry.read_bytes(), b"synthetic fixture, not a WeChat database")

    def test_migration_preserves_legacy_unknown_row(self):
        self.bridge.close()
        self.config = json.loads(Path(__file__).with_name("config.example.json").read_text(encoding="utf-8"))
        self.config.update(active_contacts=["合成好友"], state_file="legacy.sqlite3")
        self.update()
        db = sqlite3.connect(self.root / "legacy.sqlite3")
        db.executescript("""CREATE TABLE messages(id INTEGER PRIMARY KEY,peer TEXT,native_id TEXT,text TEXT,
            eligible INTEGER,created REAL,status TEXT DEFAULT 'pending',reply TEXT,UNIQUE(peer,native_id));""")
        db.execute("INSERT INTO messages VALUES(1,?,?,?,?,?,'sending',?)",
                   ("合成好友", "legacy", "合成旧消息", 1, time.time(), "合成旧回复"))
        db.commit()
        db.close()
        self.bridge = Bridge(self.path, MockAdapter())
        row = self.bridge.db.execute("SELECT * FROM messages").fetchone()
        self.assertEqual((row["text"], row["reply"], row["status"], row["source"]),
                         ("合成旧消息", "合成旧回复", "unknown", "ui"))

    def native_reader(self, native):
        return WcdbReader(self.config["database_reader"], native=native, key_loader=lambda c: "a" * 64)

    def test_ffi_int64_utf8_pointer_free_and_close(self):
        native = FakeNative()
        reader = self.native_reader(native)
        try:
            rows, names = reader.sessions()
            self.assertEqual(names[rows[0]["username"]], "合成好友")
            self.assertEqual(reader.handle.value, native.large_handle)
            self.assertEqual(len(native.freed), 2)
            self.assertEqual(native.buffers, {})
            self.assertEqual(native.wcdb_get_messages.argtypes[0], C.c_int64)
            with self.assertRaises(ReaderError):
                reader.messages("not_authorized", 4, 0)
        finally:
            reader.close()
        self.assertEqual(native.closed, [native.large_handle])
        self.assertEqual(native.shutdowns, 1)

    def test_ffi_errors_free_pointer_and_never_become_empty_messages(self):
        for payload, code in [(b"{invalid secret-like payload", 0), (b"\xff", 0),
                              (b'{"_error":"private native details"}', 0),
                              (b'[{"_error":"private native details"}]', 0), (b"[]", -2)]:
            native = FakeNative()
            reader = self.native_reader(native)
            native.payload, native.code = payload, code
            try:
                with self.assertRaises(ReaderError) as caught:
                    reader.sessions()
                self.assertNotIn("private", str(caught.exception))
                self.assertNotIn("secret", str(caught.exception))
                self.assertEqual(len(native.freed), 1)
                self.assertEqual(native.buffers, {})
            finally:
                reader.close()
        native = FakeNative()
        reader = self.native_reader(native)
        native.null = True
        try:
            with self.assertRaises(ReaderError):
                reader.sessions()
            self.assertEqual(native.freed, [])
        finally:
            reader.close()

    def test_ffi_open_failure_closes_partial_handle_and_shutdown(self):
        native = FakeNative()
        native.open_code = -2
        with self.assertRaises(ReaderError):
            self.native_reader(native)
        self.assertEqual(native.closed, [native.large_handle])
        self.assertEqual(native.shutdowns, 1)

    def test_native_entry_replacement_stops_reads(self):
        native = FakeNative()
        reader = self.native_reader(native)
        try:
            replacement = self.entry.with_suffix(".tmp")
            replacement.write_bytes(b"replaced synthetic entry")
            os.replace(replacement, self.entry)
            with self.assertRaises(ReaderError):
                reader.sessions()
        finally:
            reader.close()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_dpapi_synthetic_key_roundtrip_binding_and_invalid_overwrite(self):
        config = self.config["database_reader"]
        store_key(config, "b" * 64)
        before = Path(config["key_file"]).read_bytes()
        self.assertNotIn(b"b" * 64, before)
        self.assertEqual(load_key(config), "b" * 64)
        with self.assertRaises(ValueError):
            store_key(config, "invalid")
        self.assertEqual(Path(config["key_file"]).read_bytes(), before)
        with self.assertRaises(RuntimeError):
            load_key({**config, "session_db": str(self.entry.with_name("other.db"))})


if __name__ == "__main__":
    unittest.main()
