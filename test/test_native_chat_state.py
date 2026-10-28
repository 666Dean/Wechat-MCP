# SPDX-License-Identifier: MIT
"""Mac witness semantics through actual encrypted native WCDB fixture reads."""
import ctypes as C
import os
import unittest
from axr.aet import AXRError,canonical
from axr_applications.wechat_chat_state import NativeCachedDraftWitness
from axr_applications.wechat_database import NativeDatabase
import test_native_wechat_credentials as fixtures


class NativeChatState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.NativeWeChatCredentialsTests.setUpClass()
    def setUp(self):
        self.f=fixtures.NativeWeChatCredentialsTests('test_navigation_exact_witness')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.database=NativeDatabase(self.f.consumer,self.f.account)
        self.window={'pid':123,'window_id':456,'executable_hash':'synthetic-window-build'}
        self.calls=0
    def check(self):self.calls+=1
    def mutate(self,sql):
        handle=C.c_void_p()
        self.assertEqual(self.f.api.sqlite3_open_v2(os.fsencode(self.f.path),C.byref(handle),2,None),0)
        try:
            key=("x'"+self.f.key.hex()+"'").encode()
            self.assertEqual(self.f.api.sqlite3_key(handle,key,len(key)),0)
            self.assertEqual(self.f.api.sqlite3_exec(handle,sql.encode(),None,None,None),0)
        finally:self.f.api.sqlite3_close_v2(handle)
    def observe(self):
        return NativeCachedDraftWitness.observe(self.database,self.f.account,self.f.peer,
            'exact fixture draft',self.window,self.check,clock=lambda:90.,monotonic=lambda:500.)
    def activate(self,witness,**changes):
        parameters={'database':self.database,'account':self.f.account,'recipient':self.f.peer,
            'text':'exact fixture draft','query':'Fixture peer','window':self.window,
            'search_started':99.,'check':self.check,'clock':lambda:101.,'monotonic':lambda:503.}
        parameters.update(changes)
        return witness.activate(**parameters)
    def test_cached_then_consumed_draft_and_fresh_search_produce_sealed_binding(self):
        witness=self.observe()
        self.mutate("UPDATE SessionTable SET draft=''")
        binding=self.activate(witness)
        self.assertEqual(binding['recipient_assurance'],'cached_exact_draft_and_fresh_search')
        self.assertEqual(len(binding['recipient_witness']),64)
        self.assertNotIn('exact fixture draft',str(binding))
        self.assertGreaterEqual(self.calls,10)
    def test_owner_catalog_reads_only_private_metadata_and_detects_duplicate_or_missing_self(self):
        configuration={**self.f.config,'resources':[*self.f.config['resources'],{
            'platform':'wechat','account_id':self.f.account,'conversation_id':self.f.account}]}
        consumer=self.f.module.fixture_consumer('fixture-owner-catalog',canonical(configuration).decode(),{'fixture-key':self.f.key})
        self.database=NativeDatabase(consumer,self.f.account)
        rows=self.database.catalog(self.check)
        self.assertEqual({r['conversation_id'] for r in rows},{self.f.account,self.f.peer})
        self.assertTrue(all(set(r)=={'conversation_id','display_name','data_class'} for r in rows))
        self.mutate("INSERT INTO contact VALUES('fixture-group@chatroom','Fixture group','',0)")
        self.assertEqual(len(self.database.catalog(self.check)),2)
        self.mutate("INSERT INTO contact SELECT * FROM contact WHERE username='"+self.f.peer+"'")
        with self.assertRaisesRegex(AXRError,'catalog_invalid'):self.database.catalog(self.check)
        self.mutate("DELETE FROM contact WHERE username='"+self.f.account+"'")
        with self.assertRaisesRegex(AXRError,'self_identity_missing'):self.database.catalog(self.check)
    def test_same_text_cached_in_another_conversation_is_rejected_natively(self):
        self.mutate("INSERT INTO SessionTable VALUES('fixture-other','exact fixture draft')")
        with self.assertRaisesRegex(RuntimeError,'unique_draft'):self.observe()
    def test_ambiguous_fresh_search_or_changed_user_draft_never_produces_binding(self):
        witness=self.observe()
        self.mutate("INSERT INTO SearchRecent VALUES('fixture-other','Fixture peer',100)")
        with self.assertRaisesRegex(AXRError,'unique_fresh_search'):self.activate(witness)
        self.mutate("DELETE FROM SearchRecent WHERE username='fixture-other'; UPDATE SessionTable SET draft='user draft'")
        with self.assertRaisesRegex(AXRError,'activated_draft_changed'):self.activate(witness)
    def test_expiry_clock_rollback_and_scope_substitution_rejected_before_reads(self):
        witness=self.observe()
        for change,code in (({'clock':lambda:151.},'expired'),({'monotonic':lambda:499.},'expired'),
                ({'account':'other'},'scope_changed'),({'window':{**self.window,'window_id':999}},'scope_changed'),
                ({'search_started':89.},'fresh_post_cache')):
            with self.subTest(change=change),self.assertRaisesRegex(AXRError,code):self.activate(witness,**change)
    def test_revocation_and_wrong_account_stop_before_native_query(self):
        def revoked():raise AXRError('synthetic_revoked')
        with self.assertRaisesRegex(AXRError,'synthetic_revoked'):
            NativeCachedDraftWitness.observe(self.database,self.f.account,self.f.peer,
                'exact fixture draft',self.window,revoked)
        with self.assertRaisesRegex(AXRError,'account_mismatch'):
            NativeCachedDraftWitness.observe(self.database,'other',self.f.peer,
                'exact fixture draft',self.window,self.check)
