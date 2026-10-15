# SPDX-License-Identifier: MIT
import unittest
from unittest.mock import patch
import test_axr
from axr.aet import AXRError,digest
from axr.owner import approve


class ReplySubmission(unittest.TestCase):
    def setUp(self):
        self.fixture=test_axr.ServiceTests();self.fixture.setUp();self.s=self.fixture.service
        self.s.config['mode']='hybrid';self.s.initial_policy_digest=digest(self.s.config)
        self.config=patch.object(self.s.store,'config',return_value=self.s.config);self.config.start()
        self.status=patch.object(self.s.adapter,'status',return_value={'send_available':True,'mode':'synthetic_qualified'});self.status.start()
        task=self.s.request_task('friend');approve(self.s.store,task['disclosure_job'],self.s.principal)
        context=self.s.task_context(task['task_id']);draft=self.s.prepare('friend','fixture reply',[context['context_id']])
        self.s.finish_task(task['task_id'],draft['id']);self.task_id=task['task_id']
    def tearDown(self):
        self.config.stop();self.status.stop();self.fixture.tearDown()
    def test_exact_approval_submits_once_without_copy_and_observes_separately(self):
        s=self.s;first=s.submit_reply_task(self.task_id);self.assertEqual(first['send_job']['state'],'AwaitingApproval')
        jid=first['send_job']['id'];approve(s.store,jid,s.principal)
        def send(action,check,epoch):
            check();self.assertEqual(action.resource,self.fixture.resource)
            return {'epoch':epoch,'verified':True,'evidence_digest':digest('synthetic send')}
        with patch.object(s.adapter,'send',create=True,side_effect=send) as submitted:
            sent=s.submit_reply_task(self.task_id);again=s.submit_reply_task(self.task_id)
        self.assertEqual(sent['send_job']['state'],'Completed');self.assertTrue(sent['automatic_send'])
        self.assertEqual(again['send_job']['id'],jid);submitted.assert_called_once()
        self.assertFalse(sent['delivery_confirmed']);self.assertFalse(sent['retry'])
        self.assertTrue(s.journal.verify_audit())
    def test_unknown_is_retained_never_automatically_retried(self):
        s=self.s;jid=s.submit_reply_task(self.task_id)['send_job']['id'];approve(s.store,jid,s.principal)
        with patch.object(s.adapter,'send',create=True,side_effect=RuntimeError('synthetic uncertainty')) as send:
            first=s.submit_reply_task(self.task_id);second=s.submit_reply_task(self.task_id)
        self.assertEqual(first['send_job']['state'],'Unknown');self.assertEqual(second['send_job']['state'],'Unknown')
        send.assert_called_once();self.assertFalse(second['retry'])
    def test_manual_mode_and_unqualified_backend_block_before_proposal(self):
        self.s.manual_replies=True
        with self.assertRaisesRegex(AXRError,'human_submission'):self.s.submit_reply_task(self.task_id)
        self.s.manual_replies=False
        with patch.object(self.s.adapter,'status',return_value={'send_available':False}):
            with self.assertRaisesRegex(AXRError,'not_qualified'):self.s.submit_reply_task(self.task_id)
        self.assertEqual(self.s.journal.db.execute('SELECT count(*) FROM reply_submissions').fetchone()[0],0)

    def test_raw_send_entry_rejects_unqualified_status_without_creating_jobs(self):
        s=self.s;draft=s.inbox.get(self.task_id)['draft_job']
        draft_id=s.journal.result(draft,s.principal,s.guard.version)['draft_id']
        before=s.journal.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        for status in ({'send_available':False},{'send_available':'true'},
                       {'send_available':1},{},None,[]):
            with self.subTest(status=status),patch.object(s.adapter,'status',return_value=status):
                with self.assertRaisesRegex(AXRError,'send_backend_not_qualified'):
                    s.propose_send('friend',draft_id)
                with self.assertRaisesRegex(AXRError,'send_backend_not_qualified'):
                    s.submit_reply_task(self.task_id)
        with patch.object(s.adapter,'status',side_effect=RuntimeError('synthetic status failure')):
            with self.assertRaisesRegex(AXRError,'send_backend_not_qualified'):s.propose_send('friend',draft_id)
            with self.assertRaisesRegex(AXRError,'send_backend_not_qualified'):s.submit_reply_task(self.task_id)
        self.assertEqual(s.journal.db.execute('SELECT count(*) FROM jobs').fetchone()[0],before)
        self.assertEqual(s.journal.db.execute('SELECT count(*) FROM reply_submissions').fetchone()[0],0)

    def test_database_mode_cannot_be_upgraded_by_adapter_status(self):
        s=self.s;s.config['mode']='wcdb';s.initial_policy_digest=digest(s.config)
        before=s.journal.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        with self.assertRaisesRegex(AXRError,'send_backend_not_qualified'):s.propose_send('friend','unused')
        with self.assertRaisesRegex(AXRError,'send_backend_not_qualified'):s.submit_reply_task(self.task_id)
        self.assertEqual(s.journal.db.execute('SELECT count(*) FROM jobs').fetchone()[0],before)

    def test_raw_proposal_revalidates_policy_and_keeps_exact_send_approval(self):
        s=self.s;draft=s.inbox.get(self.task_id)['draft_job']
        draft_id=s.journal.result(draft,s.principal,s.guard.version)['draft_id']
        before=s.journal.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        with patch.object(s.store,'config',return_value={**s.config,'purpose':'changed'}):
            with self.assertRaisesRegex(AXRError,'owner_policy_changed'):s.propose_send('friend',draft_id)
        self.assertEqual(s.journal.db.execute('SELECT count(*) FROM jobs').fetchone()[0],before)
        job=s.propose_send('friend',draft_id)
        self.assertEqual(job['state'],'AwaitingApproval')
        with patch.object(s.adapter,'send',create=True) as send:
            with self.assertRaises(AXRError):s.execute(job['id'])
            send.assert_not_called()

    def test_capability_lost_after_approval_cannot_reach_send_or_retry(self):
        s=self.s;jid=s.submit_reply_task(self.task_id)['send_job']['id'];approve(s.store,jid,s.principal)
        with patch.object(s.adapter,'status',return_value={'send_available':False}),\
                patch.object(s.adapter,'send',create=True) as send:
            # Execute an already sealed job: commit still checks current capabilities.
            result=s.execute(jid);self.assertEqual(result['state'],'Unknown')
            self.assertEqual(s.execute(jid)['state'],'Unknown');send.assert_not_called()
        with patch.object(s.adapter,'send',create=True) as send:
            repeated=s.submit_reply_task(self.task_id)
            self.assertEqual(repeated['send_job']['id'],jid)
            self.assertEqual(repeated['send_job']['state'],'Unknown');send.assert_not_called()
        self.assertFalse(repeated['retry']);self.assertTrue(s.journal.verify_audit())
