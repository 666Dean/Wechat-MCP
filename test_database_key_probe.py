"""Synthetic authenticated pages; no real credentials or native databases."""
import hashlib
import hmac
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from database_key_probe import page_key_mode, probe_database_key


def synthetic_page(key, password=False):
    salt = bytes(range(16))
    body = bytes(range(256)) * 15 + bytes(176)  # bytes 16..4031, including IV
    assert len(body) == 4016
    page_key = hashlib.pbkdf2_hmac("sha512", key, salt, 256000, 32) if password else key
    mac_key = hashlib.pbkdf2_hmac("sha512", page_key, bytes(x ^ 0x3A for x in salt), 2, 32)
    mac = hmac.new(mac_key, body + struct.pack("<I", 1), hashlib.sha512).digest()
    return salt + body + mac


class KeyProbeTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent
        (root / ".test-work").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root / ".test-work")
        self.base = Path(self.temp.name)
        storage = self.base / "wxid_owner" / "db_storage"
        (storage / "session").mkdir(parents=True)
        (storage / "message").mkdir()
        self.key = bytes(range(32))
        self.session = storage / "session" / "session.db"
        self.session.write_bytes(synthetic_page(self.key, True))
        self.message = storage / "message" / "message_0.db"
        self.message.write_bytes(synthetic_page(self.key))
        self.config = json.loads((root / "config.database.example.json").read_text(encoding="utf-8"))
        self.config["database_reader"].update(account_id="wxid_owner", session_db=str(self.session),
                                             dll_path=str(self.base / "absent.dll"),
                                             key_file=str(self.base / "absent.dpapi"))
        self.path = self.base / "config.json"
        self.path.write_text(json.dumps(self.config), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def probe(self):
        with patch("local_credentials.load_key", return_value=self.key.hex()):
            return probe_database_key(self.config["database_reader"])

    def test_authentication_distinguishes_modes_and_rejects_tampering(self):
        self.assertEqual(page_key_mode(synthetic_page(self.key), self.key), "raw")
        page = synthetic_page(self.key, True)
        self.assertEqual(page_key_mode(page, self.key), "password")
        changed = bytearray(page)
        changed[512] ^= 1
        self.assertEqual(page_key_mode(bytes(changed), self.key), "unmatched")
        self.assertEqual(page_key_mode(page, bytes(32)), "unmatched")
        for invalid in (b"", page[:-1], page + b"x"):
            with self.assertRaises(ValueError):
                page_key_mode(invalid, self.key)

    def test_probe_reports_counts_without_native_load_or_file_mutation(self):
        before = {p: p.read_bytes() for p in (self.session, self.message, self.path)}
        with patch("database_reader.WcdbReader", side_effect=AssertionError("must not load DLL")):
            result = self.probe()
        self.assertTrue(result["message_key_verified"])
        self.assertEqual((result["checked_count"], result["password_count"], result["raw_count"]), (2, 1, 1))
        self.assertFalse(result["message_body_read"])
        self.assertFalse(result["state_changed"])
        output = json.dumps(result)
        for private in (self.key.hex(), str(self.session), "wxid_owner"):
            self.assertNotIn(private, output)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_unmatched_and_truncated_pages_are_failures_not_empty_success(self):
        self.message.write_bytes(synthetic_page(bytes(32)))
        result = self.probe()
        self.assertEqual(result["unmatched_count"], 1)
        self.assertFalse(result["message_key_verified"])
        self.message.write_bytes(b"truncated")
        result = self.probe()
        self.assertEqual(result["error_count"], 1)
        self.assertFalse(result["key_matches_all"])

    def test_no_message_shards_does_not_claim_message_key_verified(self):
        self.message.unlink()
        result = self.probe()
        self.assertTrue(result["key_matches_all"])
        self.assertFalse(result["message_key_verified"])

    def test_shard_cap_is_checked_before_credentials_are_loaded(self):
        for number in range(1, 65):
            (self.message.parent / f"message_{number}.db").touch()
        with patch("local_credentials.load_key", side_effect=AssertionError("too early")):
            with self.assertRaises(ValueError):
                probe_database_key(self.config["database_reader"])

    def test_cli_failure_suppresses_private_exception_details(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["server.py", "--config", str(self.path), "--probe-database-key"]), \
                patch("database_key_probe.probe_database_key", side_effect=RuntimeError("private-key-and-path")), \
                patch("sys.stdout", output):
            with self.assertRaises(SystemExit) as caught:
                server.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertNotIn("private-key-and-path", output.getvalue())

    def test_cli_runs_without_bridge_and_conflicting_actions_are_rejected(self):
        output = io.StringIO()
        args = ["server.py", "--config", str(self.path), "--probe-database-key"]
        with patch.object(sys, "argv", args), patch("local_credentials.load_key", return_value=self.key.hex()), \
                patch("server.Bridge", side_effect=AssertionError("must not create state")), patch("sys.stdout", output):
            server.main()
        self.assertTrue(json.loads(output.getvalue())["message_key_verified"])
        for other in (["--doctor"], ["--demo"], ["--list-database-sessions"], ["--probe-database-messages", "wxid_friend"]):
            with patch.object(sys, "argv", args + other), patch("sys.stderr", io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    server.main()
            self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
