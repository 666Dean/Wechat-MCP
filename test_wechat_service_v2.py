# SPDX-License-Identifier: MIT
"""Native Guard/signatures/checkpoint with synthetic application adapters.

These prove dispatcher boundaries, not a live WeChat send or installed identity.
"""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from axr.aet import AXRError,Resource,canonical,digest
from axr.guard import Guard
from axr.journal import Journal
from axr.storage import Vault
from axr.checkpoint import ProtectedCheckpoint
from axr.security import SecurityService
from axr.ipc import PeerContext
from test.test_security_authority import FixtureSigner,ProtectedStore
from axr_applications.wechat_service import WeChatKernel,WeChatService,PRINCIPAL,BOUNDARY

class Database:
    def __init__(self,*args):self.calls=0
    def search(self,identity,*,check,**kwargs):
        check();self.calls+=1
        return {'messages':[{'reference':'synthetic-message','text':'密码：synthetic-secret','outgoing':False,
            'created':100,'local_id':1,'server_id':7,'sender':identity}],
            'cursor':{'fixture':[100,1]},'has_more':False,'complete_history':False,'delivery_confirmed':False}

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        guard=Guard(root/'guard.db',b'g'*32);self.addCleanup(guard.close)
        vault=Vault(b'v'*32);checkpoint=ProtectedCheckpoint(ProtectedStore(),vault,'fixture-service')
        journal=Journal(root/'journal.db',vault,checkpoint=checkpoint);self.addCleanup(journal.close)
        self.store=SimpleNamespace(directory=root,guard=guard,vault=vault,journal=journal,key=b'g'*32)
        security=SecurityService(self.store,lambda:{},lambda:{},revoke_domain=lambda scope:None)
        journal.db.execute('CREATE TABLE wechat_state(name TEXT PRIMARY KEY,payload BLOB)')
        signer=FixtureSigner();self.owner_key=FixtureSigner()
        self.peer=PeerContext('handler',PRINCIPAL,'synthetic-native-root',1,'root-birth')
        self.owner=PeerContext('owner','wechat:owner','synthetic-owner',2,'owner-birth')
        self.client=PeerContext('client',PRINCIPAL,'synthetic-front',3,'front-birth')
        self.kernel=WeChatKernel(security,signer,self.owner_key.public_key,identity=lambda p:{'agent':p.principal,'application':'wechat','identity_verified':True},
            environment=lambda p:{'sandbox':BOUNDARY,'environment_valid':True},handler_for=lambda o,r:self.peer,
            development_fixture=True,initialize=True,application_tables={'wechat_state':'name'},recovery_verifier=lambda *a:True)
        self.addCleanup(self.kernel.close);self.kernel.controller_peer=self.peer
        helper=root/'fixture-helper';helper.write_bytes(b'never executed')
        self.config={'account_id':'fixture-owner','resources':[asdict(Resource('wechat','fixture-owner',i)) for i in ('fixture-owner','fixture-peer')],
            'conversations':[{'conversation_id':i,'display_name':i,'data_class':'personal'} for i in ('fixture-owner','fixture-peer')],
            'navigation_helper':str(helper),'codex_provider':{},'shards':[]}
        import axr_applications,sys
        module=SimpleNamespace(WeChatConsumer=lambda *a:None)
        with patch.dict(sys.modules,{'axr_applications._wechat_credentials':module}),patch.object(axr_applications,'_wechat_credentials',module,create=True),patch('axr_applications.wechat_service.NativeDatabase',Database):
            self.service=WeChatService(self.kernel,SimpleNamespace(user='fixture-user'),self.config,'fixture-endpoint')
        self.kernel.application=self.service
        binding=patch.object(self.service,'inspect_binding',return_value={'fixture':True})
        binding.start();self.addCleanup(binding.stop)
        self.addCleanup(self.stop)
    def stop(self):
        self.service.stop();self.service.stop_event.set();self.service.worker_event.set()
        if self.service.thread.is_alive():self.service.thread.join(3)
    def activate(self,**arguments):
        reviewed=self.service.review(self.owner,{'targets':'all','seconds':300,'max_replies':4,'automatic':False,**arguments})
        challenge=reviewed['challenge']
        return self.service.activate(self.owner,challenge['nonce'],self.owner_key.sign(canonical(challenge)).hex())
    def call(self,name,**args):return self.kernel.dispatch(self.client,{'operation':'WeChat','payload':{'method':name,'arguments':args}})
    def test_direct_desktop_prompt_waits_for_idle_without_creating_wechat_scope(self):
        thread='00000000-0000-4000-8000-000000000001'
        self.service.state.set('assistant',{'thread_id':thread})
        args={'text':'Synthetic direct owner task','request_id':'a'*32}
        queued=self.service.queue_owner_prompt(args)
        self.assertIsNone(self.service.scope)
        self.assertFalse(self.service.claim_owner_task()['ready'])
        self.service.lifecycle={'thread_id':thread,'state':'idle','ready_at':0}
        task=self.service.claim_owner_task();self.assertTrue(task['ready']);self.assertEqual(task['channel'],'desktop')
        self.assertFalse(self.service.claim_owner_task()['ready'])
        self.service.finish_owner_task({'job_id':queued['job_id'],'text':'Synthetic local answer'})
        self.assertEqual(self.service.jobs[queued['job_id']]['state'],'Completed');self.assertIsNone(self.service.scope)
        self.assertEqual(self.service.queue_owner_prompt(args)['state'],'Completed')
        value=self.service.dispatch(self.owner,{'operation':'WeChatOwner','payload':{'method':'snapshot','arguments':{}}})
        self.assertEqual(value['owner_messages'][0]['answer'],'Synthetic local answer')
        self.assertNotIn('prompt',value['jobs'][0]);self.assertNotIn('text',value['jobs'][0])
        public=self.call('wechat_job_status',job_id=queued['job_id']);self.assertNotIn('prompt',public);self.assertNotIn('text',public)
        with self.assertRaisesRegex(AXRError,'owner_channel'):
            self.kernel.dispatch(self.client,{'operation':'WeChatOwner','payload':{'method':'queue_owner_prompt','arguments':args}})
    def test_burst_overflow_stops_scope_without_model_or_send(self):
        self.activate(automatic=True)
        with patch.object(self.service,'scan_targets',return_value=[]),patch.object(self.service.bursts,'ready',side_effect=AXRError('wechat_burst_capacity')),patch.object(self.service,'infer') as infer,patch.object(self.service,'send') as send,patch.object(self.service.worker_event,'wait',side_effect=lambda *_:self.service.stop_event.set()):
            self.service.loop()
        self.assertIsNone(self.service.scope);self.assertEqual(self.service.bursts.pending,{})
        self.assertEqual(self.service.state.get('worker-error'),{'code':'wechat_burst_capacity'})
        infer.assert_not_called();send.assert_not_called()
    def test_owner_model_choice_cancel_and_late_child_hooks_do_not_expand_scope(self):
        thread='00000000-0000-4000-8000-000000000001';self.service.state.set('assistant',{'thread_id':thread})
        args={'text':'Synthetic task','request_id':'b'*32,'model':'synthetic-model','effort':'high'}
        q=self.service.queue_owner_prompt(args);self.service.lifecycle={'thread_id':thread,'state':'idle','ready_at':0}
        task=self.service.claim_owner_task();self.assertEqual(task['model'],'synthetic-model');self.assertEqual(task['effort'],'high')
        self.service.cancel_owner_task({'job_id':q['job_id']});self.assertEqual(self.service.jobs[q['job_id']]['state'],'Unknown')
        self.service.lifecycle={'thread_id':thread,'state':'busy','turn_id':'owner-turn'}
        event=self.service.lifecycle_event({'thread_id':thread,'event':'Stop','worker_token':task['worker_token'],'turn_id':'child-turn'})
        self.assertTrue(event['worker_event']);self.assertEqual(self.service.lifecycle['state'],'busy')
        with self.assertRaisesRegex(AXRError,'uncertain_text_never_retry'):
            self.service.queue_owner_prompt({**args,'request_id':'c'*32})
        with self.assertRaisesRegex(AXRError,'idempotency_content_changed'):
            self.service.queue_owner_prompt({**args,'model':'different-model'})
        self.assertIsNone(self.service.scope)
    def test_draft_only_scope_cannot_send_even_through_mcp(self):
        self.activate(reply_targets=[],automatic=False)
        self.assertFalse(self.service.scope['automatic']);self.assertFalse(self.call('wechat_status')['send_available'])
        with self.assertRaisesRegex(AXRError,'send_target_not_authorized'):
            self.call('wechat_send_message',conversation_id='fixture-peer',text='must not send',request_id='blocked')
        self.assertEqual(self.call('wechat_prepare_reply',conversation_id='fixture-peer',text='manual only')['state'],'Draft')
    def test_activity_wait_never_submits_and_stop_cancels_pending(self):
        self.activate(send_policy='when_idle')
        job=self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic queued reply',request_id='idle-test')
        with patch.object(self.service,'send_wait_reason',return_value='user_active'),patch.object(self.service,'scan_targets',return_value=[]),patch.object(self.service,'send') as send,patch.object(self.service.worker_event,'wait',side_effect=lambda *_:self.service.stop_event.set()):
            self.service.loop()
        self.assertEqual(self.service.jobs[job['job_id']]['state'],'WaitingForIdle');send.assert_not_called()
        self.assertEqual(self.service.reply_count,0)
        self.service.stop();self.assertEqual(self.service.jobs[job['job_id']]['state'],'FailedSafe')
    def test_background_trial_is_bounded_until_actual_observed_witness(self):
        self.assertFalse(self.service.background_qualified())
        with self.assertRaisesRegex(AXRError,'background_trial_requires_bounded_scope'):
            self.activate(send_policy='background_when_idle',seconds=0,max_replies=0)
        self.activate(send_policy='background_when_idle',seconds=600,max_replies=2)
        self.assertEqual(self.service.scope['send_policy'],'background_when_idle')
    def test_idle_release_submits_once_and_unknown_is_never_requeued(self):
        self.activate(send_policy='foreground_only')
        job=self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic once',request_id='foreground-test')
        self.service.jobs[job['job_id']]['state']='WaitingForIdle'
        with patch.object(self.service,'send_wait_reason',return_value=None),patch.object(self.service,'scan_targets',return_value=[]),patch.object(self.service,'send',return_value={'database_record_observed':False}) as send,patch.object(self.service.worker_event,'wait',side_effect=lambda *_:self.service.stop_event.set()):
            self.service.loop()
        self.assertEqual(send.call_count,1);self.assertEqual(self.service.jobs[job['job_id']]['state'],'Unknown')
        self.service.stop_event.clear()
        with self.assertRaisesRegex(AXRError,'uncertain_text_never_retry'):
            self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic once',request_id='new-id')
    def test_discovery_has_no_authority_and_read_requires_owner(self):
        self.assertFalse(self.call('wechat_status')['owner_authorized'])
        with self.assertRaisesRegex(AXRError,'scope_stopped'):self.call('wechat_read_messages',conversation_id='fixture-peer')
        with self.assertRaisesRegex(AXRError,'owner_channel'):self.service.review(self.client,{'targets':'all'})
    def test_status_verifies_the_audit_under_the_writer_lock_and_reports_failure(self):
        def verify():
            self.assertTrue(self.kernel.lock._is_owned())
            return False
        with patch.object(self.store.journal,'verify_audit',side_effect=verify):
            self.assertFalse(self.service.status()['audit_valid'])
    def test_native_database_failure_stops_scope_and_keeps_only_its_fixed_code(self):
        self.activate(automatic=True)
        with patch.object(self.service,'scan_targets',side_effect=AXRError('wcdb_native_sender_identity_mismatch')),patch.object(self.service.worker_event,'wait',side_effect=lambda *_:self.service.stop_event.set()):
            self.service.loop()
        self.assertIsNone(self.service.scope)
        self.assertEqual(self.service.state.get('worker-error'),{'code':'wcdb_native_sender_identity_mismatch'})
    def test_exact_owner_signature_and_replay(self):
        review=self.service.review(self.owner,{'targets':'all'})
        with self.assertRaisesRegex(AXRError,'signature'):self.service.activate(self.owner,review['challenge']['nonce'],'00')
        with self.assertRaisesRegex(AXRError,'expired_or_changed'):self.service.activate(self.owner,review['challenge']['nonce'],'00')
        self.activate(seconds=0,max_replies=0);self.assertTrue(self.service.scope['expires']==0)
        self.assertLessEqual(self.service.capability['body']['contract']['expires']-time.time(),3600)
    def test_window_and_account_preflight_precede_hardware_challenge(self):
        with patch.object(self.service,'inspect_binding',side_effect=AXRError('wechat_main_window_unavailable')):
            with self.assertRaisesRegex(AXRError,'main_window_unavailable'):
                self.service.review(self.owner,{'targets':'all','automatic':True})
        self.assertEqual(self.service.reviews,{})
        self.assertIsNone(self.service.scope)
        with patch.object(self.service,'inspect_binding') as binding:
            self.service.review(self.owner,{'targets':'all','automatic':False})
            binding.assert_not_called()
    def test_provider_failure_is_detected_before_hardware_or_window_request(self):
        with patch.object(self.service,'provider_readiness',return_value={'ready':False,'code':'codex_provider_build_changed'}),patch.object(self.service,'inspect_binding') as window:
            with self.assertRaisesRegex(AXRError,'^codex_provider_build_changed$'):
                self.service.review(self.owner,{'targets':'all','automatic':True})
        self.assertEqual(self.service.reviews,{});window.assert_not_called();self.assertIsNone(self.service.scope)
    def test_provider_hash_cache_invalidates_on_program_update_without_reading_auth(self):
        root=Path(self.temp.name);binary=root/'codex';auth=root/'auth';tls=root/'tls'
        binary.write_bytes(b'synthetic image');auth.write_bytes(b'synthetic login');tls.write_bytes(b'synthetic trust')
        self.service.config['codex_provider']={'binary':str(binary),'sha256':digest('wrong'),'auth_file':str(auth),'tls_bundle':str(tls),'tls_sha256':__import__('hashlib').sha256(tls.read_bytes()).hexdigest()}
        self.kernel.development_fixture=False
        try:
            self.assertEqual(self.service.provider_readiness()['code'],'codex_provider_build_changed')
            self.service.provider_cache=None
            self.service.config['codex_provider']['sha256']=__import__('hashlib').sha256(binary.read_bytes()).hexdigest()
            self.assertTrue(self.service.provider_readiness()['ready'])
            binary.write_bytes(b'changed program')
            self.assertEqual(self.service.provider_readiness()['code'],'codex_provider_build_changed')
        finally:self.kernel.development_fixture=True
    def test_navigation_failure_keeps_only_a_bounded_native_reason(self):
        self.activate()
        for reason,expected in [('authority_or_scope_changed','authority_or_scope_changed'),('private text/path','unconfirmed')]:
            with self.subTest(reason=reason),patch.object(self.service,'binding',return_value={'window_id':1}),patch.object(self.service.navigation,'invoke',return_value={
                'receipt':{'state':'Unknown'},'native':{'error':reason}}):
                with self.assertRaisesRegex(AXRError,'^wechat_navigation_complete_'+expected+'$'):
                    self.service.navigate('fixture-peer')
    def test_owner_target_check_does_not_grant_scope_or_submit(self):
        packet={'operation':'WeChatOwner','payload':{'method':'check_target','arguments':{'conversation_id':'fixture-peer'}}}
        with self.assertRaisesRegex(AXRError,'scope_stopped'):self.service.dispatch(self.owner,packet)
        self.activate()
        with patch.object(self.service,'navigate') as navigate,patch.object(self.service,'nav_state',return_value=[{'draft':'private draft'}]):
            result=self.service.dispatch(self.owner,packet)
        self.assertTrue(result['navigation_verified']);self.assertTrue(result['draft_present'])
        self.assertFalse(result['send_invoked']);self.assertNotIn('private draft',str(result));navigate.assert_called_once()
        with self.assertRaises(AXRError):self.kernel.dispatch(self.client,packet)
    def test_navigation_is_one_exact_transaction_and_stop_blocks_followup_reads(self):
        self.activate();phases=[]
        def invoke(action,check):
            phases.append(action.payload['navigation_binding']['phase'])
            self.service.stop()
            return {'receipt':{'state':'Completed'}}
        with patch.object(self.service,'binding',return_value={'window_id':1}),patch.object(self.service.navigation,'invoke',side_effect=invoke):
            with self.assertRaisesRegex(AXRError,'scope_stopped'):self.service.navigate('fixture-peer')
        self.assertEqual(phases,['complete'])
    def test_live_input_protection_is_not_inferred_from_stale_cached_text(self):
        self.activate()
        with patch.object(self.service,'nav_state',return_value=[{'draft':'existing'}]), \
             patch.object(self.service,'read',return_value={'messages':[],'has_more':False,'cursor':{}}), \
             patch.object(self.service,'navigate',return_value=({'window_id':1},0,[])) as navigate, \
             patch.object(self.service.navigation,'invoke',return_value={'receipt':{'state':'Unknown'},'native':{'error':'existing_input_preserved'}}) as ui:
            with self.assertRaisesRegex(AXRError,'existing_draft_preserved'):self.service.send('fixture-peer','new text')
        navigate.assert_called_once();self.assertEqual(ui.call_args.args[0].payload['visual_binding']['draft_policy'],'preserve')
    def test_idle_admission_survives_own_keys_but_keeps_all_three_recipient_checks(self):
        self.activate(send_policy='when_idle');actions=[];sent=False
        def invoke(action,check):
            nonlocal sent
            check();actions.append(action)
            if action.payload['mode']=='send':sent=True
            return {'receipt':{'state':'Completed'},'native':{'navigation_invoked':True,
                'query_input_submitted':True,'main_window_verified':True,'draft_match':True,
                'send_invoked':action.payload['mode']=='send'}}
        def nav(identity,mode,**kwargs):
            if mode=='recent':return [{'username':identity,'query':kwargs['query'],'last_click_time':time.time()}]
            return [{'draft':''}]
        def read(*args,**kwargs):
            return {'messages':[{'reference':'new-synthetic','outgoing':True,'text':'synthetic reply','server_id':1}] if sent else [],'has_more':False,'cursor':{}}
        with patch.object(self.service,'binding',return_value={'window_id':1}),patch.object(self.service,'nav_state',side_effect=nav), \
             patch.object(self.service,'read',side_effect=read),patch.object(self.service.navigation,'invoke',side_effect=invoke):
            result=self.service.send('fixture-peer','synthetic reply')
        self.assertTrue(result['database_record_observed'])
        navigations=[a for a in actions if a.operation=='application.navigate']
        self.assertEqual([a.resource.conversation_id for a in navigations],['fixture-peer','fixture-owner','fixture-peer'])
        self.assertEqual([a.payload['visual_binding']['idle_gate'] for a in navigations],['initial','continuation','continuation'])
        self.assertEqual(len([a for a in actions if a.operation=='messages.send']),1)
    def test_force_overwrite_is_owner_signed_and_cannot_be_truthy_text(self):
        with self.assertRaisesRegex(AXRError,'scope_invalid'):self.service.review(self.owner,{'targets':'all','overwrite_drafts':'yes'})
        value=self.activate(overwrite_drafts=True)
        self.assertIs(value['scope']['overwrite_drafts'],True)
        with patch.object(self.service,'nav_state',return_value=[{'draft':'existing'}]), \
             patch.object(self.service,'read',return_value={'messages':[],'has_more':False,'cursor':{}}), \
             patch.object(self.service,'navigate',return_value=({'window_id':1},0,[])), \
             patch.object(self.service.navigation,'invoke',return_value={'receipt':{'state':'Unknown'},'native':{'error':'existing_input_preserved'}}) as ui:
            with self.assertRaisesRegex(AXRError,'existing_draft_preserved'):self.service.send('fixture-peer','new text')
        self.assertEqual(ui.call_args.args[0].payload['visual_binding']['draft_policy'],'replace')
    def test_read_only_target_cannot_be_sent_to_through_mcp_or_dispatcher(self):
        self.activate(reply_targets=['fixture-owner'])
        self.call('wechat_read_messages',conversation_id='fixture-peer')
        self.assertEqual(self.call('wechat_prepare_reply',conversation_id='fixture-peer',text='manual draft')['state'],'Draft')
        with self.assertRaisesRegex(AXRError,'send_target_not_authorized'):
            self.call('wechat_send_message',conversation_id='fixture-peer',text='new reply',request_id='fixed-request')
        with patch.object(self.service.navigation,'invoke') as ui:
            with self.assertRaisesRegex(AXRError,'send_target_not_authorized'):self.service.send('fixture-peer','new reply')
            ui.assert_not_called()
    def test_query_submission_without_copy_still_requires_exact_fresh_recipient(self):
        self.activate()
        result={'receipt':{'state':'Completed'},'native':{'navigation_invoked':True,
            'query_input_submitted':True,'main_window_verified':True,'send_invoked':False}}
        label=self.service.catalog['fixture-peer']['display_name']
        with patch.object(self.service,'binding',return_value={'window_id':1}), \
             patch.object(self.service.navigation,'invoke',return_value=result), \
             patch.object(self.service,'nav_state',return_value=[{'username':'fixture-other','query':label,'last_click_time':time.time()}]):
            with self.assertRaisesRegex(AXRError,'unique_fresh_recipient'):
                self.service.navigate('fixture-peer')
        result['native'].pop('query_input_submitted')
        with patch.object(self.service,'binding',return_value={'window_id':1}), \
             patch.object(self.service.navigation,'invoke',return_value=result):
            with self.assertRaisesRegex(AXRError,'navigation_result_unconfirmed'):
                self.service.navigate('fixture-peer')
    def test_large_catalog_uses_small_source_specific_children(self):
        for n in range(3500):
            identity='wxid_fixture_'+str(n)
            self.service.resources[identity]=Resource('wechat','fixture-owner',identity)
            self.service.catalog[identity]={'conversation_id':identity,'display_name':'Fixture contact '+str(n),'data_class':'personal'}
        self.activate()
        self.assertEqual(len(self.service.scope['targets']),3502)
        self.assertEqual(len(self.service.capabilities),1)
        self.assertLess(len(canonical(self.service.capability)),6000)
        self.call('wechat_read_messages',conversation_id='wxid_fixture_3499')
        child=self.service.capabilities['wxid_fixture_3499']['body']['contract']
        self.assertEqual(child['resources'],[self.service.resources['wxid_fixture_3499'].key])
        self.assertEqual(child['sources'],child['resources'])
    def large_catalog(self):
        for n in range(12):
            identity='wxid_activity_'+str(n)
            self.service.resources[identity]=Resource('wechat','fixture-owner',identity)
            self.service.catalog[identity]={'conversation_id':identity,'display_name':'Fixture activity','data_class':'personal'}
    def test_account_activity_skips_unchanged_sources_and_preserves_unfinished_pages(self):
        self.large_catalog();self.activate()
        rows=[{'conversation_id':'fixture-peer','updated':self.service.baseline,'local_id':7}]
        def activity(**args):
            args['check']()
            return {'rows':rows,'after':[rows[-1]['updated'],'fixture-peer'],'has_more':False}
        with patch.object(self.service.database,'activity',side_effect=activity,create=True):
            self.assertEqual(self.service.scan_targets(),['fixture-peer'])
            self.service.finish_scan('fixture-peer',{'has_more':True})
            self.assertEqual(self.service.scan_targets(),['fixture-peer'])
            self.service.finish_scan('fixture-peer',{'has_more':False})
            self.assertEqual(self.service.scan_targets(),[])
            rows[0]['local_id']=8  # Same-second arrival must not be missed.
            self.assertEqual(self.service.scan_targets(),['fixture-peer'])
        self.assertEqual(self.service.database.calls,0)
        self.assertTrue(self.kernel.integrity.verify())
    def test_restricted_scope_never_uses_account_wide_activity(self):
        self.large_catalog();targets=list(self.service.resources)[:-1]
        for arguments in ({'targets':targets},{'reply_targets':targets}):
            self.activate(**arguments)
            with patch.object(self.service.database,'activity',create=True) as activity:
                self.assertEqual(len(self.service.scan_targets()),8);activity.assert_not_called()
            self.service.stop()
    def test_activity_rejects_foreign_sources_and_resets_on_reauthorization(self):
        self.large_catalog();self.activate()
        with patch.object(self.service.database,'activity',return_value={'rows':[{'conversation_id':'foreign','updated':1,'local_id':1}],'has_more':False},create=True):
            with self.assertRaisesRegex(AXRError,'activity_target_not_enrolled'):self.service.scan_targets()
        self.service.activity_seen={'fixture-peer':(1,1)};self.service.activity_pending={'fixture-peer':(2,2)}
        self.service.activity_after=[2,'fixture-peer'];self.service.stop();self.activate()
        self.assertEqual(self.service.activity_seen,{});self.assertEqual(self.service.activity_pending,{})
        self.assertEqual(self.service.activity_after,[0,''])
    def test_idle_generation_gate_avoids_database_work_and_bounds_sleep(self):
        self.large_catalog();self.activate();path=Path(self.temp.name)/'session';path.write_bytes(b'synthetic')
        self.service.config['shards']=[{'role':'session','path':str(path)}]
        def activity(**args):
            args['check']();return {'rows':[],'after':[0,''],'has_more':False}
        with patch.object(self.service.database,'activity',side_effect=activity,create=True) as query:
            self.service.scan_targets()
            for _ in range(3):self.assertEqual(self.service.scan_targets(),[])
            self.assertEqual(query.call_count,1);self.assertEqual(self.service.poll_delay,8)
            Path(str(path)+'-wal').write_bytes(b'new inbound metadata')
            self.service.scan_targets();self.assertEqual(query.call_count,2);self.assertEqual(self.service.poll_delay,2)
    def test_model_status_omits_contact_directory_and_owner_thread(self):
        self.large_catalog();self.activate()
        value=self.call('wechat_status');scope=value['scope']
        self.assertEqual(scope['target_count'],14);self.assertEqual(scope['reply_target_count'],14)
        for field in ('targets','reply_targets','owner_thread','style'):self.assertNotIn(field,scope)
        self.assertIn('targets',self.service.status()['scope'])
    def test_broad_self_send_uses_observed_peer_instead_of_first_directory_entry(self):
        self.large_catalog();self.activate()
        with self.assertRaisesRegex(AXRError,'verified_parking'):self.service.parking_target('fixture-owner')
        self.service.jobs['observed']={'created':100,'conversation_id':'fixture-peer','state':'Observed','result':{'database_record_observed':True}}
        self.assertEqual(self.service.parking_target('fixture-owner'),'fixture-peer')
        self.service.jobs['unknown']={'created':200,'conversation_id':'wxid_activity_0','state':'Unknown','result':{'database_record_observed':False}}
        self.assertEqual(self.service.parking_target('fixture-owner'),'fixture-peer')
        self.service.scope['reply_targets'].remove('fixture-peer')
        with self.assertRaisesRegex(AXRError,'verified_parking'):self.service.parking_target('fixture-owner')
        self.assertEqual(self.service.parking_target('wxid_activity_0'),'fixture-owner')
    def test_system_sessions_and_public_or_group_sources_are_ineligible(self):
        from axr_applications.wechat_targets import private_recipient
        for identity in ('notifymessage','brandsessionholder','mphelper','filehelper','gh_fixture','fixture@chatroom',''):
            self.assertFalse(private_recipient(identity))
        self.assertTrue(private_recipient('fixture-owner'));self.assertTrue(private_recipient('wxid_fixture_peer'))
    def test_self_task_access_is_opt_in_owner_signed_and_requires_a_bound_thread(self):
        with self.assertRaisesRegex(AXRError,'self_agent_binding_required'):self.activate(self_agent=True)
        with self.assertRaisesRegex(AXRError,'scope_invalid'):self.activate(self_agent='yes')
        self.activate()
        row={'text':'/agent summarize my project','reference':'fixture-owner-command'}
        self.assertFalse(self.service.owner_command('fixture-owner',row))
        with self.assertRaisesRegex(AXRError,'self_agent_not_authorized'):self.service.claim_owner_task()
        with self.assertRaisesRegex(AXRError,'self_command_loop_blocked'):self.service.send('fixture-owner','/agent synthetic loop')
    def self_scope(self):
        self.service.state.set('assistant',{'thread_id':'11111111-1111-4111-8111-111111111111','style':'short','attribution':False})
        self.activate(self_agent=True)
    def test_self_command_handoff_waits_for_idle_and_consumes_exactly_once(self):
        self.self_scope();row={'text':'/agent list my tasks','reference':'fixture-self-reference'}
        self.assertFalse(self.service.owner_command('fixture-peer',row))
        self.assertTrue(self.service.owner_command('fixture-owner',row));self.assertTrue(self.service.owner_command('fixture-owner',row))
        self.assertEqual(len(self.service.jobs),1);self.assertFalse(self.service.claim_owner_task()['ready'])
        thread=self.service.scope['owner_thread']
        self.service.lifecycle_event({'thread_id':thread,'event':'UserPromptSubmit','turn_id':'active'})
        self.service.lifecycle_event({'thread_id':thread,'event':'Stop','turn_id':'older'})
        self.assertEqual(self.service.lifecycle['state'],'busy')
        self.service.lifecycle_event({'thread_id':thread,'event':'Stop','turn_id':'active'})
        self.service.lifecycle['ready_at']=0
        task=self.service.claim_owner_task();self.assertTrue(task['ready']);self.assertEqual(task['text'],'list my tasks')
        self.assertFalse(self.service.claim_owner_task()['ready'])
        self.service.lifecycle_event({'thread_id':thread,'event':'UserPromptSubmit','turn_id':'worker','worker_token':task['worker_token']})
        self.assertEqual(self.service.lifecycle['state'],'idle')
        self.service.finish_owner_task({'job_id':task['job_id'],'text':'Synthetic task completed'})
        self.assertEqual(self.service.jobs[task['job_id']]['state'],'Queued')
        with self.assertRaisesRegex(AXRError,'command_not_active'):self.service.finish_owner_task({'job_id':task['job_id'],'text':'do not repeat'})
        self.assertTrue(self.kernel.integrity.verify())
    def test_stop_and_expiry_cannot_resume_a_handed_off_self_task(self):
        self.self_scope();self.service.owner_command('fixture-owner',{'text':'/agent synthetic','reference':'one'})
        self.service.lifecycle={'thread_id':self.service.scope['owner_thread'],'state':'idle','ready_at':0}
        task=self.service.claim_owner_task();self.service.stop()
        self.assertEqual(self.service.jobs[task['job_id']]['state'],'Unknown')
        with self.assertRaisesRegex(AXRError,'scope_stopped'):self.service.finish_owner_task({'job_id':task['job_id'],'text':'too late'})
    def test_real_guard_read_disclosure_masks_and_consumes_once(self):
        self.activate()
        result=self.call('wechat_read_messages',conversation_id='fixture-peer')
        self.assertNotIn('synthetic-secret',str(result));self.assertEqual(self.service.database.calls,1)
        states=self.kernel.db.execute('SELECT state FROM authority_commits').fetchall()
        self.assertEqual([r[0] for r in states],['Completed','Completed'])
        self.assertTrue(self.kernel.integrity.verify())
    def test_no_model_disclosure_without_separate_consent(self):
        self.activate(disclose=False)
        with self.assertRaisesRegex(AXRError,'disclosure_not_authorized'):self.call('wechat_read_messages',conversation_id='fixture-peer')
        self.assertEqual(self.service.database.calls,0)
    def test_unknown_is_not_queued_again_even_after_new_scope(self):
        self.activate()
        first=self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic one-time reply',request_id='stable-owner-request')
        self.service.save_job(first['job_id'],{**self.service.jobs[first['job_id']],'state':'Unknown'})
        self.service.stop();self.activate()
        again=self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic one-time reply',request_id='stable-owner-request')
        self.assertEqual(again['state'],'Unknown');self.assertFalse(again['retry'])
        self.assertEqual(len(self.service.jobs),1)
        with self.assertRaisesRegex(AXRError,'uncertain_text_never_retry'):
            self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic one-time reply',request_id='different-id-does-not-bypass')
    def test_idempotency_key_cannot_change_exact_text(self):
        self.activate();first=self.call('wechat_send_message',conversation_id='fixture-peer',text='first',request_id='same')
        with self.assertRaisesRegex(AXRError,'idempotency'):self.call('wechat_send_message',conversation_id='fixture-peer',text='changed',request_id='same')
        self.assertEqual(self.service.jobs[first['job_id']]['text'],'first')
    def test_stop_cancels_pending_and_invalidates_inflight_generation(self):
        self.activate();generation=self.service.generation
        job=self.call('wechat_send_message',conversation_id='fixture-peer',text='synthetic pending',request_id='pending')
        self.service.stop();self.assertEqual(self.service.jobs[job['job_id']]['state'],'FailedSafe')
        self.activate()
        with self.assertRaisesRegex(AXRError,'scope_stopped'):self.service.check(generation)
        self.service.stop()
        result=self.call('wechat_job_status',job_id=job['job_id'])
        self.assertEqual(result['state'],'FailedSafe');self.assertNotIn('text',result)
    def test_application_table_tampering_seals_kernel(self):
        self.kernel.db.execute("UPDATE wechat_state SET payload=? WHERE name='jobs'",(b'tampered',))
        with self.assertRaisesRegex(AXRError,'integrity_sealed'):self.call('wechat_status')
    def test_foreign_target_and_arbitrary_operations_are_denied(self):
        self.activate()
        for method,args in [('wechat_send_message',{'conversation_id':'foreign','text':'x','request_id':'x'}),('shell.exec',{}),('wechat_status',{'role':'owner'})]:
            with self.subTest(method=method),self.assertRaises(AXRError):self.call(method,**args)
    def test_manual_panel_remains_separate_from_sending(self):
        self.activate();result=self.call('wechat_prepare_reply',conversation_id='fixture-peer',text='Human review only')
        draft=self.service.dispatch(self.owner,{'operation':'WeChatOwner','payload':{'method':'manual_draft','arguments':{'job_id':result['job_id']}}})
        self.assertEqual(draft['submission'],'human');self.assertEqual(draft['text'],'Human review only')
        self.assertEqual(self.service.jobs[result['job_id']]['state'],'Draft')
    def test_scheduler_incoming_inference_single_send_readback_and_stop(self):
        self.activate(automatic=True,max_replies=1)
        # One synthetic new message. Real Guard/ledger remain in the loop;
        # inference/native UI are explicit synthetic boundaries in this test.
        self.service.baseline=0;self.service.bursts.quiet_seconds=0
        def infer(identity,page):
            self.assertEqual(identity,'fixture-owner')
            self.assertEqual(page['messages'][0]['reference'],'synthetic-message')
            return 'Synthetic typed reply'
        def send(identity,text,**kwargs):
            self.assertEqual(text,'Synthetic typed reply');self.assertTrue(kwargs['sources'])
            return {'database_record_observed':True,'exact_database_records':1,'retry':False,'delivery_confirmed':False}
        with patch.object(self.service,'infer',side_effect=infer) as model,patch.object(self.service,'send',side_effect=send) as sender:
            self.service.start()
            deadline=time.monotonic()+3
            while not any(j['state']=='Observed' for j in self.service.jobs.values()) and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(model.call_count,1);self.assertEqual(sender.call_count,1)
            self.assertTrue(any(j['state']=='Observed' for j in self.service.jobs.values()))
            self.service.stop();self.service.worker_event.set();time.sleep(.05)
            self.assertEqual(sender.call_count,1)
    def test_queued_proactive_job_survives_as_unknown_without_second_submission(self):
        self.activate(max_replies=1)
        queued=self.call('wechat_send_message',conversation_id='fixture-peer',text='Synthetic proactive',request_id='one-proactive')
        with patch.object(self.service,'send',return_value={'database_record_observed':False,'exact_database_records':0,'retry':False,'delivery_confirmed':False}) as sender:
            self.service.start();deadline=time.monotonic()+3
            while self.service.jobs[queued['job_id']]['state']!='Unknown' and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(sender.call_count,1);self.assertEqual(self.service.jobs[queued['job_id']]['state'],'Unknown')
            self.assertFalse(self.service.jobs[queued['job_id']]['result']['delivery_confirmed'])
