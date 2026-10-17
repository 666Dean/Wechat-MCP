# SPDX-License-Identifier: MIT
"""Contact qualification against concurrent synthetic committed WAL changes."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from axr.aet import AXRError
except ModuleNotFoundError as exc:
    if exc.name == 'axr':
        raise unittest.SkipTest('AXR optional: install SDK for contact snapshot tests') from exc
    raise
from adapters.wcdb_keys import qualify_contacts


class ContactSnapshotTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'contacts.db'
        self.writer = sqlite3.connect(self.path)
        self.addCleanup(self.writer.close)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.execute('CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT,delete_flag INTEGER)')
        self.writer.executemany('INSERT INTO contact VALUES(?,?,?,0)', [
            ('fixture-self', 'self', ''), ('fixture-first', 'first', 'label one'),
            ('fixture-second', 'second', 'label two')])
        self.writer.commit()
        self.hook = lambda sql: None
        self.connections = []
        owner = self

        class Connection:
            def __init__(self, *args, **kwargs):
                self.db = sqlite3.connect(owner.path.as_uri() + '?mode=ro', uri=True)
                self.db.row_factory = sqlite3.Row
                self.closed = False
                owner.connections.append(self)

            def query(self, sql, parameters=()):
                rows = [dict(row) for row in self.db.execute(sql, parameters)]
                owner.hook(sql)
                return rows

            def close(self):
                self.db.close()
                self.closed = True

        patcher = patch('adapters.wcdb_keys.open_database', Connection)
        patcher.start()
        self.addCleanup(patcher.stop)

    def qualify(self):
        return qualify_contacts(self.path, None, b'k' * 32, 'fixture-self',
                                ['label one', 'label two'])

    def test_account_and_labels_share_snapshot_then_next_call_sees_commit(self):
        def change(sql):
            if sql.startswith('SELECT username FROM contact WHERE username=?'):
                self.writer.execute("DELETE FROM contact WHERE username='fixture-self'")
                self.writer.execute("UPDATE contact SET username='fixture-replacement' WHERE remark='label two'")
                self.writer.commit()
                self.hook = lambda sql: None
        self.hook = change
        self.assertEqual([b['conversation_id'] for b in self.qualify()],
                         ['fixture-first', 'fixture-second'])
        with self.assertRaisesRegex(AXRError, 'account_identity_not_in_contact_database'):
            self.qualify()
        self.assertTrue(all(c.closed for c in self.connections))

    def test_labels_cannot_mix_versions_and_next_call_rejects_duplicate(self):
        def change(sql):
            if 'username NOT LIKE' in sql:
                self.writer.execute('INSERT INTO contact VALUES(?,?,?,0)',
                                    ('fixture-duplicate', 'duplicate', 'label two'))
                self.writer.commit()
                self.hook = lambda sql: None
        self.hook = change
        self.assertEqual(len(self.qualify()), 2)
        with self.assertRaisesRegex(AXRError, 'contact_identity_missing_or_ambiguous'):
            self.qualify()
        self.assertTrue(all(c.closed for c in self.connections))

    def test_begin_and_lookup_failure_release_connection_without_bindings(self):
        for stage in ('BEGIN', 'username NOT LIKE'):
            with self.subTest(stage=stage):
                def fail(sql):
                    if stage in sql:
                        raise AXRError('fixture_contact_read_failed')
                self.hook = fail
                with self.assertRaisesRegex(AXRError, 'fixture_contact_read_failed'):
                    self.qualify()
                self.assertTrue(self.connections[-1].closed)
        self.hook = lambda sql: None
        self.assertEqual(len(self.qualify()), 2)
