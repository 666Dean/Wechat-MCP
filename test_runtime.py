"""Runtime ownership and crash recovery. All adapters are simulated."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bridge import Bridge, MockAdapter


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        scratch = self.root / ".test-work"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.path = Path(self.temp.name) / "config.json"
        self.config = json.loads((self.root / "config.example.json").read_text(encoding="utf-8"))
        self.path.write_text(json.dumps(self.config), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_duplicate_database_is_rejected_even_through_another_config(self):
        bridge = Bridge(self.path, MockAdapter())
        alias = self.path.with_name("another-config.json")
        alias.write_text(json.dumps({**self.config, "state_file": "./state.sqlite3"}), encoding="utf-8")
        try:
            for path in (self.path, alias):
                with self.assertRaisesRegex(RuntimeError, "已有服务运行"):
                    Bridge(path, MockAdapter())
        finally:
            bridge.close()
        reopened = Bridge(alias, MockAdapter())
        reopened.close()
        reopened.close()

    def test_process_crash_releases_runtime_lock(self):
        result = subprocess.run([sys.executable, "-c",
            "import os, sys; from bridge import Bridge, MockAdapter; "
            "bridge = Bridge(sys.argv[1], MockAdapter()); os._exit(79)",
            str(self.path)], cwd=self.root, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 79, result.stderr)
        reopened = Bridge(self.path, MockAdapter())
        reopened.close()

    def test_initialization_error_releases_runtime_lock(self):
        database = self.path.parent / "state.sqlite3"
        database.write_bytes(b"not a SQLite database")
        with self.assertRaises(sqlite3.DatabaseError):
            Bridge(self.path, MockAdapter())
        database.write_bytes(b"")
        reopened = Bridge(self.path, MockAdapter())
        reopened.close()


if __name__ == "__main__":
    unittest.main()
