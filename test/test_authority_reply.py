# SPDX-License-Identifier: MIT
"""Complete reply transaction against a synthetic UI/cache/message state machine."""
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from axr.aet import AXRError
from axr_applications.wechat_reply import ReplyExecutor, ReplyPlan


class ReplyTransaction(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.plan = ReplyPlan('fixture-owner', 'fixture-peer', 'fixture-park',
                              'Fixture peer', 'Fixture park', 'Synthetic reply', 'fixture-task')
        self.wall, self.mono, self.revoked = 1000., 100., False
        self.active, self.input = 'fixture-park', ''
        self.cache = {'fixture-peer':'', 'fixture-park':''}
        self.recent, self.sent, self.stages, self.observed = [], 0, 0, []
        self.lose_response, self.observe_failure, self.ambiguous, self.changed_window = False, False, False, False
        fixture = self
        class Database:
            account = 'fixture-owner'
            def navigation(db, cid, kind, check, **parameters):
                check()
                if kind == 'draft':return [{'draft':fixture.cache[cid], 'size':len(fixture.cache[cid].encode())}]
                if kind == 'recent':return list(fixture.recent)
                if kind == 'unique_draft':
                    return [{'username':cid, 'draft':text} for cid,text in fixture.cache.items()
                            if parameters['text'] in text]
                raise AssertionError(kind)
            def search(db, cid, *, check, after, **parameters):
                check()
                if fixture.sent and fixture.observe_failure:raise AXRError('synthetic_observation_failure')
                return {'messages':list(fixture.observed) if fixture.sent else [],
                        'cursor':{'fixture':[1000,1]} if fixture.sent else {}, 'has_more':False}
        self.database = Database()
        self.executor = ReplyExecutor(self.database, self.directory.name, clock=lambda:self.wall,
            monotonic=lambda:self.mono, pause=lambda seconds:None, observation_rounds=2)
    def check(self):
        if self.revoked:raise AXRError('synthetic_revoked')
        self.wall += .001;self.mono += .001
    def binding(self,cid,check):
        check()
        return {'pid':12, 'window_id':2 if self.changed_window and self.stages else 1}
    def local(self,resource,kind,parameters,operation,check):
        check();value=operation(check);check();return value
    def native(self,action,check):
        check();mode=action.payload['mode'];data={'send_invoked':False}
        if mode == 'navigate':
            label=action.payload['text'];cid=self.plan.recipient if label == self.plan.label else self.plan.parking
            self.cache[self.active]=self.input;self.active=cid;self.input=self.cache[cid]
            self.recent=[{'username':cid,'query':label,'last_click_time':self.wall}]
            if self.ambiguous:self.recent.append({**self.recent[0],'username':'fixture-other'})
            data.update(navigation_invoked=True,query_input_submitted=True,main_window_verified=True)
        elif mode == 'stage_draft':
            if self.input and action.payload['visual_binding'].get('draft_policy')!='replace':raise AXRError('existing_draft_never_overwrite')
            self.stages+=1;self.input=action.payload['text'];data['draft_match']=True
        elif mode == 'read_draft':data['draft_match']=self.input==action.payload['text']
        elif mode == 'send':
            self.assertEqual(action.payload['visual_binding']['recipient_assurance'],
                             'cached_exact_draft_and_fresh_search')
            self.assertEqual(self.input, self.plan.text)
            self.sent+=1;data['send_invoked']=True
            if not self.observed:self.observed=[self.row()]
            if self.lose_response:raise AXRError('synthetic_lost_response')
        else:raise AssertionError(mode)
        return {'receipt':{'state':'Unknown' if mode=='send' else 'Completed'}, 'native':data}
    def row(self,**changes):
        return {'reference':'fixture-outbound', 'text':self.plan.text, 'sender':self.plan.account,
                'outgoing':True, 'server_id':123, **changes}
    def submit(self,**changes):
        return self.executor.submit(changes.pop('plan',self.plan),principal='fixture-agent',purpose='fixture',
            sources=(),binding=self.binding,native=self.native,local=self.local,check=self.check,**changes)
    def test_full_switch_witness_compare_submit_observe_keeps_native_unknown_and_cannot_replay(self):
        result=self.submit()
        self.assertEqual(result['state'],'Observed');self.assertEqual(result['native_state'],'Unknown')
        self.assertFalse(result['retry']);self.assertFalse(result['delivery_confirmed'])
        self.assertEqual((self.stages,self.sent),(1,1))
        with self.assertRaisesRegex(AXRError,'previous_attempt'):self.submit()
        self.assertEqual(self.sent,1)
    def test_lost_native_response_is_observed_without_a_second_invocation(self):
        self.lose_response=True
        result=self.submit()
        self.assertTrue(result['database_record_observed']);self.assertIsNone(result['send_invoked'])
        self.assertEqual(self.sent,1)
    def test_existing_user_draft_and_ambiguous_search_never_stage_or_send(self):
        self.cache['fixture-peer']='User draft'
        with self.assertRaisesRegex(AXRError,'preserved'):self.submit()
        self.assertEqual((self.stages,self.sent),(0,0))
        self.cache['fixture-peer']='';self.ambiguous=True
        with self.assertRaisesRegex(AXRError,'fresh_navigation'):self.submit()
        self.assertEqual((self.stages,self.sent),(0,0))
    def test_changed_window_preserves_staged_draft_and_never_sends(self):
        self.changed_window=True
        with self.assertRaisesRegex(AXRError,'scope_changed'):self.submit()
        self.assertEqual((self.stages,self.sent),(1,0))
        self.assertEqual(self.input,self.plan.text)
    def test_explicit_draft_replacement_keeps_witness_observation_and_permanent_attempt(self):
        self.cache['fixture-peer']='Synthetic unsent draft'
        result=self.submit(overwrite_drafts=True)
        self.assertEqual(result['state'],'Observed');self.assertEqual((self.stages,self.sent),(1,1))
        with self.assertRaisesRegex(AXRError,'previous_attempt'):self.submit(overwrite_drafts=True)
    def test_unknown_or_truncated_draft_cannot_be_replaced(self):
        original=self.local
        for row in ({'draft':'x','size':2},{'draft':'','size':True},{'draft':None,'size':0},{'draft':'x','size':16001}):
            with self.subTest(row=row):
                self.local=lambda resource,kind,parameters,operation,check:[row] if kind=='draft' else original(resource,kind,parameters,operation,check)
                with self.assertRaisesRegex(AXRError,'preserved'):self.submit(overwrite_drafts=True)
                self.assertEqual((self.stages,self.sent),(0,0))
        with self.assertRaisesRegex(AXRError,'policy_invalid'):self.submit(overwrite_drafts=1)
    def test_live_draft_appearing_after_empty_cache_is_preserved_without_replacement(self):
        original=self.native
        def change(action,check):
            if action.payload['mode']=='stage_draft':self.input='Synthetic user typing'
            return original(action,check)
        self.native=change
        with self.assertRaisesRegex(AXRError,'never_overwrite'):self.submit()
        self.assertEqual(self.input,'Synthetic user typing');self.assertEqual(self.sent,0)
    def test_sender_direction_server_id_full_text_and_unique_record_are_independently_required(self):
        for changes in ({'sender':'other'},{'outgoing':False},{'server_id':0},
                        {'server_id':True},{'text':'partial'},{'text_truncated':True}):
            with self.subTest(changes=changes):
                self.setUp();self.observed=[self.row(**changes)]
                result=self.submit()
                self.assertFalse(result['database_record_observed']);self.assertEqual(result['state'],'Unknown')
        self.setUp();self.observed=[self.row(),self.row(reference='duplicate',server_id=124)]
        self.assertEqual(self.submit()['exact_database_records'],2)
    def test_observation_failure_after_send_is_unknown_and_marker_survives(self):
        self.observe_failure=True
        result=self.submit()
        self.assertEqual(result['state'],'Unknown');self.assertFalse(result['observation_complete'])
        self.assertEqual(len(list(Path(self.directory.name).glob('reply-*.json'))),1)
    def test_revocation_and_clock_rollback_before_input_stop_immediately(self):
        self.revoked=True
        with self.assertRaisesRegex(AXRError,'revoked'):self.submit()
        self.assertEqual(self.stages,0)
        self.revoked=False
        original=self.binding
        def rollback(cid,check):
            self.wall-=100
            return original(cid,check)
        self.binding=rollback
        with self.assertRaisesRegex(AXRError,'clock_rollback'):self.submit()
        self.assertEqual(self.stages,0)
    def test_cancel_after_send_preserves_unknown_without_observation_or_replay(self):
        original=self.native
        def cancelled(action,check):
            result=original(action,check)
            if action.operation=='messages.send':self.revoked=True
            return result
        self.native=cancelled
        result=self.submit()
        self.assertEqual(result['state'],'Unknown');self.assertEqual(self.sent,1)
        self.assertFalse(result['retry'])
    def test_invalid_parking_and_parallel_account_transaction_are_rejected(self):
        with self.assertRaisesRegex(AXRError,'distinct_parking'):
            self.submit(plan=replace(self.plan,parking=self.plan.recipient))
        self.executor.lock.acquire()
        try:
            with self.assertRaisesRegex(AXRError,'busy'):self.submit()
        finally:self.executor.lock.release()


if __name__=='__main__':unittest.main()
