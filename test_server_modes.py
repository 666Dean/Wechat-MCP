import contextlib
import io
import unittest
from unittest.mock import patch

import server


class ServerModeTests(unittest.TestCase):
    def test_axr_rejects_all_legacy_database_and_contact_operations(self):
        for option in (['--probe-database-key'], ['--import-keeper-key', 'cache'],
                       ['--list-database-sessions'], ['--probe-database-messages', 'id'],
                       ['--list-contacts'], ['--store-database-key']):
            with self.subTest(option=option), patch('sys.argv', ['server', '--axr-state', 'state', *option]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    server.main()
                self.assertEqual(result.exception.code, 2)
