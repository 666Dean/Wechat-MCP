# SPDX-License-Identifier: MIT
import json
import time
import unittest
from unittest.mock import patch
import test_axr
from axr.aet import AXRError, digest
from axr.owner import approve
from axr_integration.manual_reply import review_draft, list_drafts


class ManualReplyWorkflow(unittest.TestCase):
    def setUp(self):
        self.fixture=test_axr.ServiceTests();self.fixture.setUp()
        self.s=self.fixture.service
        self.s.manual_replies=True
        self.s.config['listener']={'listen':True,'wake_agent':True,'auto_execute':False,
            'start_from_now':True,'keywords':['fixture'],'aggregate_seconds':0}
        self.s.initial_policy_digest=digest(self.s.config)
        self.config=patch.object(self.s.store,'config',return_value=self.s.config);self.config.start()

    def tearDown(self):
        self.config.stop();self.fixture.tearDown()

    def test_real_service_inbox_encrypted_deduplicated_approval_to_human_draft(self):
        s=self.s;s.tick();tasks=s.poll_tasks()['tasks']
        self.assertEqual(len(tasks),1);task=tasks[0]
        self.assertEqual(task['state'],'AwaitingApproval')
        self.assertNotIn('untrusted fixture',json.dumps(tasks))
        self.assertNotIn(b'untrusted fixture',bytes(s.journal.db.execute('SELECT payload FROM reply_tasks').fetchone()[0]))
        self.assertFalse(s.task_context(task['task_id'])['body_disclosed'])
        approve(s.store,task['disclosure_job'],s.principal)
        self.assertEqual(s.poll_tasks()['tasks'][0]['state'],'Ready')
        result=s.task_context(task['task_id'])
        self.assertTrue(result['body_disclosed'])
        self.assertEqual(result['disclosure']['result']['messages'][0]['text'],'untrusted fixture')
        draft=s.prepare('friend','fixture task completed',[result['context_id']])
        self.assertEqual(s.finish_task(task['task_id'],draft['id'])['state'],'DraftReadyForHuman')
        manual=review_draft(s.store,draft['id'])
        self.assertFalse(manual['sent']);self.assertIn('fixture task completed',manual['text'])
        self.assertEqual(list_drafts(s.store)[0]['job_id'],draft['id'])
        s.tick();self.assertEqual(len(s.poll_tasks()['tasks']),1)
        self.assertTrue(s.journal.verify_audit())

    def test_metadata_wait_changes_only_and_no_model_without_disclosure(self):
        s=self.s;s.tick();task=s.poll_tasks()['tasks'][0]
        self.assertEqual(s.wait_tasks(0,{task['task_id']:task['state']})['tasks'],[])
        approve(s.store,task['disclosure_job'],s.principal)
        self.assertEqual(s.wait_tasks(0,{task['task_id']:task['state']})['tasks'][0]['state'],'Ready')
        self.assertEqual(s.journal.metrics().get('model_calls',0),0)
        for timeout in (True,-1,46):
            with self.assertRaises(AXRError):s.wait_tasks(timeout)

    def test_restart_preserves_tasks_but_expiry_and_revocation_remove_access(self):
        from axr_integration.inbox import Inbox
        s=self.s;s.tick();task=s.poll_tasks()['tasks'][0]
        restored=Inbox(s.journal,s.guard,s.principal)
        self.assertEqual(restored.get(task['task_id'])['disclosure_job'],task['disclosure_job'])
        s.guard.revoke_owner('policy-change')
        self.assertEqual(s.poll_tasks()['tasks'],[])
        with self.assertRaises(AXRError):s.task_context(task['task_id'])

    def test_ciphertext_binding_tamper_and_unapproved_finish_are_denied(self):
        s=self.s;s.tick();task=s.poll_tasks()['tasks'][0]
        draft=s.prepare('friend','fixture draft',[])
        with self.assertRaisesRegex(AXRError,'not_disclosed'):s.finish_task(task['task_id'],draft['id'])
        s.journal.db.execute('UPDATE reply_tasks SET resource=? WHERE id=?',('forged',task['task_id']))
        with self.assertRaisesRegex(AXRError,'binding_mismatch'):s.poll_tasks()

    def test_manual_mode_blocks_even_exact_approved_adapter_send(self):
        s=self.s;s.config['mode']='hybrid';s.initial_policy_digest=digest(s.config)
        draft=s.prepare('friend','fixture draft',[])
        with self.assertRaisesRegex(AXRError,'human_submission'):s.propose_send('friend',draft['result']['draft_id'])
        action=s._action('friend','messages.send',{'text':'fixture'},destination='wechat:'+self.fixture.resource.key)
        job=s.runtime.propose(action);approve(s.store,job['id'],s.principal)
        with patch.object(s.adapter,'send',create=True,side_effect=AssertionError('no send')) as send:
            with self.assertRaisesRegex(AXRError,'human_submission'):s.execute(job['id'])
            self.assertEqual(s.journal.get(job['id'],s.principal)['state'],'AwaitingApproval')
            send.assert_not_called()

    def test_outgoing_and_old_history_do_not_trigger_reply_tasks(self):
        s=self.s
        for changed in ({'outgoing':True},{'created':time.time()-1800},{'text':'not a task keyword'}):
            message={'reference':str(changed),'text':'fixture','created':time.time(),'outgoing':False,**changed}
            with patch.object(s.adapter,'search',return_value={'messages':[message],'has_more':False,'cursor':None,'coverage':'fixture'}):s.tick()
        self.assertEqual(s.poll_tasks()['tasks'],[])

    def test_task_and_manual_draft_expiry_fail_closed(self):
        s=self.s;s.tick();task=s.poll_tasks()['tasks'][0]
        approve(s.store,task['disclosure_job'],s.principal)
        context=s.task_context(task['task_id']);draft=s.prepare('friend','fixture draft',[context['context_id']])
        s.journal.db.execute('UPDATE results SET expires=0 WHERE id=?',(draft['id'],))
        with self.assertRaises(AXRError):review_draft(s.store,draft['id'])
        self.assertEqual(list_drafts(s.store),[])
        s.journal.db.execute('UPDATE reply_tasks SET expires=0')
        self.assertEqual(s.poll_tasks()['tasks'],[])

    def test_explicit_context_tasks_are_not_new_reply_events(self):
        value=self.s.request_task('friend')
        self.assertFalse(value['body_disclosed']);self.assertEqual(value['origin'],'explicit_read')
        self.assertEqual(self.s.poll_tasks()['tasks'][0]['origin'],'explicit_read')
        with self.assertRaises(AXRError):self.s.request_task('friend',limit=7)

    def test_owner_setup_authentication_failure_cannot_change_policy(self):
        import sys
        from axr_integration import owner_codex
        with patch.object(sys,'argv',['owner','--state','fixture','--helper','fixture','setup']), \
                patch.object(owner_codex,'authenticate',side_effect=AXRError('fixture_auth_denied')), \
                patch.object(owner_codex,'OwnerStore') as store:
            with self.assertRaises(SystemExit):owner_codex.main()
            store.assert_not_called()

    def test_manual_readback_counts_only_exact_outgoing_record(self):
        s=self.s;draft=s.prepare('friend','fixture reply',[])
        text=s.journal.action(s.journal.get(draft['id'],s.principal)).payload['text']
        message={'reference':'sent','text':text,'sender':s.account,'outgoing':True,'server_id':123}
        for changes,observed in (({},True),({'sender':'other'},False),({'outgoing':False},False),
                                  ({'server_id':0},False),({'text':text+'x'},False),({'truncated':True},False)):
            with patch.object(s.adapter,'search',return_value={'messages':[{**message,**changes}],'has_more':False,'cursor':None,'coverage':'fixture'}):
                result=s.observe_manual_reply(draft['id'])
            self.assertEqual(result['database_record_observed'],observed)
            self.assertFalse(result['agent_sent']);self.assertFalse(result['delivery_confirmed'])
            self.assertNotIn(text,json.dumps(result))

    def test_manual_readback_needs_read_authority_and_keeps_draft_state(self):
        s=self.s;draft=s.prepare('friend','fixture reply',[])
        s.guard.revoke_owner('policy-change')
        with patch.object(s.adapter,'search',side_effect=AssertionError('revoked read')):
            with self.assertRaises(AXRError):s.observe_manual_reply(draft['id'])
        self.assertEqual(s.journal.get(draft['id'],s.principal)['state'],'Completed')

    def test_owner_session_only_delegates_exact_scoped_codex_context(self):
        from axr_integration.owner_codex import approve_session_task
        s=self.s;s.config['agent_destination']='model:codex';s.destination='model:codex';s.initial_policy_digest=digest(s.config)
        s.tick();task=s.inbox.list()[0]
        self.assertTrue(approve_session_task(s.store,task,s.config))
        self.assertTrue(s.task_context(task['id'])['body_disclosed'])
        self.assertFalse(s.task_context(task['id'])['automatic_send'])

    def test_owner_session_cannot_approve_other_destination_or_large_batch(self):
        from axr_integration.owner_codex import approve_session_task
        s=self.s;s.tick();task=s.inbox.list()[0]
        with self.assertRaisesRegex(AXRError,'outside_scope'):approve_session_task(s.store,task,s.config)
        s.destination='model:codex';s.config['agent_destination']='model:codex';s.initial_policy_digest=digest(s.config)
        resource=self.fixture.resource
        data={'messages':[{'reference':str(i),'text':'fixture','data_class':'personal'} for i in range(7)]}
        handle=s.journal.remember(s.principal,resource,data,s.guard.version,ttl=300)
        proposal=s.disclose('friend',handle)
        task_id=s.inbox.create(resource,handle,proposal['id'])
        with self.assertRaisesRegex(AXRError,'outside_budget'):approve_session_task(s.store,s.inbox.get(task_id),s.config)

    def test_owner_session_stop_revokes_and_disables_its_controls(self):
        from axr_integration import owner_codex
        s=self.s;version=s.guard.version
        with patch.object(owner_codex,'setup',return_value={}), \
             patch.object(owner_codex.time,'sleep',side_effect=KeyboardInterrupt), \
             patch.object(s.store,'seal_config',create=True) as seal:
            owner_codex.session(s.store,60,4,1)
        self.assertGreater(s.guard.version,version)
        controls=seal.call_args.args[0]['listener']
        self.assertFalse(any(controls[k] for k in ('listen','wake_agent','auto_execute')))

    def test_ambiguous_replacement_contact_cannot_mutate_policy_or_grants(self):
        from axr_integration import owner_codex
        s=self.s;s.config['database']={'fixture':True};version=s.guard.version
        with patch.object(owner_codex,'qualify_existing_contacts',side_effect=AXRError('contact_identity_missing_or_ambiguous')), \
             patch.object(s.store,'seal_config',create=True) as seal:
            with self.assertRaisesRegex(AXRError,'ambiguous'):
                owner_codex.setup(s.store,60,4,['fixture new contact'])
            seal.assert_not_called()
        self.assertEqual(s.guard.version,version)

    def test_owner_selected_replacement_revokes_old_binding(self):
        from axr_integration import owner_codex
        from axr.aet import Action,Resource
        s=self.s;s.config['database']={'fixture':True}
        binding={'conversation_id':'new-fixture','display_name':'fixture new','data_class':'personal'}
        s.journal.taint_disclosure(s.principal,self.fixture.resource,'personal')
        with patch.object(owner_codex,'qualify_existing_contacts',return_value=[binding]) as qualify, \
             patch.object(s.store,'seal_config',create=True) as seal:
            owner_codex.setup(s.store,60,4,['fixture new'])
            qualify.assert_called_once_with(s.store,s.config,['fixture new'])
            self.assertEqual(seal.call_args.args[0]['conversations'],[binding])
            new_principal=seal.call_args.args[0]['principal']
            self.assertNotEqual(new_principal,s.principal)
        with self.assertRaises(AXRError):s.guard.check(s._read_action('friend',{}))
        s.guard.check(Action(new_principal,Resource('wechat',s.account,'new-fixture'),'messages.read',s.purpose,{}))
        self.assertEqual(len(s.journal.disclosure_taint(s.principal)),1)
        self.assertEqual(s.journal.disclosure_taint(new_principal),[])
        policy=seal.call_args.args[0]
        s.config=policy;s.principal=new_principal;s.destination=policy['agent_destination']
        s.bindings={'new-fixture':binding};s.initial_policy_digest=digest(policy)
        with patch.object(s.store,'config',return_value=policy):
            task=s.request_task('new-fixture')
            approve(s.store,task['disclosure_job'],new_principal)
            context=s.task_context(task['task_id'])
            draft=s.prepare('new-fixture','fixture new isolated draft',[context['context_id']])
            self.assertEqual(draft['state'],'Completed')
            self.assertEqual(s.finish_task(task['task_id'],draft['id'])['state'],'DraftReadyForHuman')


if __name__=='__main__':unittest.main()
