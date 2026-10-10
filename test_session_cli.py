"""Owner-only metadata discovery with synthetic readers; no real credentials."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server
from database_reader import ReaderError


class SessionCliTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent
        scratch = root / ".test-work"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.path = Path(self.temp.name) / "config.json"
        self.config = json.loads((root / "config.database.example.json").read_text(encoding="utf-8"))
        self.config["database_reader"].update(
            account_id="wxid_owner", session_db=str(self.path.parent / "wxid_owner/db_storage/session/session.db"),
            dll_path=str(self.path.parent / "synthetic.dll"), key_file=str(self.path.parent / "synthetic.dpapi"))
        self.path.write_text(json.dumps(self.config), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_catalog_cli_closes_reader_and_preserves_config_without_state_database(self):
        reader = Mock()
        reader.session_catalog.return_value = {
            "sessions": [{"conversation_id": "wxid_synthetic", "display_name": "合成名称"}],
            "untrusted_content": True}
        output = io.StringIO()
        before = self.path.read_bytes()
        with patch.object(sys, "argv", ["server.py", "--config", str(self.path), "--list-database-sessions"]), \
                patch("database_reader.WcdbReader", return_value=reader), patch("sys.stdout", output):
            server.main()
        self.assertEqual(json.loads(output.getvalue()), reader.session_catalog.return_value)
        reader.close.assert_called_once()
        reader.messages.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.path.parent / self.config["state_file"]).exists())

    def test_catalog_query_failure_reports_error_and_closes_reader(self):
        reader = Mock()
        reader.session_catalog.side_effect = ReaderError("合成查询失败")
        output = io.StringIO()
        with patch.object(sys, "argv", ["server.py", "--config", str(self.path), "--list-database-sessions"]), \
                patch("database_reader.WcdbReader", return_value=reader), patch("sys.stdout", output):
            with self.assertRaises(SystemExit) as caught:
                server.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(json.loads(output.getvalue()), {"connected": False, "error": "合成查询失败"})
        reader.close.assert_called_once()
        reader.messages.assert_not_called()

    def test_catalog_open_failure_has_json_error_without_partial_state(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["server.py", "--config", str(self.path), "--list-database-sessions"]), \
                patch("database_reader.WcdbReader", side_effect=ReaderError("合成打开失败")), patch("sys.stdout", output):
            with self.assertRaises(SystemExit) as caught:
                server.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertFalse(json.loads(output.getvalue())["connected"])
        self.assertFalse((self.path.parent / self.config["state_file"]).exists())


if __name__ == "__main__":
    unittest.main()
