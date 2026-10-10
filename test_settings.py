import json
import tempfile
import unittest
from pathlib import Path

from settings import ConfigStore, FileLock, LockBusyError, validate_config


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        scratch = self.root / ".test-work"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.path = Path(self.temp.name) / "config.json"
        self.config = json.loads((self.root / "config.example.json").read_text(encoding="utf-8"))
        self.path.write_text(json.dumps(self.config), encoding="utf-8-sig")

    def tearDown(self):
        self.temp.cleanup()

    def test_rejects_invalid_configuration(self):
        invalid = [("active_contacts", "name"), ("active_contacts", [""]),
                   ("send_enabled", "false"), ("send_enabled", 1),
                   ("mention_pattern", "["), ("backend", ""), ("state_file", None),
                   ("reply_prefix", ""), ("introduction", 123),
                   ("max_reply_chars", True), ("max_reply_chars", 0),
                   ("min_reply_interval_seconds", float("nan")),
                   ("min_reply_interval_seconds", float("inf")),
                   ("min_reply_interval_seconds", -1)]
        for key, value in invalid:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_config({**self.config, key: value})
        with self.assertRaises(ValueError):
            validate_config([])

    def test_bom_configuration_updates_without_changing_other_settings(self):
        store = ConfigStore(self.path)
        store.set_contacts([" 中文备注 ", "中文备注"])
        self.assertEqual(store.load(), {**self.config, "active_contacts": ["中文备注"]})

    def test_locked_configuration_update_fails_without_overwriting(self):
        store = ConfigStore(self.path)
        before = self.path.read_bytes()
        with FileLock(store.lock_path):
            with self.assertRaises(LockBusyError):
                store.set_contacts(["新备注"])
            self.assertEqual(self.path.read_bytes(), before)
        store.set_contacts(["锁释放后的备注"])
        self.assertEqual(store.load()["active_contacts"], ["锁释放后的备注"])


if __name__ == "__main__":
    unittest.main()
