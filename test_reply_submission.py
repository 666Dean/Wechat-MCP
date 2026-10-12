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
