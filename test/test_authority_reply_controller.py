# SPDX-License-Identifier: MIT
"""Signed-owner plan -> native Guard -> async synthetic UI -> independent observation."""
from dataclasses import replace
from types import SimpleNamespace
import time
import threading
import unittest
from axr.aet import AXRError, Resource, canonical, digest
from axr_applications.wechat_controller import AuthorityReplyController
from axr_applications.wechat_mcp import WeChatMCPApplication
from test import test_security_authority as fixtures
from test import test_authority_reply as transactions


class ReplyController(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AuthorityTests('test_owner_presence_task_access_handler_claim_and_unknown_no_retry')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.tx = transactions.ReplyTransaction('test_full_switch_witness_compare_submit_observe_keeps_native_unknown_and_cannot_replay')
        self.tx.setUp();self.addCleanup(self.tx.doCleanups)
        f, tx = self.f, self.tx
        resources = [Resource('wechat',tx.plan.account,cid) for cid in (tx.plan.recipient,tx.plan.parking,'axr:application-ui')]
        f.c = replace(f.c,application='wechat',goal_digest=digest('fixture-reply'),
            operations=('messages.read','messages.send','application.navigate','application.draft','status.read'),
            resources=tuple(r.key for r in resources),sources=tuple(r.key for r in resources),
            destinations=('local','wechat:'+resources[0].key),outputs=('ReplyDraft',),max_uses=100)
        f.k.identity=lambda peer:{'agent':peer.principal,'application':'wechat','identity_verified':True}
        f.k.wechat_registry=SimpleNamespace(user='fixture-user',enroll=lambda *a:None,accept=lambda a:f.handler)
        f.k.wechat_handlers={}
        self.app=WeChatMCPApplication(f.k,tx.database,tx.plan.account,[r.conversation_id for r in resources],
                                    f.handler,destination='model:fixture')
        configuration={'helper':'fixture-helper','helper_sha256':'0'*64,'endpoint':'fixture',
            'attribution_prefix':'Synthetic ',
            'profiles':{tx.plan.recipient:{'label':tx.plan.label,'visual_binding':{'cid':tx.plan.recipient}},
                        tx.plan.parking:{'label':tx.plan.parking_label,'visual_binding':{'cid':tx.plan.parking}}}}
        class Bridge:
            def __init__(bridge,*args,**options):bridge.options=options
            def invoke(bridge,action,check):
                check();bridge.options['enroll_handler']({'pid':f.handler.pid,'birth':f.handler.birth})
                proof=bridge.options['prepare'](action,{'pid':f.handler.pid,'birth':f.handler.birth})
                f.k.claim_commit(f.handler,proof)
                try:
                    if action.payload['mode']=='binding':
                        data={'binding':tx.binding(action.payload['visual_binding']['cid'],check),
                              'main_window_verified':True,'send_invoked':False}
                    else:data=tx.native(action,check)['native']
                    f.k.observe(f.handler,proof,verified=action.operation!='messages.send',evidence_digest=digest(data))
                    return {'native':data,'receipt':bridge.options['receipt'](action.execution_id)}
                except Exception:
                    f.k.observe(f.handler,proof,verified=False,evidence_digest=digest('synthetic-lost'))
                    raise
        self.controller=AuthorityReplyController(self.app,configuration,executor=tx.executor,bridge_factory=Bridge)
        self.app.replies=self.controller
        f.k.application=self.app.dispatch;f.k.application_owner=self.app.owner_dispatch
        f.k.application_close=self.controller.close
        f.s.revoke_domain=self.controller.stop
        f.k.integrity.persist()
        self.capability=f.authorize()
        f.guard._issue_owner(principal=f.client.principal,resource=resources[0],operations=['messages.read'],
            purpose=f.c.goal_digest,expires_at=f.c.expires,max_uses=100,classes=['personal'])
        f.k.integrity.persist()
        self.draft=self.app.remember(f.client,f.c.body(),resources[0],
            {'kind':'manual-draft','text':tx.plan.text,'sources':[{
                'resource':{'platform':'wechat','account_id':tx.plan.account,'conversation_id':tx.plan.recipient},
                'reference':'synthetic-inbound','data_class':'personal'}]})
    def call(self,method,**parameters):
        return self.f.call(self.f.client,'Application',method=method,parameters=parameters,capability=self.capability)
    def propose(self):
        return self.call('submit_reply',conversation_id=self.tx.plan.recipient,draft_id=self.draft)
    def approve(self,handle):
        f=self.f
        review=f.call(f.owner,'Authorize',phase='review-application',job_id=handle)
        return f.call(f.owner,'Authorize',phase='approve-application',job_id=handle,
            challenge_id=review['challenge']['nonce'],owner_signature=f.ownerkey.sign(canonical(review['challenge'])).hex())
    def finish(self,handle):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            result=self.call('reply_status',job_id=handle)
            if result['state'] in ('Unknown','FailedSafe'):return result
            time.sleep(.01)
        self.fail('synthetic reply worker did not finish')
    def test_signed_exact_owner_plan_runs_without_holding_kernel_lock_and_unknown_never_replays(self):
        proposed=self.propose();self.assertEqual(proposed['state'],'AwaitingApproval')
        with self.assertRaises(AXRError):self.call('execute',job_id=proposed['id'])
        self.approve(proposed['id'])
        self.call('execute',job_id=proposed['id'])
        result=self.finish(proposed['id'])
        self.assertEqual(result['state'],'Unknown')
        self.assertTrue(result['observation']['database_record_observed'],result)
        self.assertEqual(self.tx.sent,1)
        self.call('execute',job_id=proposed['id'])
        self.assertEqual(self.tx.sent,1)
        self.assertTrue(self.f.k.integrity.verify())
        self.assertFalse(self.controller.active)
    def test_missing_send_task_scope_never_creates_approval_job(self):
        f=self.f
        f.c=replace(f.c,id='read-only',operations=('messages.read',))
        self.capability=f.authorize()
        self.draft=self.app.remember(f.client,f.c.body(),Resource('wechat',self.tx.plan.account,self.tx.plan.recipient),
            {'kind':'manual-draft','text':self.tx.plan.text,'sources':[]})
        with self.assertRaisesRegex(AXRError,'task_scope_incomplete'):self.propose()
        self.assertEqual(self.f.j.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.assertEqual(self.tx.sent,0)
    def test_separate_approval_setting_still_rejects_outside_scope_and_does_not_auto_start_old_jobs(self):
        proposed=self.propose();self.app.manual_approval_required=False
        with self.assertRaises(AXRError):self.call('execute',job_id=proposed['id'])
        second=self.propose();result=self.finish(second['id'])
        self.assertTrue(result['observation']['database_record_observed'],result)
        self.assertEqual(self.tx.sent,1)
    def test_source_taint_outside_signed_task_prevents_send_plan(self):
        resource=Resource('wechat',self.tx.plan.account,self.tx.plan.recipient)
        self.draft=self.app.remember(self.f.client,self.f.c.body(),resource,{'kind':'manual-draft',
            'text':self.tx.plan.text,'sources':[{'resource':{'platform':'wechat','account_id':self.tx.plan.account,
            'conversation_id':'other'},'reference':'tainted','data_class':'personal'}]})
        with self.assertRaisesRegex(AXRError,'source_outside_task_contract'):self.propose()
        self.assertEqual(self.tx.sent,0)
    def test_owner_revocation_prevents_even_prepared_worker_from_starting_input(self):
        proposed=self.propose();self.approve(proposed['id'])
        self.f.call(self.f.owner,'Revoke',scope=self.f.c.id)
        with self.assertRaises(AXRError):self.call('execute',job_id=proposed['id'])
        self.assertEqual(self.tx.stages,0)
    def test_scoped_parent_approval_revocation_stops_derived_work_without_a_policy_version_change(self):
        proposed=self.propose();self.approve(proposed['id'])
        arrived=threading.Event();resume=threading.Event();original=self.tx.binding
        def held(cid,check):
            arrived.set()
            if not resume.wait(3):raise AXRError('synthetic_wait_expired')
            return original(cid,check)
        self.tx.binding=held
        try:
            self.call('execute',job_id=proposed['id'])
            self.assertTrue(arrived.wait(2))
            with self.f.k.lock:
                context,job,action=self.app.pending(proposed['id'])
                before=self.f.guard.version
                self.f.guard.revoke_scoped(job['grant_id']);self.f.k.integrity.persist()
                self.assertEqual(before,self.f.guard.version)
        finally:resume.set()
        result=self.finish(proposed['id'])
        self.assertFalse(result['observation']['database_record_observed'])
        self.assertEqual((self.tx.stages,self.tx.sent),(0,0))


if __name__=='__main__':unittest.main()
