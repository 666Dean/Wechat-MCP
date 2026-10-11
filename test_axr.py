# SPDX-License-Identifier: MIT
"""Security and transaction fault tests. Fixtures contain no live chat/account data."""
import ctypes as C
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid
from dataclasses import replace,asdict
from pathlib import Path
try:
    import axr
except ModuleNotFoundError as exc:
    if exc.name=="axr":raise unittest.SkipTest("AXR optional: install requirements.axr.txt and native SDK to run these gates") from exc
    raise
from axr import _axr_native as native
from axr.aet import Action,Resource,Provenance,AXRError,canonical
from axr.guard import Guard
from axr.storage import Vault
from axr.journal import Journal
from axr.runtime import Runtime
from axr.host import Lease,FrameCodec,Supervisor,Sandbox
from axr.workspace import Workspace
from axr.admission import Budget,Admission
from axr.owner import approve
from axr_integration.service import Service
from adapters.wcdb import DatabaseAdapter,CipherConnection,decode_text

class Foundation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.now=[1000.]
        self.guard=Guard(self.root/'guard.db',b'g'*32,clock=lambda:self.now[0])
        self.journal=Journal(self.root/'journal.db',Vault(b'j'*32),clock=lambda:self.now[0])
        self.resource=Resource('test','account','chat');self.action=Action('agent',self.resource,'messages.read','purpose',{})
    def tearDown(self):self.guard.close();self.journal.close();self.tmp.cleanup()
    def grant(self,action=None,**kwargs):
        a=action or self.action
        return self.guard._issue_owner(principal=a.principal,resource=a.resource,operations=[a.operation],
            purpose=a.purpose,expires_at=self.now[0]+120,max_uses=kwargs.pop('max_uses',100),
            workflow=a.workflow,**kwargs)
    def runtime(self,handler):return Runtime(self.guard,self.journal,self.root/'leases',{self.action.operation:handler})
    def test_exact_principal_account_conversation_purpose_and_workflow(self):
        self.grant()
        for changes in [dict(principal='other'),dict(resource=Resource('test','other','chat')),
                        dict(resource=Resource('test','account','other')),dict(purpose='other'),dict(workflow='other')]:
            with self.assertRaises(AXRError):self.guard.check(replace(self.action,**changes))
    def test_expiry_and_max_use(self):
        self.grant(max_uses=1);gid,version=self.guard.consume(self.action)
        self.guard.revalidate(self.action,gid,version)
        with self.assertRaises(AXRError):self.guard.consume(self.action)
        self.now[0]+=121
        with self.assertRaises(AXRError):self.guard.revalidate(self.action,gid,version)
    def test_revocation_before_commit(self):
        gid=self.grant();used,v=self.guard.consume(self.action);self.guard.revoke_owner(gid)
        with self.assertRaises(AXRError):self.guard.revalidate(self.action,used,v)
    def test_native_helper_commit_proof_revoke_and_body_tamper(self):
        self.now[0]=time.time();self.grant(max_uses=1)
        gid,version=self.guard.consume(self.action)
        control=self.guard.execution_proof(self.action,gid,version)
        self.assertTrue(native.check_commit(control['store'],control['proof']))
        changed=json.loads(control['proof']);changed['grants'][0]['require_quota']=True
        self.assertFalse(native.check_commit(control['store'],json.dumps(changed)))
        changed=json.loads(control['proof']);changed['grants'][0]['body_sha256']='0'*64
        self.assertFalse(native.check_commit(control['store'],json.dumps(changed)))
        self.guard.revoke_owner(gid)
        self.assertFalse(native.check_commit(control['store'],control['proof']))
        self.grant();gid,version=self.guard.consume(self.action)
        control=self.guard.execution_proof(self.action,gid,version)
        db=sqlite3.connect(self.root/'guard.db')
        db.execute("UPDATE grants SET body=replace(body,'purpose','other') WHERE id=?",(gid,));db.commit();db.close()
        self.assertFalse(native.check_commit(control['store'],control['proof']))
    def test_native_helper_commit_proof_wall_expiry_and_missing_store(self):
        self.grant();gid,version=self.guard.consume(self.action)
        control=self.guard.execution_proof(self.action,gid,version)
        # Broker's injected test clock cannot extend the real helper's wall expiry.
        self.assertFalse(native.check_commit(control['store'],control['proof']))
        missing=str(self.root/'absent.db')
        self.assertFalse(native.check_commit(missing,control['proof']));self.assertFalse(Path(missing).exists())
        self.assertFalse(native.check_commit(control['store'],'{}'))
    def test_native_commit_scope_cannot_exchange_read_for_send_or_another_target(self):
        self.now[0]=time.time();self.grant(max_uses=1)
        gid,version=self.guard.consume(self.action);control=self.guard.execution_proof(self.action,gid,version)
        scope={'resource':asdict(self.resource),'operations':['messages.read','messages.search']}
        check=lambda s:native.check_scoped_commit(control['store'],control['proof'],json.dumps(s))
        self.assertTrue(check(scope))
        self.assertFalse(check({**scope,'operations':['messages.send']}))
        self.assertFalse(check({**scope,'resource':asdict(Resource('test','account','other'))}))
        forged=json.loads(control['proof']);forged['action']['operation']='messages.send';forged['action']['payload']={'text':'test'}
        forged['intent_seal']=native.intent_seal(json.dumps(forged['action']))
        self.assertFalse(native.check_commit(control['store'],json.dumps(forged)))
    def test_native_source_budget_precedes_proof_expansion(self):
        action=asdict(self.action)
        action['sources']=[asdict(Provenance(self.resource,str(i),'personal')) for i in range(201)]
        with self.assertRaisesRegex(RuntimeError,'provenance_budget'):native.intent_seal(json.dumps(action))
    def test_native_commit_send_text_and_visual_regions_are_sealed(self):
        self.now[0]=time.time()
        action=replace(self.action,operation='messages.send',payload={'text':'fixture reply'})
        self.grant(action,intent=action.seal,max_uses=1)
        gid,version=self.guard.consume(action);control=self.guard.execution_proof(action,gid,version)
        scope={'resource':asdict(self.resource),'operations':['messages.send'],'text':'fixture reply'}
        self.assertTrue(native.check_scoped_commit(control['store'],control['proof'],json.dumps(scope)))
        self.assertFalse(native.check_scoped_commit(control['store'],control['proof'],json.dumps({**scope,'text':'different'})))
        changed=json.loads(control['proof']);changed['action']['payload']['text']='different'
        changed['intent_seal']=native.intent_seal(json.dumps(changed['action']))
        self.assertFalse(native.check_commit(control['store'],json.dumps(changed)))
        action=replace(self.action,payload={'visual_binding':{'window_id':1,'regions':{'messages':[0,0,1,1]}}})
        self.grant(action);gid,version=self.guard.consume(action);control=self.guard.execution_proof(action,gid,version)
        scope={'resource':asdict(self.resource),'operations':['messages.read'],'visual_binding':action.payload['visual_binding']}
        self.assertTrue(native.check_scoped_commit(control['store'],control['proof'],json.dumps(scope)))
        self.assertFalse(native.check_scoped_commit(control['store'],control['proof'],json.dumps({**scope,'visual_binding':{'window_id':2}})))
    def test_native_helper_commit_proof_rechecks_source_quota(self):
        self.now[0]=time.time();source_id=self.grant(max_uses=1,classes=['personal'])
        action=replace(self.action,operation='reply.prepare',sources=(Provenance(self.resource,'ref','personal'),))
        self.grant(action,classes=['personal'],max_uses=1)
        gid,version=self.guard.consume(action);control=self.guard.execution_proof(action,gid,version)
        self.assertTrue(native.check_commit(control['store'],control['proof']))
        omitted=json.loads(control['proof']);omitted['grants'].pop()
        self.assertFalse(native.check_commit(control['store'],json.dumps(omitted)))
        swapped=json.loads(control['proof']);swapped['grants'].reverse()
        self.assertFalse(native.check_commit(control['store'],json.dumps(swapped)))
        self.guard.consume(self.action)
        self.assertFalse(native.check_commit(control['store'],control['proof']))
    def test_tampered_grant(self):
        self.grant();db=sqlite3.connect(self.root/'guard.db');db.execute("UPDATE grants SET body=replace(body,'purpose','forged')");db.commit();db.close()
        with self.assertRaises(AXRError):self.guard.check(self.action)
    def test_blanket_external_and_long_exact_grants_rejected(self):
        send=replace(self.action,operation='messages.send',destination='chat')
        with self.assertRaises(AXRError):self.grant(send,destinations=['chat'])
        with self.assertRaises(AXRError):self.grant(send,destinations=['chat'],intent=send.seal)
        self.grant(send,destinations=['chat'],intent=send.seal,max_uses=1)
        with self.assertRaises(AXRError):self.guard.check(replace(send,payload={'text':'different'}))
    def test_cross_conversation_access_and_disclosure_separate(self):
        source=Provenance(self.resource,'ref','personal')
        target=Resource('test','account','target')
        send=replace(self.action,resource=target,operation='messages.send',payload={'text':'summary'},sources=(source,),destination='external')
        self.grant(send,destinations=['external'],classes=['personal'],intent=send.seal,max_uses=1)
        with self.assertRaises(AXRError):self.guard.check(send)
        self.grant(classes=['personal'])
        with self.assertRaises(AXRError):self.guard.check(send)
        disclosure=replace(send,resource=self.resource,operation='disclosure.send',payload={'output_seal':send.seal})
        self.grant(disclosure,destinations=['external'],classes=['personal'],intent=disclosure.seal,max_uses=1)
        self.guard.check(send)
    def test_classified_read_final_use_and_exact_sensitive_approval(self):
        self.now[0]=time.time()
        for data_class in ('personal','sensitive'):
            action=replace(self.action,payload={'limit':1},sources=(Provenance(self.resource,'query:fixture',data_class),))
            self.grant(action,classes=[data_class],max_uses=1,**({'intent':action.seal} if data_class=='sensitive' else {}))
            gid,version=self.guard.consume(action)
            self.guard.revalidate(action,gid,version)
            control=self.guard.execution_proof(action,gid,version)
            self.assertTrue(native.check_commit(control['store'],control['proof']))
            self.assertEqual(len(json.loads(control['proof'])['grants']),1)
            with self.assertRaises(AXRError):self.guard.consume(action)
    def test_source_access_class_cannot_be_replaced_by_workspace_grant(self):
        self.grant(classes=['workspace-normal'])
        prepare=replace(self.action,operation='reply.prepare',sources=(Provenance(self.resource,'ref','personal'),))
        self.grant(prepare,classes=['personal'])
        with self.assertRaises(AXRError):self.guard.check(prepare)
        self.grant(classes=['personal'])
        self.guard.check(prepare)
    def test_sensitive_source_requires_exact_reauthorization(self):
        sensitive=replace(self.action,sources=(Provenance(self.resource,'secret','sensitive'),))
        self.grant(classes=['sensitive'])
        with self.assertRaises(AXRError):self.guard.check(sensitive)
        self.grant(sensitive,classes=['sensitive'],intent=sensitive.seal,max_uses=1)
        self.guard.check(sensitive)
    def test_encryption_binding_and_no_plaintext_in_journal(self):
        action=replace(self.action,payload={'text':'fixture-secret-body'})
        jid=self.journal.propose(action)
        self.assertEqual(self.journal.action(self.journal.get(jid,'agent')),action)
        self.assertNotIn(b'fixture-secret-body',(self.root/'journal.db-wal').read_bytes())
        with self.assertRaises(AXRError):self.journal.vault.open(self.journal.get(jid,'agent')['payload'],'other')
    def test_append_only_audit_and_native_chain(self):
        jid=self.journal.propose(self.action);self.journal.transition(jid,'agent','PolicyChecked')
        self.assertTrue(self.journal.verify_audit())
        with self.assertRaises(sqlite3.IntegrityError):self.journal.db.execute('UPDATE audit_records SET record=?',('{}',))
        with self.assertRaises(sqlite3.IntegrityError):self.journal.db.execute('DELETE FROM audit_records')
    def test_recovery_is_unknown_and_no_retry(self):
        jid=self.journal.propose(self.action)
        for state in ['PolicyChecked','Ready','Prepared','Executing']:self.journal.transition(jid,'agent',state)
        self.assertEqual(self.journal.recover(),1);self.assertEqual(self.journal.receipt(jid,'agent')['state'],'Unknown')
        with self.assertRaises(AXRError):self.journal.transition(jid,'agent','Ready')
    def test_recovery_prepared_fails_safe(self):
        jid=self.journal.propose(self.action)
        for state in ['PolicyChecked','Ready','Prepared']:self.journal.transition(jid,'agent',state)
        self.journal.recover();self.assertEqual(self.journal.receipt(jid,'agent')['state'],'FailedSafe')
    def test_terminal_no_execute_again(self):
        calls=[];self.grant();runtime=self.runtime(lambda a,c,e:(calls.append(1) or {'epoch':e,'verified':True}))
        job=runtime.propose(self.action);self.assertEqual(runtime.execute(job['id'],'agent')['state'],'Completed')
        runtime.execute(job['id'],'agent');self.assertEqual(len(calls),1)
    def test_cancelled_exact_approval_cannot_authorize_identical_new_proposal(self):
        send=replace(self.action,operation='messages.send',payload={'text':'synthetic'},destination='chat')
        self.grant(send,destinations=['chat'],intent=send.seal,max_uses=1)
        runtime=Runtime(self.guard,self.journal,self.root/'leases',{})
        original=runtime.propose(send);self.assertEqual(original['state'],'Ready')
        runtime.cancel(original['id'],'agent')
        fresh=replace(send,execution_id=uuid.uuid4().hex)
        self.assertNotEqual(send.seal,fresh.seal)
        self.assertEqual(runtime.propose(fresh)['state'],'AwaitingApproval')
    def test_same_execution_id_rejected_after_cancel_ttl_and_restart(self):
        runtime=self.runtime(lambda a,c,e:{'epoch':e,'verified':True})
        job=runtime.propose(self.action,ttl=1);runtime.cancel(job['id'],'agent')
        self.now[0]+=2;self.journal.purge();self.journal.close()
        self.journal=Journal(self.root/'journal.db',Vault(b'j'*32),clock=lambda:self.now[0])
        with self.assertRaisesRegex(AXRError,'execution_id_already_proposed'):
            self.journal.propose(self.action)
    def test_stale_epoch_and_unconfirmed_side_effect(self):
        send=replace(self.action,operation='messages.send',payload={'text':'fixture'},destination='chat')
        self.grant(send,destinations=['chat'],intent=send.seal,max_uses=1)
        runtime=Runtime(self.guard,self.journal,self.root/'leases',{'messages.send':lambda a,c,e:{'epoch':'old','verified':True}})
        job=runtime.propose(send);self.assertEqual(runtime.execute(job['id'],'agent')['state'],'Unknown')
    def test_revoke_inside_handler_check(self):
        gid=self.grant()
        def handler(a,check,e):self.guard.revoke_owner(gid);check();self.fail('committed after revocation')
        runtime=self.runtime(handler);job=runtime.propose(self.action)
        self.assertEqual(runtime.execute(job['id'],'agent')['state'],'FailedSafe')
    def test_context_ttl_principal_scope_policy_and_results(self):
        cid=self.journal.remember('agent',self.resource,{'text':'fixture'},self.guard.version,ttl=10)
        for p,r,v in [('other',self.resource,1),('agent',Resource('test','account','other'),1),('agent',self.resource,2)]:
            with self.assertRaises(AXRError):self.journal.context(cid,p,r,v)
        self.now[0]+=11
        with self.assertRaises(AXRError):self.journal.context(cid,'agent',self.resource,1)
    def test_disclosed_scope_taint_outlives_body_ttl_and_broker_restart(self):
        self.journal.taint_disclosure('agent',self.resource,'sensitive')
        self.journal.taint_disclosure('agent',self.resource,'sensitive')
        self.journal.remember('agent',self.resource,{'messages':['synthetic']},1,ttl=2)
        self.now[0]+=3;self.journal.purge();self.journal.close()
        self.journal=Journal(self.root/'journal.db',Vault(b'j'*32),clock=lambda:self.now[0])
        taint=self.journal.disclosure_taint('agent');self.assertEqual(len(taint),1)
        self.assertEqual(taint[0].resource,self.resource);self.assertEqual(taint[0].data_class,'sensitive')
        self.assertEqual(self.journal.disclosure_taint('other'),[])
    def test_pending_approval_expiry_purges_body_without_erasing_active_commit(self):
        pending=self.journal.propose(self.action,ttl=5)
        self.journal.transition(pending,'agent','PolicyChecked');self.journal.transition(pending,'agent','AwaitingApproval')
        active=self.journal.propose(replace(self.action,execution_id=uuid.uuid4().hex),ttl=5)
        for state in ['PolicyChecked','Ready','Prepared','Executing']:self.journal.transition(active,'agent',state)
        self.now[0]+=6;self.journal.purge()
        self.assertEqual(self.journal.get(pending,'agent')['state'],'Expired')
        self.assertIsNone(self.journal.get(pending,'agent')['payload'])
        self.assertEqual(self.journal.get(active,'agent')['state'],'Executing')
        self.assertIsNotNone(self.journal.get(active,'agent')['payload'])
        self.journal.recover();self.journal.purge()
        self.assertEqual(self.journal.get(active,'agent')['state'],'Unknown')
        self.assertIsNone(self.journal.get(active,'agent')['payload']);self.assertTrue(self.journal.verify_audit())
    def test_budget_ceiling_persists_and_window_reset(self):
        budget=Budget(self.journal);budget.reserve('calls',2,amount=2)
        with self.assertRaises(AXRError):Budget(self.journal).reserve('calls',2)
        self.now[0]+=86400;budget.reserve('calls',2)
    def test_budget_invalid_reservation_cannot_refund_or_bypass(self):
        budget=Budget(self.journal)
        for options in [dict(amount=-1),dict(amount=0),dict(amount=True),dict(seconds=0),dict(seconds=86401),dict(amount=1.5)]:
            with self.assertRaises(AXRError):budget.reserve('calls',1,**options)
        budget.reserve('calls',1)
        with self.assertRaises(AXRError):budget.reserve('calls',1)
    def test_account_lease_independent_of_config(self):
        with Lease(self.root/'leases',['test','account']):
            with self.assertRaises(AXRError):
                with Lease(self.root/'leases',['test','account']):pass
    def test_authenticated_frame_replay_tamper_epoch_size(self):
        encoder=FrameCodec(b'k'*32,'epoch');decoder=FrameCodec(b'k'*32,'epoch');encoded=encoder.encode({'a':1})
        self.assertEqual(decoder.decode(encoded),{'a':1})
        for frame in [encoded,encoded.replace(b'"a":1',b'"a":2'),b'x'*(1024*1024+1)]:
            with self.assertRaises(AXRError):decoder.decode(frame)
        with self.assertRaises(AXRError):FrameCodec(b'k'*32,'other').decode(encoded)
    def test_workspace_symlink_escape_and_backup(self):
        workspace=self.root/'workspace';workspace.mkdir();backup=self.root/'versions'
        broker=Workspace(workspace,self.journal.vault,backup)
        for path in ['../private.txt','/tmp/private.txt','script.py']:
            with self.assertRaises(AXRError):broker.path(path)
        if os.name!='nt':
            (workspace/'link').symlink_to(self.root,target_is_directory=True)
            with self.assertRaises(AXRError):broker.path('link/private.txt')
        (workspace/'note.txt').write_text('old')
        action=replace(self.action,operation='workspace.write',payload={'path':'note.txt','text':'new'})
        self.assertTrue(broker.write(action,lambda:None,'epoch')['verified']);self.assertEqual((workspace/'note.txt').read_text(),'new')
        self.assertNotIn(b'old',next(backup.iterdir()).read_bytes())
    def test_admission_defaults_unknown_direction_and_no_model(self):
        admission=Admission(self.guard,self.journal,Budget(self.journal))
        e={'reference':'one','text':'hello Codex','created':1000.,'sender':'friend','outgoing':False}
        policy={'listen':True,'wake_agent':True,'keywords':['Codex'],'auto_execute':False}
        result=admission.evaluate(self.resource,[e],{},lambda:None);self.assertEqual(result['state'],'listener_off')
        result=admission.evaluate(self.resource,[{**e,'created':None}],policy,lambda:None);self.assertFalse(result['decisions'][0]['wake'])
        result=admission.evaluate(self.resource,[{**e,'outgoing':None}],policy,lambda:None);self.assertFalse(result['decisions'][0]['wake'])
        before=self.journal.metrics()
        result=admission.evaluate(self.resource,[e],policy,lambda:None,replay=True);self.assertTrue(result['decisions'][0]['wake']);self.assertEqual(result['model_calls'],0)
        self.assertEqual(self.journal.metrics(),before)
    def test_aggregate_dedup_and_off_clears(self):
        a=Admission(self.guard,self.journal,Budget(self.journal));p={'listen':True,'wake_agent':True,'keywords':['AI'],'aggregate_seconds':3}
        e={'reference':'one','text':'AI','created':1000.,'sender':'friend','outgoing':False}
        a.evaluate(self.resource,[e],p,lambda:None);self.assertEqual(a.drain(self.resource,p),[])
        self.assertEqual(a.evaluate(self.resource,[e],p,lambda:None)['decisions'][0]['reason'],'duplicate')
        self.now[0]+=4;self.assertEqual(len(a.drain(self.resource,p)),1)
    def test_admission_pending_body_and_event_count_bounded(self):
        a=Admission(self.guard,self.journal,Budget(self.journal));p={'listen':True,'wake_agent':True,'keywords':['AI']}
        events=[{'reference':str(i),'text':'AI'+'x'*9000,'created':1000.,'outgoing':False} for i in range(60)]
        a.evaluate(self.resource,events,p,lambda:None);batch=a.drain(self.resource,p,force=True)
        self.assertEqual(len(batch),50);self.assertTrue(all(len(e['text'])==4000 and e['text_truncated'] for e in batch))

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        class Store:
            directory=root;vault=Vault(b'v'*32)
            guard=Guard(root/'guard.db',b'g'*32)
            journal=Journal(root/'journal.db',vault)
            def config(s):return {'principal':'agent','purpose':'purpose','account_id':'account','agent_destination':'model:test',
                'mode':'wcdb','conversations':[{'conversation_id':'friend','display_name':'fixture'}],'listener':{}}
            def close(s):s.guard.close();s.journal.close()
        class Adapter:
            def status(s):return {'mode':'fixture','send_available':False}
            def search(s,cid,**kwargs):return {'messages':[{'reference':'ref','text':'untrusted fixture','created':time.time(),'outgoing':False}],
                'cursor':None,'has_more':False,'coverage':'fixture'}
            def close(s):pass
        self.service=Service(root,store=Store(),adapter=Adapter(),leases=root/'leases')
        self.resource=self.service.resource('friend')
        for op in ['messages.read','messages.search','reply.prepare']:
            self.service.guard._issue_owner(principal='agent',resource=self.resource,operations=[op],purpose='purpose',
                expires_at=time.time()+100,max_uses=100,classes=['personal'])
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def test_read_body_hidden_until_independent_disclosure(self):
        s=self.service;result=s.read('friend');self.assertEqual(result['state'],'Completed');self.assertNotIn('untrusted fixture',json.dumps(result))
        job=s.disclose('friend',result['result']['context_id']);self.assertEqual(job['state'],'AwaitingApproval')
        with self.assertRaises(AXRError):s.execute(job['id'])
        approve(s.store,job['id'],'agent');out=s.execute(job['id']);self.assertEqual(out['result']['messages'][0]['text'],'untrusted fixture')
    def test_ocr_selectors_are_sealed_and_not_forwarded_as_query_filters(self):
        from unittest.mock import patch
        from axr.aet import digest
        s=self.service;s.config['mode']='ui';binding=s.bindings['friend']
        binding['read_method']='ocr';binding['visual_binding']={'pid':12,'window_id':1,'regions':{'messages':[0,0,1,1]}}
        s.initial_policy_digest=digest(s.config)
        original=s.adapter.search
        def search(cid,*,query,sender,since,until,after,limit,guard_context):
            self.assertEqual(json.loads(guard_context['proof'])['action']['payload']['visual_binding'],binding['visual_binding'])
            return original(cid)
        with patch.object(s.store,'config',return_value=s.config),patch.object(s.adapter,'search',side_effect=search):
            action=s._read_action('friend',{'query':'','sender':None,'since':0,'until':2**63-1,'after':None,'limit':2})
            self.assertEqual(action.payload['visual_binding'],binding['visual_binding'])
            self.assertEqual(s.read('friend')['state'],'Completed')
    def test_hybrid_readback_observation_cannot_retry_or_promote_unknown_send(self):
        from unittest.mock import patch
        from axr.aet import digest
        s=self.service;s.config['mode']='hybrid';s.initial_policy_digest=digest(s.config)
        with patch.object(s.store,'config',return_value=s.config),patch.object(s.adapter,'send',create=True,
                side_effect=lambda action,check,epoch:{'epoch':epoch,'verified':False}) as send:
            action=s._action('friend','messages.send',{'text':'synthetic reply'},destination='wechat:'+self.resource.key)
            job=s.runtime.propose(action);approve(s.store,job['id'],'agent')
            self.assertEqual(s.execute(job['id'])['state'],'Unknown')
            message={'reference':'synthetic-record','text':'synthetic reply','created':time.time(),
                     'sender':'account','outgoing':True,'server_id':42}
            cases=[([message],True),([{**message,'sender':'other'}],False),([{**message,'outgoing':False}],False),
                   ([{**message,'server_id':0}],False),([{**message,'server_id':True}],False),
                   ([{**message,'text':'synthetic reply different'}],False),([message,message],False),
                   ([{**message,'text_truncated':True}],False)]
            for messages,expected in cases:
                page={'messages':messages,'coverage':'synthetic','has_more':False,'cursor':None}
                with self.subTest(messages=messages),patch.object(s.adapter,'search',return_value=page):
                    result=s.observe_send_record(job['id'])
                    self.assertEqual(result['database_record_observed'],expected)
                    self.assertFalse(result['delivery_confirmed']);self.assertFalse(result['send_state_changed'])
                    self.assertNotIn('synthetic reply',json.dumps(result))
                    self.assertNotIn('context_id',result['read_job']['result'])
                    self.assertEqual(s.journal.receipt(job['id'],'agent')['state'],'Unknown')
            self.assertEqual(send.call_count,1)
    def test_send_record_observation_requires_independent_read_authority(self):
        from unittest.mock import patch
        from axr.aet import digest
        s=self.service;s.config['mode']='hybrid';s.initial_policy_digest=digest(s.config)
        with patch.object(s.store,'config',return_value=s.config),patch.object(s.adapter,'send',create=True,
                side_effect=lambda action,check,epoch:{'epoch':epoch,'verified':False}):
            action=s._action('friend','messages.send',{'text':'synthetic reply'},destination='wechat:'+self.resource.key)
            job=s.runtime.propose(action);approve(s.store,job['id'],'agent');s.execute(job['id'])
            # Revoke all existing read grants; the exact send grant cannot read.
            db=sqlite3.connect(s.guard.path)
            read_ids=[gid for gid,body in db.execute('SELECT id,body FROM grants')
                      if set(json.loads(body)['operations']) & {'messages.read','messages.search'}]
            db.close()
            for gid in read_ids:s.guard.revoke_owner(gid)
            with patch.object(s.adapter,'search',side_effect=AssertionError('read must remain blocked')):
                result=s.observe_send_record(job['id'])
            self.assertEqual(result['read_job']['state'],'AwaitingApproval')
            self.assertFalse(result['database_record_observed'])
    def test_send_record_observation_retains_sensitive_source_class(self):
        from unittest.mock import patch
        from axr.aet import digest
        s=self.service;s.config['mode']='hybrid';s.initial_policy_digest=digest(s.config)
        s.guard._issue_owner(principal='agent',resource=self.resource,operations=['messages.read'],purpose='purpose',
            expires_at=time.time()+100,max_uses=10,classes=['sensitive'])
        with patch.object(s.store,'config',return_value=s.config),patch.object(s.adapter,'send',create=True,
                side_effect=lambda action,check,epoch:{'epoch':epoch,'verified':False}):
            action=s._action('friend','messages.send',{'text':'synthetic sensitive reply'},
                sources=(Provenance(self.resource,'sensitive-source','sensitive'),),destination='wechat:'+self.resource.key)
            job=s.runtime.propose(action);approve(s.store,job['id'],'agent');self.assertEqual(s.execute(job['id'])['state'],'Unknown')
            with patch.object(s.adapter,'search',side_effect=AssertionError('personal grant cannot read sensitive reply')):
                result=s.observe_send_record(job['id'])
            self.assertEqual(result['read_job']['state'],'AwaitingApproval')
            pending=s.journal.action(s.journal.get(result['read_job']['id'],'agent'))
            self.assertIn('sensitive',{p.data_class for p in pending.sources})
    def test_personal_read_and_listener_require_personal_class_before_adapter(self):
        from unittest.mock import patch
        from axr.aet import digest
        s=self.service;s.guard.revoke_owner('policy-change')
        s.guard._issue_owner(principal='agent',resource=self.resource,operations=['messages.read'],purpose='purpose',
            expires_at=time.time()+100,max_uses=10,classes=['workspace-normal'])
        s.config['listener']={'listen':True,'wake_agent':False,'keywords':['fixture']};s.initial_policy_digest=digest(s.config)
        with patch.object(s.store,'config',return_value=s.config),patch.object(s.adapter,'search',side_effect=AssertionError('unclassified grant cannot reach data')):
            self.assertEqual(s.read('friend')['state'],'AwaitingApproval')
            with self.assertRaises(AXRError):s.tick()
            simulation=s.simulate('friend',[{'reference':'fixture-simulation','text':'fixture','created':time.time(),'outgoing':False}])
            self.assertEqual(simulation['decisions'][0]['reason'],'authority_denied')
        s.guard._issue_owner(principal='agent',resource=self.resource,operations=['messages.read'],purpose='purpose',
            expires_at=time.time()+100,max_uses=1,classes=['personal'])
        with patch.object(s.store,'config',return_value=s.config):
            self.assertEqual(s.read('friend')['state'],'Completed')
    def test_signed_string_false_cannot_enable_listener_or_runner(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from axr_integration.policy import validate_controls
        for section,fields in (('listener',('listen','wake_agent','auto_execute')),('runner',('enabled',))):
            for field in fields:
                for value in ('false','true',0,1,None,[],{}):
                    with self.subTest(section=section,field=field,value=value):
                        config={**self.service.config,section:{field:value}};close=Mock();adapter=Mock()
                        store=SimpleNamespace(guard=None,journal=None,config=lambda:config,close=close)
                        with self.assertRaisesRegex(AXRError,'requires_boolean'):
                            Service(self.tmp.name,store=store,adapter=adapter)
                        close.assert_called_once();self.assertEqual(adapter.mock_calls,[])
            for value in (None,[],True):
                with self.assertRaisesRegex(AXRError,'invalid_wechat_controls'):
                    validate_controls({section:value})
        valid=validate_controls({'listener':{'listen':False,'wake_agent':False,'auto_execute':False},'runner':{'enabled':False}})
        self.assertFalse(valid['listener']['listen']);self.assertFalse(valid['runner']['enabled'])
    def test_listener_off_still_expires_body_without_adapter_access(self):
        from unittest.mock import patch
        s=self.service;s.read('friend')
        action=s._action('friend','messages.send',{'text':'synthetic expired approval'})
        job=s.runtime.propose(action)
        self.assertEqual(job['state'],'AwaitingApproval')
        s.journal.db.execute('UPDATE contexts SET expires=0')
        s.journal.db.execute('UPDATE jobs SET expires=0 WHERE id=?',(job['id'],))
        with patch.object(s.adapter,'search',side_effect=AssertionError('disabled listener cannot access data')):
            self.assertEqual(s.tick()['state'],'listener_off')
        self.assertEqual(s.journal.db.execute('SELECT count(*) FROM contexts').fetchone()[0],0)
        expired=s.journal.get(job['id'],s.principal)
        self.assertEqual(expired['state'],'Expired');self.assertIsNone(expired['payload'])
        self.assertTrue(s.journal.verify_audit());self.assertEqual(s.journal.metrics()['pages_read'],1)
    def test_taint_cannot_be_omitted_in_send_draft(self):
        s=self.service;s.read('friend');draft=s.prepare('friend','generated summary',[])
        self.assertEqual(draft['state'],'Completed');job=s.propose_send('friend',draft['result']['draft_id'])
        action=s.journal.action(s.journal.get(job['id'],'agent'));self.assertEqual(len(action.sources),1)
        self.assertEqual(action.sources[0].data_class,'personal');self.assertTrue(action.payload['text'].startswith('【自动回复 · AI 助理】'))
        self.assertEqual(job['state'],'AwaitingApproval')
    def test_expired_body_context_cannot_clean_disclosed_source_scope(self):
        s=self.service;result=s.read('friend');job=s.disclose('friend',result['result']['context_id'])
        approve(s.store,job['id'],'agent');s.execute(job['id'])
        s.journal.db.execute('UPDATE contexts SET expires=0');s.journal.purge()
        draft=s.prepare('friend','later summary',[]);send=s.propose_send('friend',draft['result']['draft_id'])
        action=s.journal.action(s.journal.get(send['id'],'agent'))
        self.assertTrue(any(p.reference.startswith('disclosed-scope:') and p.data_class=='personal' for p in action.sources))
    def test_unauthorized_scope_and_forged_context(self):
        with self.assertRaises(AXRError):self.service.read('other')
        with self.assertRaises(AXRError):self.service.prepare('friend','text',['forged'])
    def test_runner_batch_context_has_total_cost_bound_before_disclosure(self):
        from axr_integration.runner import run
        self.service.config['runner']={'enabled':True}
        events=[{'reference':str(i),'text':'x'*9000,'created':time.time(),'outgoing':False} for i in range(50)]
        proposal=run(self.service,self.resource,events,{})
        context=self.service.journal.context(proposal['context_id'],'agent',self.resource,self.service.guard.version)
        self.assertEqual(sum(len(e['text']) for e in context['messages']),24000)
        self.assertEqual(len(context['messages']),6);self.assertTrue(all(e['text_truncated'] for e in context['messages']))
        self.assertEqual(proposal['state'],'AwaitingDisclosureApproval');self.assertEqual(self.service.journal.metrics().get('model_calls',0),0)
    def test_listener_reads_use_aet_quota_and_revocation_without_disclosure(self):
        from unittest.mock import patch
        from axr.aet import digest
        s=self.service;s.config['listener']={'listen':True,'wake_agent':False,'keywords':['fixture']}
        s.initial_policy_digest=digest(s.config)
        with patch.object(s.store,'config',return_value=s.config),patch.object(s.adapter,'search',wraps=s.adapter.search) as search:
            s.tick();s.tick()
            self.assertEqual(search.call_count,2)
            self.assertEqual(s.journal.metrics()['jobs_completed'],2)
            self.assertEqual(s.journal.db.execute('SELECT count(*) FROM contexts').fetchone()[0],0)
            s.guard.revoke_owner('policy-change')
            with self.assertRaises(AXRError):s.tick()
            self.assertEqual(search.call_count,2)
    def test_mcp_surface_has_no_grant_or_key_endpoint(self):
        from mcp.server import MCPServer
        from axr_integration.service import register
        import asyncio
        mcp=MCPServer('fixture');register(mcp,self.service)
        async def check():
            tools=await mcp.list_tools();names={t.name for t in tools}
            self.assertIn('axr_execute',names)
            self.assertFalse(any(x in name for name in names for x in ('grant','secret','configure','approve_owner')))
        asyncio.run(check())

class Workers(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','Windows native AppContainer')
    def test_native_windows_sandbox_staged_file_private_denial_and_loopback(self):
        import shutil,socket
        from axr.storage import private_directory
        binary=os.environ.get('AXR_TEST_WORKER');launcher=os.environ.get('AXR_TEST_WINDOWS_LAUNCHER')
        if not binary or not launcher:self.skipTest('native Windows witnesses not provided')
        self.assertTrue(Path(binary).is_file());self.assertTrue(Path(launcher).is_file())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);staged=root/'runtime';staged.mkdir()
            worker=staged/Path(binary).name;shutil.copy2(binary,worker)
            for directory in os.environ.get('AXR_TEST_RUNTIME_ROOTS','').split(os.pathsep):
                if directory:
                    for dll in Path(directory).glob('*.dll'):shutil.copy2(dll,staged/dll.name)
            allowed=staged/'allowed.txt';allowed.write_text('synthetic')
            private=private_directory(root/'private')/'denied.txt';private.write_text('synthetic')
            sandbox=Sandbox(windows_launcher=launcher,windows_root=str(staged))
            supervisor=Supervisor(timeout=20)
            try:
                first=supervisor.invoke([str(worker)],{'op':'read','path':str(allowed)},sandbox=sandbox)
            except AXRError as failure:
                # Retry only the synthetic, read-only bootstrap probe to expose
                # native stage/exit metadata; no live data or external commit.
                import subprocess
                probe=subprocess.run(sandbox.wrap([str(worker)]),input=canonical({'op':'read','path':str(allowed)})+b'\n',
                                     stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20)
                self.fail('supervised sandbox bootstrap '+str(failure)+'; native probe: '+str(probe.returncode)+' '+probe.stdout[:1024].decode('utf8','replace'))
            self.assertTrue(first['result']['allowed'])
            self.assertFalse(supervisor.invoke([str(worker)],{'op':'read','path':str(private)},sandbox=sandbox)['result']['allowed'])
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));listener.listen(2)
                request={'op':'network','port':listener.getsockname()[1]}
                self.assertTrue(supervisor.invoke([str(worker)],request)['result']['allowed'])
                self.assertFalse(supervisor.invoke([str(worker)],request,sandbox=sandbox)['result']['allowed'])

    def test_ui_display_name_alone_cannot_read_content(self):
        from adapters.ui import UIAdapter
        from unittest.mock import patch
        adapter=UIAdapter({'native_helper':'not-launched','account_id':'fixture-self',
            'conversations':[{'conversation_id':'fixture-chat','display_name':'fixture'}]})
        with patch.object(adapter,'_request',side_effect=AssertionError('helper must not be invoked')):
            with self.assertRaisesRegex(AXRError,'stable_account'):adapter.search('fixture-chat')
        adapter.close()

    def test_ui_health_never_qualifies_send_and_does_not_request_labels(self):
        from adapters.ui import UIAdapter
        from unittest.mock import patch
        adapter=UIAdapter({'native_helper':'not-launched','conversations':[]})
        calls=[]
        def request(op,**args):
            calls.append((op,args))
            if op=='status':return {'running':True,'accessibility':True,'pid':12}
            if op=='capabilities':
                return {'pid':12,'editable_nodes':1,'truncated':False,'content_read':False}
            if op=='structure':return {'nodes':[],'pid':12}
            self.fail('content operation during health check')
        with patch('adapters.ui.sys.platform','darwin'),patch.object(adapter,'_request',side_effect=request):
            status=adapter.status();adapter.structure()
        self.assertFalse(status['send_available'])
        self.assertEqual(status['ui_structure_state'],'candidate_controls_unqualified')
        self.assertEqual(calls,[('status',{}),('capabilities',{'expected_pid':12}),('structure',{})])
        adapter.close()

    def test_ui_health_fails_on_process_epoch_change(self):
        from adapters.ui import UIAdapter
        from unittest.mock import patch
        adapter=UIAdapter({'native_helper':'not-launched','conversations':[]})
        with patch('adapters.ui.sys.platform','darwin'),patch.object(adapter,'_request',side_effect=[
                {'running':True,'accessibility':True,'pid':12},AXRError('application_epoch_changed')]):
            with self.assertRaisesRegex(AXRError,'epoch_changed'):adapter.status()
        adapter.close()

    def test_ui_health_permission_missing_does_not_traverse(self):
        from adapters.ui import UIAdapter
        from unittest.mock import patch
        adapter=UIAdapter({'native_helper':'not-launched','conversations':[]})
        with patch('adapters.ui.sys.platform','darwin'),patch.object(adapter,'_request',return_value={
                'running':True,'accessibility':False,'pid':12}) as request:
            self.assertFalse(adapter.status()['send_available'])
            request.assert_called_once_with('status')
        adapter.close()
    def test_ui_visual_health_reports_protection_without_reading_pixels(self):
        from adapters.ui import UIAdapter
        from unittest.mock import patch
        adapter=UIAdapter({'native_helper':'not-launched','conversations':[]})
        with patch('adapters.ui.sys.platform','darwin'),patch.object(adapter,'_request',side_effect=[
            {'running':True,'accessibility':True,'pid':12},
            {'editable_nodes':0,'truncated':False},
            {'capture_candidates':0,'screen_capture_permission':True,'content_read':False}]) as request:
            self.assertEqual(adapter.status()['ocr_state'],'protected_windows')
            self.assertEqual(request.call_args.args,('visual_capabilities',))
            self.assertEqual(request.call_args.kwargs,{'expected_pid':12})
        adapter.close()
    def test_ocr_preview_has_no_sender_or_time_inference_and_needs_read_proof(self):
        from adapters.ui import UIAdapter
        from unittest.mock import patch
        binding={'conversation_id':'fixture-chat','display_name':'fixture','read_method':'ocr',
                 'visual_binding':{'pid':12,'window_id':1,'bounds':[0,0,100,100],'regions':{}}}
        adapter=UIAdapter({'native_helper':'not-launched','account_id':'fixture-self','conversations':[binding]})
        with patch('adapters.ui.sys.platform','darwin'),patch.object(adapter,'_request',return_value={
                'pid':12,'lines':[{'text':'fixture line','confidence':0.99}],
                'identity_assurance':'visible_exact_identifiers_ocr'}) as request:
            with self.assertRaisesRegex(AXRError,'commit_proof'):adapter.search('fixture-chat')
            with self.assertRaisesRegex(AXRError,'sender_time'):adapter.search('fixture-chat',sender='self',guard_context={'proof':'test'})
            request.assert_not_called()
            page=adapter.search('fixture-chat',guard_context={'proof':'test'})
            self.assertTrue(page['preview_only']);self.assertFalse(page['background'])
            self.assertIsNone(page['messages'][0]['sender']);self.assertIsNone(page['messages'][0]['outgoing'])
            self.assertEqual(request.call_args.kwargs['visual_binding'],binding['visual_binding'])
        adapter.close()

    def test_timeout_and_output_limit(self):
        with self.assertRaisesRegex(AXRError,'timed_out'):
            Supervisor(timeout=.1).invoke([sys.executable,'-c','import time;time.sleep(5)'],{})
        with self.assertRaisesRegex(AXRError,'too_large'):
            Supervisor(timeout=5).invoke([sys.executable,'-c','import sys;sys.stdout.write("x"*2000000)'],{})
    @unittest.skipUnless(sys.platform=='darwin','macOS native sandbox')
    def test_native_sandbox_allowed_worker_and_denied_private_file(self):
        result=Supervisor().invoke(['/usr/bin/printf','{"verified":true}'],{},sandbox=Sandbox())
        self.assertTrue(result['result']['verified'])
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'private.json';file.write_text('{"synthetic_secret":"fixture"}')
            with self.assertRaises(AXRError):Supervisor().invoke(['/bin/cat',str(file)],{},sandbox=Sandbox())
            result=Supervisor().invoke(['/bin/cat',str(file)],{},sandbox=Sandbox(read_roots=[tmp]))
            self.assertEqual(result['result']['synthetic_secret'],'fixture')

    @unittest.skipUnless(sys.platform=='darwin','macOS native sandbox')
    def test_native_sandbox_denies_network_to_listening_loopback(self):
        import socket
        binary=os.environ.get('AXR_TEST_WORKER')
        if not binary or not Path(binary).is_file():self.skipTest('native worker probe not provided')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(1)
            request={'op':'network','port':listener.getsockname()[1]}
            self.assertTrue(Supervisor().invoke([binary],request)['result']['allowed'])
            self.assertFalse(Supervisor().invoke([binary],request,sandbox=Sandbox(read_roots=os.environ.get('AXR_TEST_RUNTIME_ROOTS','').split(os.pathsep) if os.environ.get('AXR_TEST_RUNTIME_ROOTS') else []))['result']['allowed'])

    def test_owner_requires_interactive_terminal(self):
        from axr.owner import authenticate
        from unittest.mock import patch
        with patch('sys.stdin.isatty',return_value=False):
            with self.assertRaisesRegex(AXRError,'interactive'):authenticate('does-not-exist')

