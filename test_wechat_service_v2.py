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
        self.addCleanup(self.stop)
    def stop(self):
        self.service.stop();self.service.stop_event.set();self.service.worker_event.set()
        if self.service.thread.is_alive():self.service.thread.join(3)
    def activate(self,**arguments):
        reviewed=self.service.review(self.owner,{'targets':'all','seconds':300,'max_replies':4,'automatic':False,**arguments})
        challenge=reviewed['challenge']
        return self.service.activate(self.owner,challenge['nonce'],self.owner_key.sign(canonical(challenge)).hex())
    def call(self,name,**args):return self.kernel.dispatch(self.client,{'operation':'WeChat','payload':{'method':name,'arguments':args}})
    def test_discovery_has_no_authority_and_read_requires_owner(self):
        self.assertFalse(self.call('wechat_status')['owner_authorized'])
        with self.assertRaisesRegex(AXRError,'scope_stopped'):self.call('wechat_read_messages',conversation_id='fixture-peer')
        with self.assertRaisesRegex(AXRError,'owner_channel'):self.service.review(self.client,{'targets':'all'})
    def test_exact_owner_signature_and_replay(self):
        review=self.service.review(self.owner,{'targets':'all'})
        with self.assertRaisesRegex(AXRError,'signature'):self.service.activate(self.owner,review['challenge']['nonce'],'00')
        with self.assertRaisesRegex(AXRError,'expired_or_changed'):self.service.activate(self.owner,review['challenge']['nonce'],'00')
        self.activate(seconds=0,max_replies=0);self.assertTrue(self.service.scope['expires']==0)
        self.assertLessEqual(self.service.capability['body']['contract']['expires']-time.time(),3600)
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
        self.service.baseline=0
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
