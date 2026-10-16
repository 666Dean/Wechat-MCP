# SPDX-License-Identifier: MIT
"""Unlimited delegation keeps short native grants, bounded queues and user-turn priority."""
import json,sys,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from test import test_automatic_reply as fixtures
from axr.aet import AXRError
from axr_integration.assistant_settings import save,load
from axr_integration.thread_router import ThreadRouter

class PersistentReply(unittest.TestCase):
    setUp=fixtures.AutomaticReplyTests.setUp
    task=fixtures.AutomaticReplyTests.task
    draft=fixtures.AutomaticReplyTests.draft
    desktop=fixtures.AutomaticReplyTests.desktop
    def test_unlimited_is_session_scope_not_permanent_native_grant(self):
        self.s.stop_automatic();self.s.start_automatic(['peer','self'],0,0,self.helper);auto=self.s.automatic
        self.assertIsNone(auto.expires);self.assertIsNone(auto.deadline);self.assertIsNone(auto.limit)
        auto.used=1000001;self.assertTrue(auto.status()['active']);self.assertIsNone(auto.status()['remaining'])
        before=self.s.journal.clock();auto.access.clear();auto.ensure_access('peer')
        import sqlite3
        with sqlite3.connect(self.s.guard.path) as db:
            grants=[json.loads(row[0]) for row in db.execute('SELECT body FROM grants WHERE revoked=0')]
        current=[g for g in grants if g['policy_version']==self.s.guard.version]
        self.assertTrue(current);self.assertTrue(all(g['expires_at']<=before+301 for g in current))
        self.assertTrue(all('messages.send' not in g['operations'] for g in current))
    def test_encrypted_preferences_validate_persona_and_explicit_attribution(self):
        value={'thread_id':'00000000-0000-4000-8000-000000000001','thread_title':'Fixture','persona':'私有合成人设',
               'style':'简短自然','attribution':False}
        save(self.s.store,value);self.assertEqual(load(self.s.store),value)
        self.assertNotIn('私有合成人设'.encode(),(self.root/'assistant-preferences.sealed').read_bytes())
        for field,value2 in [('attribution','false'),('persona','x'*12001),('thread_id','not-a-thread')]:
            with self.subTest(field=field),self.assertRaises(AXRError):save(self.s.store,{**value,field:value2})
    def test_busy_queue_contains_only_references_then_reloads_exact_inbound(self):
        auto=self.s.automatic;auto.preferences={'thread_id':'fixture'};auto.listener['aggregate_seconds']=0
        with patch.object(auto,'materialize'):self.task()
        self.assertTrue(auto.has_pending());self.assertEqual(self.s.inbox.list(),[])
        row=self.s.journal.db.execute('SELECT id,payload FROM automatic_pending').fetchone()
        queued=self.s.store.vault.open(row['payload'],row['id']+':pending')
        self.assertEqual(set(queued),{'cid','refs','since','until'});self.assertNotIn('text',str(queued))
        tasks=self.s.poll_tasks()['tasks'];self.assertEqual(len(tasks),1)
        self.assertEqual(tasks[0]['state'],'Ready');self.assertFalse(auto.has_pending())
    def test_missing_ref_is_not_treated_as_empty_or_approved(self):
        auto=self.s.automatic;auto.preferences={'thread_id':'fixture'}
        with patch.object(auto,'materialize'):self.task()
        self.events=[]
        with self.assertRaises(AXRError):auto.materialize()
        self.assertTrue(auto.has_pending());self.assertFalse(self.s.inbox.list())
    def test_listener_drains_remaining_page_without_another_database_write(self):
        path=self.dbroot/'message/message_0.db';path.parent.mkdir(parents=True);path.write_bytes(b'change hint only')
        calls=[];original=self.s.adapter.search
        def search(cid,**kwargs):
            calls.append(cid);page=original(cid,**kwargs)
            page['has_more']=calls==['peer'];return page
        with patch.object(self.s.adapter,'search',side_effect=search):
            self.s.tick();self.assertEqual(calls,['peer','self'])
            self.s.tick();self.assertEqual(calls,['peer','self','peer'])
            self.s.tick();self.assertEqual(calls,['peer','self','peer'])
    @unittest.skipUnless(sys.platform=='darwin','synthetic Mac UI sequence')
    def test_owner_can_disable_attribution_without_losing_source_checks(self):
        self.s.automatic.preferences={'attribution':False}
        task=self.task();draft=self.draft(task);desktop=self.desktop()
        result=self.s.finish_task(task['task_id'],draft['id'])
        self.assertEqual(result['state'],'Observed',result)
        self.assertFalse(desktop.records[0]['text'].startswith('【'))
        self.assertTrue(desktop.send_sources[0])
    @unittest.skipUnless(sys.platform=='darwin','synthetic Mac UI sequence')
    def test_identical_answers_to_distinct_new_tasks_are_not_unknown_retries(self):
        first=self.task('first');draft=self.draft(first);desktop=self.desktop()
        one=self.s.finish_task(first['task_id'],draft['id'])
        self.assertEqual(one['state'],'Observed',one)
        second=self.task('second');draft=self.draft(second)
        two=self.s.finish_task(second['task_id'],draft['id'])
        self.assertEqual(two['state'],'Observed',two);self.assertEqual(desktop.sends,2)
        self.assertEqual(desktop.records[0]['text'],desktop.records[1]['text'])
        self.assertNotEqual(desktop.records[0]['server_id'],desktop.records[1]['server_id'])
        self.s.submit_reply_task(first['task_id']);self.s.submit_reply_task(second['task_id'])
        self.assertEqual(desktop.sends,2)

