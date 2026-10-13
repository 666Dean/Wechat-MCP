# SPDX-License-Identifier: MIT
"""Committed WAL snapshot tests using synthetic SQLite tables, never live chats."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from axr.aet import AXRError
except ModuleNotFoundError as exc:
    if exc.name == 'axr':
        raise unittest.SkipTest('AXR optional: install SDK for snapshot tests') from exc
    raise
from adapters.wcdb import DatabaseAdapter


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.db'
        self.chat = 'fixture-chat'
        self.table = 'Msg_' + hashlib.md5(self.chat.encode()).hexdigest()
        self.writer = sqlite3.connect(self.path)
        self.addCleanup(self.writer.close)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.execute('CREATE TABLE Name2Id(user_name TEXT)')
        self.writer.executemany('INSERT INTO Name2Id(rowid,user_name) VALUES(?,?)',
                                [(7, 'fixture-self'), (19, self.chat)])
        self.writer.execute(f'CREATE TABLE "{self.table}"(server_id INTEGER,create_time INTEGER,'
                            'local_type INTEGER,real_sender_id INTEGER,message_content BLOB)')
        self.writer.execute(f'INSERT INTO "{self.table}" VALUES(10,100,1,19,?)', ('original fixture',))
        self.writer.commit()
        self.connections = []
        self.hook = lambda sql: None
        owner = self

        class Connection:
            def __init__(self, path):
                self.db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                self.db.execute('PRAGMA query_only=ON')
                self.db.row_factory = sqlite3.Row
                self.closed = False
                self.was_in_transaction = False
                owner.connections.append(self)

            def query(self, sql, parameters=()):
                rows = [dict(row) for row in self.db.execute(sql, parameters)]
                owner.hook(sql)
                return rows

            def close(self):
                self.was_in_transaction = self.db.in_transaction
                self.db.close()
                self.closed = True

        self.adapter = DatabaseAdapter({
            'account_id': 'fixture-self',
            'conversations': [{'conversation_id': self.chat, 'schema': 'v4'}],
            'shards': [{'path': str(self.path)}],
        }, None, connection_factory=Connection)
        self.addCleanup(self.adapter.close)

    def test_wal_commit_between_message_and_sender_queries_keeps_identity_snapshot(self):
        def change_identity(sql):
            if sql.startswith('SELECT ') and ' AS local_id,' in sql:
                self.writer.execute('UPDATE Name2Id SET user_name=? WHERE rowid=7', (self.chat,))
                self.writer.execute('UPDATE Name2Id SET user_name=? WHERE rowid=19', ('fixture-self',))
                self.writer.execute(f'UPDATE "{self.table}" SET message_content=?', ('new fixture',))
                self.writer.commit()
                self.hook = lambda sql: None
        self.hook = change_identity
        first = self.adapter.search(self.chat)['messages'][0]
        self.assertEqual((first['text'], first['sender'], first['outgoing']),
                         ('original fixture', self.chat, False))
        second = self.adapter.search(self.chat)['messages'][0]
        self.assertEqual((second['text'], second['sender'], second['outgoing']),
                         ('new fixture', 'fixture-self', True))
        self.assertTrue(all(c.closed and c.was_in_transaction for c in self.connections))
        self.assertEqual(self.adapter.connections, {})

    def test_commit_after_schema_read_waits_until_next_page(self):
        def append(sql):
            if sql.startswith('SELECT name FROM sqlite_master'):
                self.writer.execute(f'INSERT INTO "{self.table}" VALUES(11,101,1,19,?)', ('new fixture',))
                self.writer.commit()
                self.hook = lambda sql: None
        self.hook = append
        first = self.adapter.search(self.chat)
        self.assertEqual([m['text'] for m in first['messages']], ['original fixture'])
        second = self.adapter.search(self.chat, after=first['cursor'])
        self.assertEqual([m['text'] for m in second['messages']], ['new fixture'])

    def test_uncommitted_wal_is_hidden_then_visible_after_commit(self):
        self.writer.execute(f'INSERT INTO "{self.table}" VALUES(11,101,1,19,?)', ('pending fixture',))
        first = self.adapter.search(self.chat)
        self.assertEqual(len(first['messages']), 1)
        self.writer.commit()
        second = self.adapter.search(self.chat, after=first['cursor'])
        self.assertEqual([m['text'] for m in second['messages']], ['pending fixture'])

    def test_failed_and_empty_reads_release_snapshot_and_return_no_partial_page(self):
        for failure in ('begin', 'missing_table', 'sender'):
            with self.subTest(failure=failure):
                if failure == 'missing_table':
                    self.writer.execute(f'DROP TABLE "{self.table}"')
                    self.writer.commit()
                def fail(sql):
                    if failure == 'begin' and sql == 'BEGIN':
                        raise AXRError('fixture_begin_failed')
                    if failure == 'sender' and sql.startswith('SELECT user_name FROM Name2Id'):
                        raise AXRError('fixture_sender_failed')
                self.hook = fail
                if failure == 'missing_table':
                    page = self.adapter.search(self.chat)
                    self.assertEqual((page['messages'], page['cursor']), ([], {}))
                    self.writer.execute(f'CREATE TABLE "{self.table}"(server_id INTEGER,create_time INTEGER,'
                                        'local_type INTEGER,real_sender_id INTEGER,message_content BLOB)')
                    self.writer.execute(f'INSERT INTO "{self.table}" VALUES(10,100,1,19,?)', ('fixture',))
                    self.writer.commit()
                else:
                    with self.assertRaisesRegex(AXRError, 'fixture_'):
                        self.adapter.search(self.chat)
                self.assertTrue(self.connections[-1].closed)
                self.assertTrue(self.connections[-1].was_in_transaction)
                self.assertEqual(self.adapter.connections, {})
        self.hook = lambda sql: None
        self.assertEqual(len(self.adapter.search(self.chat)['messages']), 1)


if __name__ == '__main__':
    unittest.main()
