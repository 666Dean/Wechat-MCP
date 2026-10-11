"""Synthetic cache/page tests. DPAPI storage is mocked; no real WeChat data."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from database_key_import import import_key_cache, read_key_cache
from test_database_key_probe import synthetic_page


class CacheImportTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent
        (root / ".test-work").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root / ".test-work")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.key = bytes(range(32))
        self.cache = self.base / "wechat_db.key"
        self.cache.write_text(self.key.hex() + "\n", encoding="ascii")
        storage = self.base / "wxid_test" / "db_storage"
        (storage / "session").mkdir(parents=True)
        (storage / "message").mkdir()
        self.session = storage / "session" / "session.db"
        self.message = storage / "message" / "message_0.db"
        for path in (self.session, self.message):
            path.write_bytes(synthetic_page(self.key, True))
        self.config = json.loads((root / "config.database.example.json").read_text(encoding="utf-8"))
        self.reader = self.config["database_reader"]
        self.reader.update(account_id="wxid_test", session_db=str(self.session),
                           dll_path=str(self.base / "absent.dll"), key_file=str(self.base / "old.dpapi"))
        Path(self.reader["key_file"]).write_bytes(b"existing-protected-credential")
        self.config_path = self.base / "config.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def test_import_validates_before_storing_original_password_and_keeps_source(self):
        source = self.cache.read_bytes()
        with patch("database_key_import.store_key") as store, \
                patch("local_credentials.load_key", side_effect=AssertionError("must use candidate")):
            result = import_key_cache(self.reader, self.cache)
        store.assert_called_once_with(self.reader, self.key.hex())
        self.assertTrue(result["key_imported"])
        self.assertEqual(result["password_count"], 2)
        self.assertFalse(result["message_body_read"])
        self.assertEqual(source, self.cache.read_bytes())
        output = json.dumps(result)
        for private in (self.key.hex(), str(self.base), "wxid_test"):
            self.assertNotIn(private, output)

    def test_partial_match_wrong_key_missing_shards_and_invalid_page_never_replace(self):
        cases = [synthetic_page(bytes(32)), b"truncated", None]
        for content in cases:
            with self.subTest(content_type=type(content).__name__):
                if content is None:
                    self.message.unlink()
                else:
                    self.message.write_bytes(content)
                with patch("database_key_import.store_key") as store:
                    result = import_key_cache(self.reader, self.cache)
                self.assertFalse(result["key_imported"])
                store.assert_not_called()
                self.assertEqual(Path(self.reader["key_file"]).read_bytes(), b"existing-protected-credential")

    def test_wrong_account_rejected_without_store(self):
        self.reader["account_id"] = "wxid_other"
        with patch("database_key_import.store_key") as store:
            with self.assertRaises(RuntimeError):
                import_key_cache(self.reader, self.cache)
        store.assert_not_called()

    def test_invalid_cache_formats_and_size_are_rejected(self):
        for content in (b"", b"f" * 63, b"f" * 65, b"g" * 64, b"\xff" * 64,
                        b" " * 129 + self.key.hex().encode(), b'{"key":"private"}'):
            self.cache.write_bytes(content)
            with self.subTest(length=len(content)), self.assertRaises(ValueError):
                read_key_cache(self.cache)

    @unittest.skipUnless(os.name == "posix", "POSIX link fixture; Windows reparse requires device validation")
    def test_cache_links_hardlinks_and_fifo_rejected(self):
        link = self.base / "linked.key"
        link.symlink_to(self.cache)
        with self.assertRaises(ValueError):
            read_key_cache(link)
        link.unlink()
        os.link(self.cache, link)
        with self.assertRaises(ValueError):
            read_key_cache(link)
        link.unlink()
        os.mkfifo(link)
        with self.assertRaises(ValueError):
            read_key_cache(link)

    def test_cli_failure_redacts_and_does_not_initialize_bridge(self):
        args = ["server.py", "--config", str(self.config_path), "--import-keeper-key", str(self.cache)]
        for error in (RuntimeError("private-path-and-key"), OSError("private-storage-error")):
            output = io.StringIO()
            with patch.object(sys, "argv", args), patch("sys.stdin.isatty", return_value=True), \
                    patch("database_key_import.import_key_cache", side_effect=error), \
                    patch("server.Bridge", side_effect=AssertionError("must not connect")), \
                    patch("sys.stdout", output):
                with self.assertRaises(SystemExit) as caught:
                    server.main()
            self.assertEqual(caught.exception.code, 1)
            self.assertFalse(json.loads(output.getvalue())["key_imported"])
            self.assertNotIn("private-", output.getvalue())

    def test_cli_requires_terminal_and_rejects_all_other_actions(self):
        args = ["server.py", "--import-keeper-key", str(self.cache)]
        conflicts = [["--demo"], ["--doctor"], ["--store-database-key"], ["--probe-database-key"],
                     ["--list-database-sessions"], ["--probe-database-messages", "test"],
                     ["--set-contacts"], ["--list-contacts"], ["--allow-contact-management"]]
        for other in conflicts:
            with patch.object(sys, "argv", args + other), patch("sys.stdin.isatty", return_value=True), \
                    patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as caught:
                server.main()
            self.assertEqual(caught.exception.code, 2)
        with patch.object(sys, "argv", args), patch("sys.stdin.isatty", return_value=False), \
                patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as caught:
            server.main()
        self.assertEqual(caught.exception.code, 2)

    def test_cli_success_is_counts_only_without_bridge(self):
        output = io.StringIO()
        args = ["server.py", "--config", str(self.config_path), "--import-keeper-key", str(self.cache)]
        with patch.object(sys, "argv", args), patch("sys.stdin.isatty", return_value=True), \
                patch("database_key_import.store_key") as store, \
                patch("server.Bridge", side_effect=AssertionError("must not connect")), \
                patch("sys.stdout", output):
            server.main()
        self.assertTrue(json.loads(output.getvalue())["key_imported"])
        store.assert_called_once()


if __name__ == "__main__":
    unittest.main()