class Router(unittest.TestCase):
    def make(self):
        class Broker:
            def __init__(self):self.automatic_worker=None;self.starts=[];self.service=SimpleNamespace(_delegate=None)
            def stop_worker(self):pass
            def start_worker(self,duration,thread):self.starts.append((duration,thread))
        broker=Broker();router=ThreadRouter(broker);router.bind('fixture');return broker,router
    def test_active_or_unknown_never_steers_or_prefills_a_composer(self):
        b,r=self.make();r.pending=True
        for state in ('awaiting_lifecycle','busy','paused','worker'):
            r.state=state;r.schedule();self.assertFalse(b.starts)
        self.assertTrue(r.event('other','Stop','turn')['ignored'])
    def test_stop_continues_pending_in_same_loop_and_interrupt_pauses(self):
        b,r=self.make();r.event('fixture','UserPromptSubmit','turn')
        active=True;pending=True
        auto=SimpleNamespace(status=lambda:{'active':active},has_pending=lambda:pending)
        b.service._delegate=SimpleNamespace(automatic=auto,inbox=SimpleNamespace(list=lambda:[]))
        self.assertTrue(r.event('fixture','Stop','turn')['continue_pending']);self.assertEqual(r.state,'busy')
        r.event('fixture','Interrupt','turn');self.assertEqual(r.state,'paused')
        pending=False;self.assertFalse(r.event('fixture','Stop','turn')['continue_pending']);self.assertEqual(r.state,'idle')
        pending=True;active=False
        self.assertFalse(r.event('fixture','Stop','turn')['continue_pending'])
    def test_idle_handoff_waits_for_quiet_period_then_resumes_exact_thread(self):
        import threading
        b,r=self.make();auto=SimpleNamespace(status=lambda:{'active':True},has_pending=lambda:True)
        b.service._delegate=SimpleNamespace(automatic=auto,runtime=SimpleNamespace(lock=threading.RLock()),inbox=SimpleNamespace(list=lambda:[]))
        r.state='idle';r.ready_at=time.monotonic()+5;r.schedule();self.assertFalse(b.starts)
        r.ready_at=0;r.schedule();self.assertEqual(b.starts,[(300,'fixture')]);self.assertEqual(r.state,'worker')
    def test_worker_hook_cannot_interrupt_itself_but_desktop_user_has_priority(self):
        b,r=self.make();b.worker_hook_token='fixture-token';r.state='worker'
        with patch.object(b,'stop_worker') as stop:
            result=r.event('fixture','UserPromptSubmit','worker-turn','codex_hook_v1','fixture-token')
            self.assertTrue(result['worker_event']);self.assertEqual(r.state,'worker');stop.assert_not_called()
            r.event('fixture','UserPromptSubmit','user-turn','codex_hook_v1')
            self.assertEqual(r.state,'busy');stop.assert_called_once()
