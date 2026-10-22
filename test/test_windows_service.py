# SPDX-License-Identifier: MIT
"""Shared dispatcher with real Guard, RSA proofs and synthetic application I/O."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from axr import _axr_native as native
from axr.aet import AXRError,canonical,digest
from axr_applications.wechat_windows_service import WindowsWeChatService
from axr_applications import windows_owner,wechat
import axr_applications
import test_wechat_service_v2 as fixtures


@unittest.skipUnless(sys.platform=='win32','Windows authority service adaptation')
class WindowsService(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ServiceTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.kernel=self.f.kernel;self.owner=self.f.owner;self.client=self.f.client
        self.config={**self.f.config,'manual_approval_required':True}
        module=SimpleNamespace(WeChatConsumer=lambda *args:None)
        with patch.object(axr_applications,'_wechat_credentials',module,create=True),patch(
                'axr_applications.wechat_service.NativeDatabase',fixtures.Database):
            self.service=WindowsWeChatService(self.kernel,SimpleNamespace(user='fixture-user'),self.config,'fixture-endpoint')
        self.kernel.wechat_service=self.service
        self.kernel.store.config=lambda:{'application':self.config}
        self.addCleanup(self.service.close)
        self.signer=self.f.owner_key
        self.binding=patch.object(self.service,'inspect_binding',return_value={'fixture':True});self.binding.start();self.addCleanup(self.binding.stop)
    def activate(self,**args):
        reviewed=self.service.review(self.owner,{'targets':'all','seconds':300,'max_replies':4,'automatic':False,**args})
        challenge=reviewed['challenge']
        return self.service.activate(self.owner,challenge['nonce'],self.signer.sign(canonical(challenge)).hex())
    def call(self,method,peer=None,**args):
        return self.kernel.dispatch(peer or self.client,{'operation':'WeChat','payload':{'method':method,'arguments':args}})
    def approve(self,handle):
        review=self.service.review_pending(self.owner,handle);challenge=review['challenge']
        return self.service.approve_pending(self.owner,challenge['nonce'],self.signer.sign(canonical(challenge)).hex())
    def test_rsa_hello_owner_activates_common_scope_and_scoped_child(self):
        from cryptography.hazmat.primitives.asymmetric import rsa,padding
        from cryptography.hazmat.primitives import hashes,serialization
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.signer=SimpleNamespace(sign=lambda value:key.sign(value,padding.PKCS1v15(),hashes.SHA256()))
        self.kernel.owner_public_key=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.activate(seconds=0,max_replies=0)
        contract=self.service.capability['body']['contract']
        self.assertEqual(len(contract['resources']),2);self.assertEqual(len(contract['sources']),1)
        self.assertGreater(contract['expires'],time.time());self.assertLessEqual(contract['expires'],time.time()+3600)
        self.assertTrue(self.kernel.integrity.verify())
    def test_pending_mcp_disclosure_is_body_free_and_delivered_exactly_once(self):
        self.activate();pending=self.call('wechat_read_messages',conversation_id='fixture-peer')
        self.assertEqual(pending['state'],'AwaitingDisclosureApproval');self.assertNotIn('synthetic-secret',json.dumps(pending))
        handle=pending['job_id'];metadata=self.call('wechat_job_status',job_id=handle)
        self.assertNotIn('page',metadata);self.assertNotIn('synthetic-secret',json.dumps(metadata))
        self.approve(handle)
        result=self.call('wechat_job_status',job_id=handle)
        self.assertEqual(result['state'],'Completed');self.assertIn('page',result)
        self.assertNotIn('synthetic-secret',json.dumps(result))
        self.assertNotIn('page',self.call('wechat_job_status',job_id=handle))
        self.assertNotIn('page',self.service.jobs[handle])
    def test_approval_is_bound_to_exact_content_and_cannot_replay(self):
        self.activate();pending=self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic reply',request_id='once')
        handle=pending['job_id'];review=self.service.review_pending(self.owner,handle);challenge=review['challenge']
        self.service.save_job(handle,{**self.service.jobs[handle],'text':'Changed synthetic reply'})
        signature=self.signer.sign(canonical(challenge)).hex()
        with self.assertRaisesRegex(AXRError,'review_changed'):self.service.approve_pending(self.owner,challenge['nonce'],signature)
        with self.assertRaisesRegex(AXRError,'review_changed'):self.service.approve_pending(self.owner,challenge['nonce'],signature)
        self.assertEqual(self.service.jobs[handle]['state'],'AwaitingApproval')
    def test_toggle_off_does_not_approve_old_jobs_and_toggle_on_catches_queued_jobs(self):
        self.activate();old=self.call('wechat_send_message',conversation_id='fixture-peer',text='First synthetic reply',request_id='old')
        self.config['manual_approval_required']=False
        self.service.process_pending();self.assertEqual(self.service.jobs[old['job_id']]['state'],'AwaitingApproval')
        new=self.call('wechat_send_message',conversation_id='fixture-peer',text='Second synthetic reply',request_id='new')
        self.assertEqual(new['state'],'Queued')
        self.config['manual_approval_required']=True;self.service.process_pending()
        self.assertEqual(self.service.jobs[new['job_id']]['state'],'AwaitingApproval')
    def test_incoming_batch_waits_before_inference_then_requires_separate_send_approval(self):
        self.activate(automatic=True)
        context=fixtures.Database().search('fixture-peer',check=lambda:None)['messages']
        job={'id':'inbound-fixture','conversation_id':'fixture-peer','operation':'reply.prepare','state':'Executing',
            'created':time.time(),'expires':time.time()+300,'retry':False}
        with patch.object(self.service,'infer',return_value='Synthetic answer') as infer:
            self.service.process_incoming(job['id'],job,context);infer.assert_not_called()
            self.assertEqual(self.service.jobs[job['id']]['state'],'AwaitingDisclosureApproval')
            self.assertNotIn('synthetic-secret',json.dumps(self.service.jobs[job['id']]))
            self.approve(job['id']);self.service.process_pending();infer.assert_called_once()
        current=self.service.jobs[job['id']]
        self.assertEqual(current['state'],'AwaitingApproval');self.assertNotIn('page',current)
        self.assertNotIn('approval',current)
        self.assertEqual(self.approve(job['id'])['state'],'Queued')
    def test_scope_stop_cancels_pending_and_restart_does_not_restore_it(self):
        self.activate();pending=self.call('wechat_read_messages',conversation_id='fixture-peer')
        handle=pending['job_id'];self.approve(handle);self.service.stop()
        self.assertEqual(self.service.jobs[handle]['state'],'FailedSafe');self.assertNotIn('page',self.service.jobs[handle])
        self.assertFalse(self.service.scope)
        with self.assertRaises(AXRError):self.call('wechat_job_status',job_id=handle+'-other')
    def test_foreign_client_cannot_consume_reviewed_disclosure_or_owner_methods(self):
        from dataclasses import replace
        self.activate();pending=self.call('wechat_read_messages',conversation_id='fixture-peer');self.approve(pending['job_id'])
        other=replace(self.client,witness='foreign-birth')
        with self.assertRaisesRegex(AXRError,'not_owned'):self.call('wechat_job_status',peer=other,job_id=pending['job_id'])
        with self.assertRaises(AXRError):self.kernel.dispatch(other,{'operation':'WeChatOwner','payload':{'method':'review_pending','arguments':{'job_id':pending['job_id']}}})
    def test_monotonic_scope_deadline_and_clock_rollback_both_stop(self):
        self.activate();wall,tick,duration=self.service.scope_clock
        self.service.scope_clock=(wall,tick-1000,duration)
        with self.assertRaisesRegex(AXRError,'stopped_or_expired'):self.service.check()
        self.service.scope_clock=(wall+1000,tick,duration)
        with self.assertRaisesRegex(AXRError,'stopped_or_expired'):self.service.check()
    def test_rejected_activation_cannot_replace_active_scope_clock(self):
        other=self.service.review(self.owner,{'targets':'all','seconds':0,'max_replies':0})['challenge']
        self.activate();original=self.service.scope_clock
        with self.assertRaisesRegex(AXRError,'review_expired_or_changed'):
            self.service.activate(self.owner,other['nonce'],self.signer.sign(canonical(other)).hex())
        self.assertEqual(self.service.scope_clock,original)
    def test_shared_loop_catches_up_deduplicates_and_waits_for_inference_approval(self):
        self.activate(seconds=0,max_replies=0);self.service.bursts.quiet_seconds=0;rounds=[]
        def wait(timeout):
            rounds.append(True)
            if len(rounds)==1:
                job=next(iter(self.service.jobs.values()))
                self.assertEqual(job['state'],'AwaitingDisclosureApproval');self.approve(job['id'])
            if len(rounds)==3:self.service.stop_event.set()
        with patch.object(self.service,'scan_targets',return_value=['fixture-peer']),patch.object(
                self.service,'infer',return_value='Synthetic generated draft') as infer,patch.object(
                self.service.worker_event,'wait',side_effect=wait),patch.object(self.service.navigation,'invoke') as ui:
            self.service.loop()
        self.assertEqual(len(self.service.jobs),1);self.assertEqual(next(iter(self.service.jobs.values()))['state'],'Draft')
        infer.assert_called_once();ui.assert_not_called();self.assertEqual(len(rounds),3)
        self.assertTrue(self.kernel.integrity.verify())
    def test_enabling_approval_during_execution_stops_before_next_phase(self):
        self.config['manual_approval_required']=False;self.activate()
        pending=self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic in-flight reply',request_id='switch')
        self.service.save_job(pending['job_id'],{**self.service.jobs[pending['job_id']],'state':'Executing'})
        self.service.context.executing_job=pending['job_id'];self.service.check()
        self.config['manual_approval_required']=True
        with self.assertRaisesRegex(AXRError,'exact_owner_approval_required'):self.service.check()
    def test_unapproved_incoming_batches_reserve_reply_budget(self):
        self.activate(automatic=True,max_replies=1);self.service.bursts.quiet_seconds=0;rounds=[]
        def wait(timeout):
            rounds.append(True)
            if len(rounds)==2:self.service.stop_event.set()
        with patch.object(self.service,'scan_targets',return_value=list(self.service.resources)),patch.object(
                self.service.worker_event,'wait',side_effect=wait),patch.object(self.service,'infer') as infer:
            self.service.loop()
        self.assertEqual(len(self.service.jobs),1);infer.assert_not_called()
        self.assertEqual(len(self.service.pending_jobs()),1);self.assertEqual(self.service.reply_count,0)
    def test_restart_marks_pending_disclosure_unknown_and_erases_body(self):
        self.activate();pending=self.call('wechat_read_messages',conversation_id='fixture-peer');self.approve(pending['job_id'])
        module=SimpleNamespace(WeChatConsumer=lambda *args:None)
        with patch.object(axr_applications,'_wechat_credentials',module,create=True),patch(
                'axr_applications.wechat_service.NativeDatabase',fixtures.Database):
            recovered=WindowsWeChatService(self.kernel,SimpleNamespace(user='fixture-user'),self.config,'fixture-endpoint')
        self.addCleanup(recovered.close)
        self.assertIsNone(recovered.scope);self.assertEqual(recovered.jobs[pending['job_id']]['state'],'Unknown')
        self.assertNotIn('page',recovered.jobs[pending['job_id']]);self.assertNotIn('approval',recovered.jobs[pending['job_id']])
    def test_new_service_dispatch_keeps_existing_application_route(self):
        application=Mock(return_value={'legacy':'still approved separately'});self.kernel.application=application
        result=self.kernel.dispatch(self.client,{'operation':'Application','payload':{}})
        self.assertEqual(result,{'legacy':'still approved separately'});application.assert_called_once()
        self.assertFalse(self.call('wechat_status')['owner_authorized'])
    def test_approved_windows_service_uses_full_reply_executor_and_cannot_resend(self):
        from test import test_authority_reply as transactions
        transaction=transactions.ReplyTransaction();transaction.setUp();self.addCleanup(transaction.doCleanups)
        transaction.plan=type(transaction.plan)('fixture-owner','fixture-peer','fixture-owner',
            'Fixture peer','Fixture owner','Synthetic reply','fixture-task')
        transaction.cache={'fixture-peer':'','fixture-owner':''};transaction.active='fixture-owner'
        self.service.database=transaction.database;self.service.executor=transaction.executor
        self.config['reply_navigation']={'profiles':{cid:{'label':label,'visual_binding':{'expected_identity':cid}}
            for cid,label in [('fixture-peer','Fixture peer'),('fixture-owner','Fixture owner')]}}
        self.service.config['reply_navigation']=self.config['reply_navigation']
        self.activate();pending=self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic reply',request_id='full-chain')
        self.approve(pending['job_id']);self.service.context.executing_job=pending['job_id']
        self.service.save_job(pending['job_id'],{**self.service.jobs[pending['job_id']],'state':'Executing'})
        def invoke(action,check):
            proof=self.service.prepare(action);self.kernel.claim_commit(self.f.peer,proof)
            if action.payload['mode']=='binding':
                result={'receipt':{'state':'Completed'},'native':{'main_window_verified':True,'binding':{'pid':12,'window_id':1}}}
            else:result=transaction.native(action,check)
            self.kernel.observe(self.f.peer,proof,verified=result['receipt']['state']=='Completed',evidence_digest=digest(result))
            return result
        with patch.object(self.service.navigation,'invoke',side_effect=invoke):
            result=self.service.send('fixture-peer','Synthetic reply')
            self.assertTrue(result['database_record_observed']);self.assertEqual(result['native_state'],'Unknown')
            with self.assertRaisesRegex(AXRError,'previous_attempt'):self.service.send('fixture-peer','Synthetic reply')
        self.assertEqual(transaction.sent,1);self.assertTrue(self.kernel.integrity.verify())
    def channel(self):
        fixture=self
        class Channel:
            session=SimpleNamespace(authority={'root_id':fixture.kernel.root_id},authority_epoch=fixture.kernel.epoch)
            closed=False
            def request(self,operation,**payload):return fixture.kernel.dispatch(fixture.owner,{'operation':operation,'payload':payload})
            def close(self):self.closed=True
        return Channel()
    def test_fixed_owner_control_reviews_scope_locally_and_cancellation_never_signs(self):
        request={'operation':'control','method':'start','arguments':{'targets':'all','automatic':False}}
        channel=self.channel();outputs=[];confirm=Mock(return_value=False);key=Mock()
        with self.assertRaisesRegex(AXRError,'cancelled'):
            windows_owner.service_control({'endpoint':'fixture','server':{}},request,outputs.append,connect=lambda *args:channel,
                owner_key=key,clock=time.time,confirm=confirm)
        key.assert_not_called();self.assertTrue(channel.closed);self.assertIsNone(self.service.scope)
        self.assertIn('wechat-standing-scope',confirm.call_args.args[0])
        self.assertEqual(outputs,[])
    def test_fixed_owner_control_signs_only_reviewed_pending_job(self):
        self.activate();pending=self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic reviewed reply',request_id='owner-review')
        channel=self.channel();outputs=[]
        result=windows_owner.service_control({'endpoint':'fixture','server':{}},{'operation':'control','method':'approve_pending',
            'arguments':{'job_id':pending['job_id']}},outputs.append,connect=lambda *args:channel,
            owner_key=lambda:self.signer,clock=time.time,confirm=lambda text,expires:True)
        self.assertEqual(result['state'],'Queued');self.assertEqual(outputs,[result]);self.assertTrue(channel.closed)
    def test_desktop_approval_setting_uses_existing_signed_eight_tool_policy(self):
        from axr_applications.wechat_mcp import WeChatMCPApplication
        def save(required,generation):self.config.update(manual_approval_required=required,approval_setting_generation=generation)
        app=WeChatMCPApplication(self.kernel,SimpleNamespace(account='fixture-owner'),'fixture-owner',list(self.service.resources),
            self.f.peer,destination='model:codex-mcp',save_approval_setting=save)
        self.kernel.application=app.dispatch;self.kernel.application_owner=app.owner_dispatch
        channel=self.channel();confirm=Mock(return_value=True);outputs=[]
        result=windows_owner.service_control({'endpoint':'fixture','server':{}},{'operation':'control','method':'set_manual_approval',
            'arguments':{'required':False}},outputs.append,connect=lambda *args:channel,owner_key=lambda:self.signer,clock=time.time,confirm=confirm)
        self.assertFalse(result['manual_approval_required']);self.assertFalse(self.service.approval_required())
        self.assertEqual(result['generation'],1);self.assertTrue(channel.closed)
        self.assertIn('旧待办',confirm.call_args.args[0])
    def test_normal_python_cannot_display_owner_review_or_open_hello(self):
        with self.assertRaisesRegex(RuntimeError,'protected_owner_host_required'):
            native.review_windows_owner('Synthetic owner review',time.time()+60)
    def test_provider_readiness_requires_real_windows_isolation_and_caches_failure(self):
        import hashlib
        from axr_applications import wechat_windows_service as implementation
        root=self.kernel.store.directory
        for name in ('synthetic-cli','synthetic-auth','synthetic-ca'):(root/name).write_bytes(b'synthetic bytes; never executed')
        self.service.config['codex_provider']={'binary':str(root/'synthetic-cli'),'auth_file':str(root/'synthetic-auth'),
            'tls_bundle':str(root/'synthetic-ca'),'workspace':str(root),'sha256':hashlib.sha256((root/'synthetic-cli').read_bytes()).hexdigest(),
            'tls_sha256':hashlib.sha256((root/'synthetic-ca').read_bytes()).hexdigest()}
        with patch.object(self.kernel,'development_fixture',False):
            self.assertEqual(self.service.provider_readiness(),{'ready':False,'code':'codex_provider_os_sandbox_unavailable'})
            with patch.object(implementation,'CodexSourceProvider') as provider:
                self.assertFalse(self.service.provider_readiness()['ready']);provider.assert_not_called()


class WindowsServiceFactory(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','Windows service factory')
    def test_factory_attaches_both_apis_and_closes_service_before_server(self):
        kernel=SimpleNamespace(application_close=None,close=Mock());registry=object();events=[]
        store=SimpleNamespace(config=lambda:{'application':{'conversations':[]}},close=Mock())
        service=SimpleNamespace(start=lambda:events.append('start'),close=lambda:events.append('service.close'))
        server=SimpleNamespace(serve=lambda:events.append('serve'),close=lambda:events.append('server.close'))
        with patch.object(wechat,'release_gate',return_value=SimpleNamespace(require=lambda:None)),patch.object(wechat,'OwnerStore',return_value=store),patch.object(
                wechat.native,'HardwareSigningKey'),patch.object(wechat,'_kernel',return_value=(kernel,registry)),patch.object(
                wechat,'AuthorityServer',return_value=server),patch('axr_applications.wechat_mcp.attach_windows_mcp') as attach,patch(
                'axr_applications.wechat_windows_service.WindowsWeChatService',return_value=service):
            result=wechat.create_authority({'state':'unused-fixture','owner_public_key':'fixture','endpoint':'fixture'})
        attach.assert_called_once();self.assertIs(kernel.wechat_service,service)
        result.serve();result.close()
        self.assertEqual(events,['start','serve','service.close','server.close'])
