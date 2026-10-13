# SPDX-License-Identifier: MIT
"""Optional engine tests: real encrypted synthetic fixtures, no live account data."""
import hashlib
import itertools
import ctypes as C
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
try:
    from axr.aet import AXRError
except ModuleNotFoundError as exc:
    if exc.name == 'axr':
        raise unittest.SkipTest('AXR optional: install SDK for SQLite3mc tests') from exc
    raise
from adapters.sqlite3mc import MultipleCipherConnection
from adapters.wcdb import CipherConnection, DatabaseAdapter, open_database
from adapters.wcdb_keys import qualify_contacts
from database_key_probe import verified_page_key
try:
    import apsw
except ModuleNotFoundError:
    apsw = None


class EngineSelection(unittest.TestCase):
    def test_explicit_selection_never_falls_back_or_accepts_unqualified_engine(self):
        with patch.dict('sys.modules', {'apsw': None}):
            with self.assertRaisesRegex(AXRError, 'optional_dependency_missing'):
                open_database('missing', 'ab'*32, 'wcdb4-raw', engine='sqlite3mc')
        with patch.dict('sys.modules', {'apsw': SimpleNamespace(apswversion=lambda: '3.53.4.0')}):
            with self.assertRaisesRegex(AXRError, 'version_not_qualified'):
                open_database('missing', 'ab'*32, 'wcdb4-raw', engine='sqlite3mc')
        with self.assertRaisesRegex(AXRError, 'engine_not_supported'):
            DatabaseAdapter({'engine':'automatic'}, None)
        with self.assertRaisesRegex(AXRError, 'library_not_configured'):
            open_database('missing', 'ab'*32, 'wcdb4-raw')
        with self.assertRaisesRegex(AXRError, 'profile_not_qualified'):
            MultipleCipherConnection('missing', 'ab'*32, 'sqlcipher3')


@unittest.skipUnless(apsw is not None and getattr(apsw, 'mc_version', None) == 'SQLite3 Multiple Ciphers 2.4.0',
                     'qualified optional apsw-sqlite3mc wheel not installed')
class EncryptedReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.db'
        self.raw = 'ab'*32
        self.writer = apsw.Connection(str(self.path))
        self.addCleanup(self.writer.close)
        self.writer.pragma('cipher', 'sqlcipher')
        self.writer.pragma('legacy', 4)
        self.writer.pragma('key', 'raw:' + self.raw)
        self.writer.pragma('journal_mode', 'WAL')
        self.writer.execute('CREATE TABLE fixture(id INTEGER PRIMARY KEY, text TEXT)')
        self.writer.execute('INSERT INTO fixture VALUES(1,?)', ('synthetic original',))

    def reader(self):
        reader = MultipleCipherConnection(self.path, self.raw, 'wcdb4-raw')
        self.addCleanup(reader.close)
        return reader

    def test_readonly_write_wrong_key_and_closed_connection(self):
        reader = self.reader()
        self.assertEqual(reader.query('SELECT text FROM fixture'), [{'text':'synthetic original'}])
        with self.assertRaises(AXRError):
            reader.query('INSERT INTO fixture VALUES(4,?)', ('must reject',))
        with self.assertRaises(AXRError):
            reader.query('UPDATE fixture SET text=?', ('must reject',))
        with self.assertRaisesRegex(AXRError, 'key_profile_schema_or_query_failed'):
            MultipleCipherConnection(self.path, 'cd'*32, 'wcdb4-raw')
        reader.close()
        reader.interrupt()
        reader.close()
        with self.assertRaisesRegex(AXRError, 'connection_closed'):
            reader.query('SELECT 1')

    def test_committed_wal_pinned_and_uncommitted_hidden_then_close_releases(self):
        reader = self.reader()
        reader.query('BEGIN')
        self.assertEqual(reader.query('SELECT count(*) AS n FROM fixture'), [{'n':1}])
        self.writer.execute('INSERT INTO fixture VALUES(2,?)', ('synthetic committed',))
        self.assertEqual(reader.query('SELECT count(*) AS n FROM fixture'), [{'n':1}])
        reader.close()
        fresh = self.reader()
        self.assertEqual(fresh.query('SELECT count(*) AS n FROM fixture'), [{'n':2}])
        self.writer.execute('BEGIN')
        self.writer.execute('INSERT INTO fixture VALUES(3,?)', ('synthetic pending',))
        try:
            self.assertEqual(fresh.query('SELECT count(*) AS n FROM fixture'), [{'n':2}])
        finally:
            self.writer.execute('ROLLBACK')

    def test_password_normalized_page_key_not_derived_twice(self):
        path = Path(self.tmp.name) / 'password.db'
        password = bytes(range(32))
        writer = apsw.Connection(str(path))
        try:
            writer.pragma('cipher', 'sqlcipher')
            writer.pragma('legacy', 4)
            writer.pragma('hexkey', password.hex())
            writer.execute('CREATE TABLE fixture(value TEXT)')
            writer.execute('INSERT INTO fixture VALUES(?)', ('synthetic password fixture',))
        finally:
            writer.close()
        effective = verified_page_key(path.read_bytes()[:4096], password, 'password')
        self.assertIsNotNone(effective)
        reader = MultipleCipherConnection(path, effective.hex(), 'wcdb4-raw')
        try:
            self.assertEqual(reader.query('SELECT value FROM fixture'), [{'value':'synthetic password fixture'}])
        finally:
            reader.close()
        with self.assertRaises(AXRError):
            MultipleCipherConnection(path, password.hex(), 'wcdb4-raw')

    def test_result_cell_and_vm_budgets_fail_without_partial_results(self):
        reader = self.reader()
        with self.assertRaisesRegex(AXRError, 'result_budget_exceeded'):
            reader.query('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1002) SELECT x FROM n')
        with self.assertRaisesRegex(AXRError, 'cell_budget_exceeded'):
            reader.query('SELECT zeroblob(1048577) AS value')
        with patch('adapters.sqlite3mc.time.monotonic', side_effect=itertools.chain([0], itertools.repeat(6))):
            with self.assertRaisesRegex(AXRError, 'query_failed_not_empty_result'):
                reader.query('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000) SELECT sum(x) FROM n')
        self.assertEqual(reader.query('SELECT 1 AS n'), [{'n':1}])

    def test_interrupt_is_not_blocked_by_query_lock_and_reader_recovers(self):
        reader = self.reader()
        active = threading.Event()
        errors = []
        calls = [0]
        clock = time.monotonic
        def progress_clock():
            calls[0] += 1
            if calls[0] > 1:
                active.set()
            return clock()
        def query():
            try:
                reader.query('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n')
            except AXRError as exc:
                errors.append(str(exc))
        with patch('adapters.sqlite3mc.time.monotonic', side_effect=progress_clock):
            worker = threading.Thread(target=query)
            worker.start()
            try:
                self.assertTrue(active.wait(2), 'query did not reach VM progress callback')
                reader.interrupt()
            finally:
                worker.join(6)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ['database_query_failed_not_empty_result'])
        self.assertEqual(reader.query('SELECT 1 AS n'), [{'n':1}])

    def test_database_adapter_uses_normalized_keys_and_preserves_identity_pagination(self):
        chat = 'fixture-peer'
        table = 'Msg_' + hashlib.md5(chat.encode()).hexdigest()
        self.writer.execute('CREATE TABLE Name2Id(user_name TEXT)')
        self.writer.executemany('INSERT INTO Name2Id(rowid,user_name) VALUES(?,?)', [(7,'fixture-self'), (19,chat)])
        self.writer.execute(f'CREATE TABLE "{table}"(server_id INTEGER,create_time INTEGER,local_type INTEGER,'
                            'real_sender_id INTEGER,message_content BLOB)')
        self.writer.executemany(f'INSERT INTO "{table}" VALUES(?,100,1,19,?)', [(10,'fixture one'), (11,'fixture two')])
        key = bytes.fromhex(self.raw)
        class Secrets:
            def get(self, reference):
                self_outer.assertEqual(reference, 'fixture-key')
                return key
        self_outer = self
        adapter = DatabaseAdapter({'engine':'sqlite3mc','account_id':'fixture-self',
            'conversations':[{'conversation_id':chat,'schema':'v4'}],
            'shards':[{'path':str(self.path),'key_reference':'fixture-key','cipher_profile':'wcdb4-raw'}]}, Secrets())
        try:
            first = adapter.search(chat, limit=1)
            self.assertEqual(first, adapter.search(chat, limit=1))
            second = adapter.search(chat, limit=1, after=first['cursor'])
            self.assertNotEqual(first['messages'][0]['reference'], second['messages'][0]['reference'])
            self.assertEqual(first['messages'][0]['sender'], chat)
            self.assertFalse(first['messages'][0]['outgoing'])
            self.assertEqual(adapter.connections, {})
            self.assertEqual(adapter.status()['engine'], 'sqlite3mc')
        finally:
            adapter.close()

    def test_contact_qualification_uses_explicit_engine_and_rejects_duplicate_labels(self):
        self.writer.execute('CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT,delete_flag INTEGER)')
        self.writer.executemany('INSERT INTO contact VALUES(?,?,?,0)',
                               [('fixture-self','fixture-self',''), ('fixture-peer','peer','test label')])
        bindings = qualify_contacts(self.path, None, bytes.fromhex(self.raw), 'fixture-self',
                                    ['test label'], engine='sqlite3mc')
        self.assertEqual(bindings[0]['conversation_id'], 'fixture-peer')
        self.writer.execute('INSERT INTO contact VALUES(?,?,?,0)', ('fixture-other','other','test label'))
        with self.assertRaisesRegex(AXRError, 'missing_or_ambiguous'):
            qualify_contacts(self.path, None, bytes.fromhex(self.raw), 'fixture-self',
                             ['test label'], engine='sqlite3mc')

    def test_cross_engine_native_sqlcipher_raw_key_and_committed_wal(self):
        library = os.environ.get('AXR_SQLCIPHER_LIBRARY')
        if not library:
            self.skipTest('native SQLCipher library not provided for cross-engine qualification')
        # SQLite3mc-created encrypted WAL -> original SQLCipher C ABI reader.
        reader = CipherConnection(self.path, library, self.raw, 'wcdb4-raw')
        try:
            self.assertEqual(reader.query('SELECT text FROM fixture'), [{'text':'synthetic original'}])
        finally:
            reader.close()
        # Native SQLCipher-created encrypted WAL -> optional reader.
        path = Path(self.tmp.name) / 'native.db'
        writer = object.__new__(CipherConnection)
        writer.lib = C.CDLL(library)
        writer.handle = C.c_void_p()
        writer._declare()
        self.assertEqual(writer.lib.sqlite3_open_v2(str(path).encode(), C.byref(writer.handle), 6, None), 0)
        try:
            writer.query('PRAGMA key="x\'' + self.raw + '\'"')
            writer.query('PRAGMA journal_mode=WAL')
            writer.query('CREATE TABLE fixture(value TEXT)')
            writer.query('INSERT INTO fixture VALUES(?)', ('synthetic native fixture',))
            reader = MultipleCipherConnection(path, self.raw, 'wcdb4-raw')
            try:
                self.assertEqual(reader.query('SELECT value FROM fixture'), [{'value':'synthetic native fixture'}])
            finally:
                reader.close()
        finally:
            writer.close()


if __name__ == '__main__':
    unittest.main()
