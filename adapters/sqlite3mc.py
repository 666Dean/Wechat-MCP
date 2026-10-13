# SPDX-License-Identifier: MIT
"""Explicit optional SQLite3mc reader. Only normalized raw SQLCipher-4 keys."""
import re
import threading
import time
from pathlib import Path
from axr.aet import AXRError


class MultipleCipherConnection:
    def __init__(self, path, key, profile):
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', key):
            raise AXRError('invalid_database_key')
        if profile not in ('sqlcipher4', 'wcdb4-raw'):
            raise AXRError('sqlite3mc_cipher_profile_not_qualified')
        try:
            import apsw
        except ModuleNotFoundError:
            raise AXRError('sqlite3mc_optional_dependency_missing') from None
        if (apsw.apswversion() != '3.53.4.0' or
                getattr(apsw, 'mc_version', None) != 'SQLite3 Multiple Ciphers 2.4.0'):
            raise AXRError('sqlite3mc_version_not_qualified')
        self.apsw = apsw
        self.db = None
        self.query_lock = threading.RLock()
        self.life_lock = threading.RLock()
        try:
            self.db = apsw.Connection(Path(path).resolve(strict=True).as_uri() + '?mode=ro',
                                      flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI)
            self.db.set_busy_timeout(1000)
            self.db.pragma('cipher', 'sqlcipher')
            self.db.pragma('legacy', 4)
            self.db.pragma('hmac_check', True)
            # hexkey would derive AGAIN. Owner imports already normalized the
            # password per database; use the documented raw key form instead.
            self.db.pragma('key', 'raw:' + key)
            self.db.pragma('query_only', True)
            self.db.pragma('trusted_schema', False)
            self.db.pragma('temp_store', 'MEMORY')
            self.query('SELECT count(*) FROM sqlite_master')
        except (apsw.Error, AXRError):
            self.close()
            raise AXRError('database_key_profile_schema_or_query_failed') from None
        except BaseException:
            self.close()
            raise

    def query(self, sql, parameters=()):
        with self.query_lock:
            if self.db is None:
                raise AXRError('database_connection_closed')
            deadline = time.monotonic() + 5
            self.db.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
            cursor = self.db.cursor()
            try:
                rows = []
                for values in cursor.execute(sql, parameters):
                    if len(rows) >= 1001:
                        raise AXRError('database_result_budget_exceeded')
                    row = {}
                    for (name, *_), value in zip(cursor.get_description(), values):
                        if isinstance(value, (str, bytes)):
                            size = len(value.encode('utf8')) if isinstance(value, str) else len(value)
                            if size > 1024 * 1024:
                                raise AXRError('database_cell_budget_exceeded')
                        row[name] = value
                    rows.append(row)
                return rows
            except self.apsw.Error:
                raise AXRError('database_query_failed_not_empty_result') from None
            finally:
                cursor.close()
                self.db.set_progress_handler(None)

    def interrupt(self):
        with self.life_lock:
            if self.db is not None:
                self.db.interrupt()

    def close(self):
        with self.query_lock, self.life_lock:
            if self.db is not None:
                self.db.close()
                self.db = None
