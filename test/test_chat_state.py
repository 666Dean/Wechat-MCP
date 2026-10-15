# SPDX-License-Identifier: MIT
"""Cached -> active draft transitions use synthetic SQLite account data only."""
import sqlite3
import unittest
try:
    from adapters.macos.chat_state import CachedDraftWitness
    from axr.aet import AXRError
except ModuleNotFoundError as exc:
    if exc.name=='axr':raise unittest.SkipTest('optional AXR SDK unavailable') from exc
    raise


class Connection:
    def __init__(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('CREATE TABLE SessionTable(username TEXT,draft TEXT);CREATE TABLE SearchRecent(username TEXT,query TEXT,last_click_time INTEGER);')
    def query(self,sql,parameters=()):return [dict(r) for r in self.db.execute(sql,parameters).fetchall()]


class ChatStateTests(unittest.TestCase):
    def setUp(self):
        self.c=Connection();self.addCleanup(self.c.db.close)
        self.c.db.execute('INSERT INTO SessionTable VALUES(?,?)',('fixture-peer','fixture reply'))
        self.window={'pid':123,'window_id':456,'title':'微信','bounds':{'X':1,'Y':2,'Width':800,'Height':600}}
        self.now=100.;self.mono=500.;self.checks=0
    def check(self):self.checks+=1
    def observe(self):return CachedDraftWitness.observe(self.c,'fixture-account','fixture-peer','fixture reply',self.window,self.check,clock=lambda:self.now,monotonic=lambda:self.mono)
    def select(self):
        self.c.db.execute('UPDATE SessionTable SET draft=?',('',))
        self.c.db.execute('INSERT INTO SearchRecent VALUES(?,?,?)',('fixture-peer','fixture label',102))
        self.now=103.;self.mono=503.
    def activate(self,witness,**kw):
        params=dict(account='fixture-account',recipient='fixture-peer',text='fixture reply',query='fixture label',window=self.window,search_started=102.,check=self.check,clock=lambda:self.now,monotonic=lambda:self.mono)
        params.update(kw);return witness.activate(self.c,self.c,**params)
    def test_consumed_cache_requires_prior_exact_snapshot_and_fresh_selection(self):
        witness=self.observe();self.select();binding=self.activate(witness)
        self.assertEqual(binding['recipient_assurance'],'cached_exact_draft_and_fresh_search')
        self.assertEqual(len(binding['recipient_witness']),64)
        self.assertNotIn('fixture reply',str(binding));self.assertGreaterEqual(self.checks,5)
        with self.assertRaisesRegex(AXRError,'unique_exact_cached_draft_required'):self.observe()
    def test_wrong_or_ambiguous_selected_contact_rejected(self):
        witness=self.observe();self.select()
        self.c.db.execute('UPDATE SearchRecent SET username=?',('fixture-other',))
        with self.assertRaisesRegex(AXRError,'unique_fresh_search_identity_required'):self.activate(witness)
        self.c.db.execute('INSERT INTO SearchRecent VALUES(?,?,?)',('fixture-peer','fixture label',102))
        with self.assertRaisesRegex(AXRError,'unique_fresh_search_identity_required'):self.activate(witness)
    def test_oversized_matching_cache_is_not_copied_out_of_sqlite(self):
        self.c.db.execute('UPDATE SessionTable SET draft=?',('fixture reply'+'x'*20000,))
        original=self.c.query;observed=[]
        def query(sql,parameters=()):
            rows=original(sql,parameters);observed.extend(rows);return rows
        self.c.query=query
        with self.assertRaisesRegex(AXRError,'unique_exact_cached_draft_required'):self.observe()
        self.assertIsNone(observed[0]['draft'])
    def test_same_text_in_another_cached_conversation_rejected(self):
        self.c.db.execute('INSERT INTO SessionTable VALUES(?,?)',('fixture-other','fixture reply'))
        with self.assertRaisesRegex(AXRError,'unique_exact_cached_draft_required'):self.observe()
    def test_new_user_draft_and_scope_substitution_rejected(self):
        witness=self.observe();self.select();self.c.db.execute('UPDATE SessionTable SET draft=?',('user draft',))
        with self.assertRaisesRegex(AXRError,'activated_draft_changed'):self.activate(witness)
        for kw in ({'account':'other'},{'recipient':'other'},{'text':'other'},{'window':{**self.window,'window_id':999}}):
            with self.subTest(kw=kw),self.assertRaisesRegex(AXRError,'cached_draft_scope_changed'):self.activate(witness,**kw)
    def test_expiry_clock_rollback_and_old_navigation_rejected(self):
        witness=self.observe();self.select()
        self.now=164.;self.mono=564.
        with self.assertRaisesRegex(AXRError,'cached_draft_witness_expired'):self.activate(witness)
        self.now=99.;self.mono=503.
        with self.assertRaisesRegex(AXRError,'cached_draft_witness_expired'):self.activate(witness)
        self.now=103.
        with self.assertRaisesRegex(AXRError,'fresh_post_cache_navigation_required'):self.activate(witness,search_started=99.)
    def test_revocation_check_precedes_and_follows_source_reads(self):
        def revoked():raise AXRError('revoked')
        with self.assertRaisesRegex(AXRError,'revoked'):
            CachedDraftWitness.observe(self.c,'fixture-account','fixture-peer','fixture reply',self.window,revoked)
        witness=self.observe();self.select()
        with self.assertRaisesRegex(AXRError,'revoked'):self.activate(witness,check=revoked)