class DatabasePages(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.chat='fixture-chat'
        table='Msg_'+hashlib.md5(self.chat.encode()).hexdigest();self.table=table;paths=[]
        for i in range(2):
            path=self.root/f'message_{i}.db';paths.append(path);db=sqlite3.connect(path)
            db.execute('CREATE TABLE Name2Id(user_name TEXT PRIMARY KEY)');db.executemany('INSERT INTO Name2Id(rowid,user_name) VALUES(?,?)',[(7,'fixture-self'),(19,self.chat)])
            db.execute(f'CREATE TABLE "{table}"(local_id INTEGER,server_id INTEGER,local_type INTEGER,create_time INTEGER,real_sender_id INTEGER,message_content BLOB)')
            db.execute(f'INSERT INTO "{table}" VALUES(?,?,?,?,?,?)',(i+1,10+i,1,100,19,'matching fixture'))
            db.commit();db.close()
        class Connection:
            def __init__(self,path):self.db=sqlite3.connect(path);self.db.row_factory=sqlite3.Row
            def query(self,sql,parameters=()):return [dict(row) for row in self.db.execute(sql,parameters)]
            def close(self):self.db.close()
        self.paths=paths
        self.adapter=DatabaseAdapter({'account_id':'fixture-self','conversations':[{'conversation_id':self.chat,'schema':'v4'}],
            'shards':[{'path':str(p)} for p in paths]},None,connection_factory=Connection)
    def tearDown(self):self.adapter.close();self.tmp.cleanup()
    def test_same_second_shards_and_bound_keyset_pagination(self):
        first=self.adapter.search(self.chat,limit=1);self.assertTrue(first['has_more']);self.assertEqual(len(first['messages']),1)
        second=self.adapter.search(self.chat,after=first['cursor'],limit=1);self.assertEqual(len(second['messages']),1)
        self.assertNotEqual(first['messages'][0]['reference'],second['messages'][0]['reference'])
        self.assertFalse(second['messages'][0]['outgoing']);self.assertEqual(second['messages'][0]['sender'],self.chat)
        self.assertEqual(self.adapter.search(self.chat,after=second['cursor'],limit=1)['messages'],[])
    def test_filters_compression_and_nontext_not_exposed(self):
        import zstandard
        db=sqlite3.connect(self.paths[0]);db.execute(f'INSERT INTO "{self.table}" VALUES(3,30,1,101,7,?)',(zstandard.ZstdCompressor().compress(b'compressed fixture'),))
        db.execute(f'INSERT INTO "{self.table}" VALUES(4,40,3,102,19,?)',('<msg>synthetic secret media metadata</msg>',));db.commit();db.close()
        result=self.adapter.search(self.chat,query='compressed',sender='fixture-self',since=101)
        self.assertEqual(len(result['messages']),1);self.assertTrue(result['messages'][0]['outgoing']);self.assertEqual(result['messages'][0]['text'],'compressed fixture')
        self.assertNotIn('secret media',json.dumps(self.adapter.search(self.chat)))
    def test_account_and_sender_unknown_reject(self):
        self.adapter.config['account_id']='not-in-shard'
        with self.assertRaisesRegex(AXRError,'account_identity'):self.adapter.search(self.chat)
        self.adapter.config['account_id']='fixture-self';db=sqlite3.connect(self.paths[0]);db.execute(f'UPDATE "{self.table}" SET real_sender_id=999');db.commit();db.close()
        with self.assertRaisesRegex(AXRError,'sender_identity'):self.adapter.search(self.chat)
    def test_database_replacement_requires_new_baseline(self):
        self.adapter.search(self.chat)
        path=self.paths[0];replacement=self.root/'new.db';replacement.write_bytes(path.read_bytes());os.replace(replacement,path)
        with self.assertRaisesRegex(AXRError,'generation_changed'):self.adapter.search(self.chat)

class CipherTests(unittest.TestCase):
    def test_real_sqlcipher_committed_wal_readonly_and_wrong_key(self):
        library=os.environ.get('AXR_SQLCIPHER_LIBRARY')
        if not library:self.skipTest('SQLCipher integration library not provided')
        self.assertTrue(Path(library).is_file(),'explicit SQLCipher integration library is missing')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'encrypted.db';writer=object.__new__(CipherConnection)
            writer.lib=C.CDLL(library);writer.handle=C.c_void_p();writer._declare()
            self.assertEqual(writer.lib.sqlite3_open_v2(str(path).encode(),C.byref(writer.handle),2|4,None),0)
            key='ab'*32
            try:
                writer.query('PRAGMA key="x\''+key+'\'"');writer.query('PRAGMA journal_mode=WAL')
                writer.query('CREATE TABLE sample(id INTEGER PRIMARY KEY,text TEXT)');writer.query('INSERT INTO sample VALUES(1,?)',('synthetic private fixture',))
                self.assertTrue(Path(str(path)+'-wal').exists())
                self.assertNotIn(b'synthetic private fixture',Path(str(path)+'-wal').read_bytes())
                reader=CipherConnection(path,library,key,'sqlcipher4')
                try:
                    self.assertEqual(reader.query('SELECT text FROM sample')[0]['text'],'synthetic private fixture')
                    with self.assertRaises(AXRError):reader.query('INSERT INTO sample VALUES(2,?)',('write denied',))
                finally:reader.close()
                with self.assertRaises(AXRError):CipherConnection(path,library,'cd'*32,'sqlcipher4')
            finally:writer.close()
    def test_zstd_bounded_text_and_unknown_codec(self):
        import zstandard
        self.assertEqual(decode_text(zstandard.ZstdCompressor().compress('fixture'.encode()),1),'fixture')
        with self.assertRaises(AXRError):decode_text(b'x',99)

    def test_wcdb_modern_compression_flags_and_complete_frame(self):
        import zstandard
        encoded=zstandard.ZstdCompressor().compress('modern fixture'.encode())
        for flag in (4,5):self.assertEqual(decode_text(encoded,flag),'modern fixture')
        for flag in (2,3):
            with self.assertRaisesRegex(AXRError,'dictionary_required'):decode_text(encoded,flag)
        for invalid in (encoded[:-1],encoded+b'garbage',encoded+encoded):
            with self.assertRaises(AXRError):decode_text(invalid,4)
        self.assertEqual(decode_text(b'plain blob',1),'plain blob')

    def test_wcdb_compression_output_and_window_budget(self):
        import zstandard
        payload=b'x'*(1024*1024+1)
        for known in (True,False):
            encoded=zstandard.ZstdCompressor(write_content_size=known).compress(payload)
            with self.assertRaises(AXRError):decode_text(encoded,4)
        with self.assertRaises(AXRError):decode_text('x'*(1024*1024+1),0)

if __name__=='__main__':unittest.main()
