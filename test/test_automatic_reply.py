# SPDX-License-Identifier: MIT
"""Real Guard/Journal and MCP Service, synthetic original desktop/cache only."""
import contextlib
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
try:
    from axr.aet import AXRError,digest
    from axr.guard import Guard
    from axr.journal import Journal
    from axr.storage import Vault
    from axr_integration.service import Service
    from axr_integration.automatic_reply import validate_scope
    from test.test_chat_plan import SyntheticDesktop
except ModuleNotFoundError as exc:
    if exc.name=='axr':raise unittest.SkipTest('optional AXR SDK unavailable') from exc
    raise


class AutomaticReplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.helper=self.root/'sender';self.helper.write_bytes(b'synthetic pinned helper')
        dbroot=(self.root/'account'/'db_storage').resolve();self.dbroot=dbroot
        config={'principal':'codex-fixture','purpose':'wechat-assistant','account_id':'self','agent_destination':'model:codex',
                'mode':'wcdb','database':{'shards':[{'path':str(dbroot/'message/message_0.db')}],'engine':'sqlcipher'},
                'attribution_prefix':'【自动回复 · AI 助理】','conversations':[{'conversation_id':r,'display_name':r} for r in ('peer','self')],'listener':{}}
        self.config=config
        class Store:
            directory=self.root;vault=Vault(b'v'*32);guard=Guard(self.root/'guard.db',b'g'*32)
            journal=Journal(self.root/'journal.db',vault);secrets=SimpleNamespace(get=lambda ref:b'k'*32)
            def config(s):return config
            def close(s):s.guard.close();s.journal.close()
        self.events=[]
        outer=self
        class Adapter:
            def status(s):return {'mode':'fixture','send_available':False}
            def search(s,cid,**kw):
                return {'messages':[e for e in outer.events if e['conversation']==cid and e['created']>=kw.get('since',0)],'has_more':False,'cursor':None,'coverage':'fixture'}
            def close(s):pass
        self.s=Service(self.root,store=Store(),adapter=Adapter(),manual_replies=True,development_fixture=True,leases=self.root/'leases')
        self.addCleanup(self.s.close)
        self.patches=contextlib.ExitStack();self.addCleanup(self.patches.close)
        self.patches.enter_context(patch('axr_integration.automatic_reply.sys.platform','darwin'))
        self.patches.enter_context(patch.object(self.s,'start_listener'))
        self.s.start_automatic(['peer','self'],300,3,self.helper)
        self.s.automatic.listener['aggregate_seconds']=0
    def task(self,ref='new',outgoing=False,created=None):
        e={'reference':ref,'conversation':'peer','text':'请整理一个简短回复','sender':'peer','outgoing':outgoing,'created':created or time.time()}
        self.events.append(e);self.s.listener_since=int(e['created'])
        self.s.tick();tasks=self.s.poll_tasks()['tasks']
        return tasks[-1] if tasks else None
    def draft(self,task):
        value=self.s.task_context(task['task_id']);self.assertTrue(value['body_disclosed'])
        return self.s.prepare('peer','好的，已收到。',[value['context_id']])
    def desktop(self,**kwargs):
        desktop=SyntheticDesktop(self.root,**kwargs)
        prefix='axr_integration.chat_executor.'
        keys={rel:{'key_reference':'synthetic','cipher_profile':'wcdb4-raw'} for rel in ('general/general.db','session/session.db')}
        rows={rel:{'path':self.dbroot/rel} for rel in keys}
        opened=SimpleNamespace(stdout='\n'.join('n'+str(self.dbroot/r) for r in ('contact/contact.db','session/session.db')))
        for name,value in [('inventory',lambda root:rows),('verified_cached',lambda *a:keys),('open_database',lambda *a,**kw:desktop),
                           ('Supervisor',lambda **kw:desktop),('DatabaseAdapter',lambda *a:desktop),('subprocess.run',lambda *a,**kw:opened),('time.sleep',lambda n:None)]:
            self.patches.enter_context(patch(prefix+name,value))
        self.patches.enter_context(patch.object(Path,'home',return_value=self.root))
        return desktop
    @unittest.skipUnless(sys.platform=='darwin','macOS native sequence with synthetic desktop')
    def test_incoming_mcp_finish_sends_once_and_observes_without_promoting_unknown(self):
        task=self.task();draft=self.draft(task);desktop=self.desktop()
        result=self.s.finish_task(task['task_id'],draft['id'])
        self.assertEqual(result['state'],'Observed',result);self.assertTrue(result['database_record_observed'])
        self.assertEqual(result['send_job']['state'],'Unknown');self.assertFalse(result['delivery_confirmed'])
        self.assertEqual(desktop.sends,1);self.assertEqual(self.s.submit_reply_task(task['task_id']),{k:v for k,v in result.items() if k not in ('task_id','draft_job')})
        self.assertEqual(desktop.sends,1);self.assertTrue(self.s.journal.verify_audit())
        # Both original provenance and conservative disclosure taint survive.
        self.assertTrue(any(p['reference']=='new' for p in desktop.send_sources[0]))
        self.assertTrue(self.s.automatic.status()['active'])
    def test_outgoing_old_explicit_and_third_target_cannot_trigger(self):
        self.assertIsNone(self.task(outgoing=True));self.events=[]
        old=self.task('old',created=self.s.automatic.started-5)
        self.assertEqual(old['state'],'AwaitingApproval')
        with self.assertRaises(AXRError):self.s.task_context(old['task_id'])
        explicit=self.s.request_task('peer')
        with self.assertRaises(AXRError):self.s.task_context(explicit['task_id'])
        with self.assertRaises(AXRError):validate_scope(self.s,['peer','third'],300,3,self.helper)
    @unittest.skipUnless(sys.platform=='darwin','macOS native sequence with synthetic desktop')
    def test_unknown_stops_session_and_does_not_retry(self):
        task=self.task();draft=self.draft(task);desktop=self.desktop(observe=False)
        result=self.s.finish_task(task['task_id'],draft['id'])
        self.assertEqual(result['state'],'Unknown');self.assertEqual(desktop.sends,1)
        self.assertFalse(self.s.automatic.status()['active'])
        self.assertEqual(self.s.submit_reply_task(task['task_id']),{k:v for k,v in result.items() if k not in ('task_id','draft_job')})
        self.assertEqual(desktop.sends,1)
    @unittest.skipUnless(sys.platform=='darwin','macOS native sequence with synthetic desktop')
    def test_existing_input_preserved_and_claim_is_final(self):
        task=self.task();draft=self.draft(task);desktop=self.desktop(existing=True)
        result=self.s.finish_task(task['task_id'],draft['id'])
        self.assertEqual(result['state'],'Stopped');self.assertEqual(desktop.sends,0)
        self.assertTrue(desktop.input.startswith('user draft'))
        self.s.submit_reply_task(task['task_id']);self.assertEqual(desktop.sends,0)
    def test_expiry_stop_helper_change_and_policy_revoke_block_before_input(self):
        for kind in ('deadline','wall','stop','helper','revoke'):
            with self.subTest(kind=kind):
                auto=self.s.automatic
                if kind=='deadline':auto.deadline=time.monotonic()-1
                if kind=='wall':auto.expires=time.time()-1
                if kind=='stop':auto.stopped.set()
                if kind=='helper':self.helper.write_bytes(b'changed')
                if kind=='revoke':self.s.guard.revoke_owner('test')
                with self.assertRaises(AXRError):auto.check()
    def test_stop_does_not_wait_for_runtime_lock_and_invalidates_native_proof(self):
        entered=threading.Event();release=threading.Event()
        def hold():
            with self.s.runtime.lock:entered.set();release.wait(3)
        thread=threading.Thread(target=hold);thread.start();entered.wait(1)
        before=self.s.guard.version
        try:
            self.s.stop_automatic();self.assertGreater(self.s.guard.version,before)
        finally:release.set();thread.join()
        self.assertFalse(self.s.automatic.status()['active'])
