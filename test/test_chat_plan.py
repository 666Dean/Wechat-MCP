# SPDX-License-Identifier: MIT
"""Finite plans and real Guard/Journal with a synthetic cache-consuming desktop."""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
try:
    from axr.aet import AXRError
    from axr.guard import Guard
    from axr.storage import Vault
    from axr_integration.chat_plan import load_plan
    from axr_integration.owner_chat_send import main,claim_attempt
except ModuleNotFoundError as exc:
    if exc.name=='axr':raise unittest.SkipTest('optional AXR SDK unavailable') from exc
    raise

PREFIX='【自动回复 · AI 助理】 '


class SyntheticDesktop:
    def __init__(self,root,*,existing=False,observe=True):
        self.root=root;self.drafts={'peer':'user draft' if existing else '', 'self':''}
        self.active=None;self.input='';self.recent={};self.records=[];self.sends=0;self.observe=observe;self.send_sources=[]
        self.binding={'pid':123,'window_id':456,'title':'微信','bounds':{'X':0,'Y':0,'Width':800,'Height':600}}
    def invoke(self,command,req,**kw):
        mode=req['mode']
        if mode=='binding':result={'binding':self.binding.copy()}
        elif mode=='navigate':
            role=req['expected_text']
            if self.active!=role:
                if self.active is not None:self.drafts[self.active]=self.input
                self.active=role;self.input=self.drafts[role];self.drafts[role]=''
            self.recent[role]={'username':role,'query':role,'last_click_time':int(time.time())}
            result={'navigation_invoked':True,'query_echo_match':True,'main_window_verified':True,'send_invoked':False}
        elif mode=='stage_draft':
            self.input+=req['expected_text']
            result={'draft_match':self.input==req['expected_text'],'send_invoked':False,'stage_invoked':True}
        elif mode=='send':
            proof=json.loads(req['guard_context']['proof']);self.send_sources.append(proof['action']['sources'])
            if self.input!=req['expected_text']:raise AssertionError('wrong input submitted')
            if self.active!=req['identity']:raise AssertionError('wrong recipient submitted')
            self.sends+=1
            if self.observe:self.records.append({'text':self.input,'sender':'self','outgoing':True,'server_id':12345+self.sends,'conversation':self.active})
            self.input='';result={'draft_match':True,'send_invoked':True,'stage_invoked':False}
        else:raise AssertionError('unexpected native operation')
        return {'result':result}
    def query(self,sql,params=()):
        if 'FROM SearchRecent' in sql:
            return [v for v in self.recent.values() if v['query']==params[0] and v['last_click_time']>=params[1]]
        if 'instr(draft' in sql:return [{'username':k,'draft':v} for k,v in self.drafts.items() if params[0] in v]
        if 'FROM SessionTable WHERE username' in sql:
            value=self.drafts[params[0]];return [{'draft':value,'size':len(value.encode())}]
        raise AssertionError('unexpected SQL')
    def search(self,conversation,**payload):
        rows=[{k:v for k,v in m.items() if k!='conversation'} for m in self.records if m['conversation']==conversation and payload['query'] in m['text']]
        return {'messages':rows,'cursor':len(rows),'has_more':False}
    def close(self):pass
    def cancel(self):pass


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.path=self.root/'plan.json'
        self.plan={'version':1,'messages':[{'conversation_id':'peer','parking_conversation_id':'self','text':PREFIX+'fixture peer reply'},
                                          {'conversation_id':'self','parking_conversation_id':'peer','text':PREFIX+'fixture self reply'}]}
        self.save()
    def save(self):self.path.write_text(json.dumps(self.plan));self.path.chmod(0o600)
    def test_private_plan_and_side_effect_free_review(self):
        self.assertEqual(load_plan(self.path),self.plan)
        with patch('axr_integration.owner_chat_send.authenticate') as auth,contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['--state','unused','--native-helper','unused','--owner-helper','unused','--plan',str(self.path),'--check-plan']),0)
            self.assertIn('"ui_accessed": false',out.getvalue());auth.assert_not_called()
        if os.name!='nt':
            self.path.chmod(0o644)
            with self.assertRaisesRegex(AXRError,'private_regular_bounded_plan_required'):load_plan(self.path)
    def test_ambiguous_group_duplicate_and_unbounded_plans_rejected(self):
        for change in ('duplicate','group','official','third','text','field'):
            self.setUpPlan()
            if change=='duplicate':self.plan['messages'][1]=self.plan['messages'][0].copy()
            elif change=='group':self.plan['messages'][0]['conversation_id']='fixture@chatroom'
            elif change=='official':self.plan['messages'][0]['conversation_id']='gh_fixture'
            elif change=='third':self.plan['messages'][1]['parking_conversation_id']='third'
            elif change=='text':self.plan['messages'][0]['text']='x'*8001
            else:self.plan['messages'][0]['shell']='unexpected'
            self.save()
            with self.subTest(change=change),self.assertRaises(AXRError):load_plan(self.path)
    def setUpPlan(self):
        self.plan={'version':1,'messages':[{'conversation_id':'peer','parking_conversation_id':'self','text':PREFIX+'fixture peer reply'},
                                          {'conversation_id':'self','parking_conversation_id':'peer','text':PREFIX+'fixture self reply'}]}
    @unittest.skipUnless(sys.platform=='darwin','macOS finite sender workflow')
    def test_durable_attempt_claim_never_overwrites(self):
        attempt=self.root/'attempt.json';claim_attempt(attempt)
        with self.assertRaises(FileExistsError):claim_attempt(attempt)
        self.assertFalse(json.loads(attempt.read_text())['retry'])
    def run_synthetic(self,desktop):
        native=self.root/'native';native.write_bytes(b'synthetic executable identity')
        state=self.root/'state';state.mkdir(exist_ok=True)
        guard=Guard(state/'fixture-guard.db',b'g'*32);self.addCleanup(guard.close)
        dbroot=(self.root/'account'/'db_storage').resolve()
        config={'account_id':'self','attribution_prefix':PREFIX.strip(),'database':{'shards':[{'path':str(dbroot/'message'/'message_0.db')}],'engine':'sqlcipher','sqlcipher_library':'synthetic'},
                'conversations':[{'conversation_id':r,'display_name':r} for r in ('peer','self')]}
        class Store:
            def __init__(self,*a):self.guard=guard;self.vault=Vault(b'v'*32);self.secrets=SimpleNamespace(get=lambda key:b'k'*32)
            def config(self):return config
            def close(self):pass
        keys={rel:{'key_reference':'synthetic','cipher_profile':'wcdb4-raw'} for rel in ('general/general.db','session/session.db')}
        inventory={rel:{'path':dbroot/rel} for rel in keys}
        lsof=SimpleNamespace(stdout='\n'.join('n'+str(dbroot/r) for r in ('contact/contact.db','session/session.db')))
        with contextlib.ExitStack() as stack:
            prefix='axr_integration.chat_executor.'
            for name,value in [('authenticate',lambda path:None),('OwnerStore',Store),('inventory',lambda root:inventory),('verified_cached',lambda *a:keys),
                               ('open_database',lambda *a,**k:desktop),('Supervisor',lambda **k:desktop),('DatabaseAdapter',lambda *a:desktop),
                               ('subprocess.run',lambda *a,**k:lsof),('sys.platform','darwin'),('sys.stdin.isatty',lambda:True),('sys.stdout.isatty',lambda:True),('time.sleep',lambda n:None)]:
                location='axr_integration.owner_chat_send.' if name in ('authenticate','OwnerStore','sys.platform','sys.stdin.isatty','sys.stdout.isatty') else prefix
                stack.enter_context(patch(location+name,value))
            stack.enter_context(patch.object(Path,'home',return_value=self.root))
            out=stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(out,'isatty',return_value=True))
            code=main(['--state',str(state),'--native-helper',str(native),'--owner-helper',str(native),'--plan',str(self.path)])
            return code,out.getvalue()
    @unittest.skipUnless(sys.platform=='darwin','macOS finite sender workflow')
    def test_two_target_workflow_consumes_cache_and_submits_once_each(self):
        desktop=SyntheticDesktop(self.root)
        code,out=self.run_synthetic(desktop)
        self.assertEqual(code,0);self.assertEqual(desktop.sends,2)
        self.assertEqual(out.count('"exact_database_records": 1'),2)
        self.assertTrue(all(r['sender']=='self' for r in desktop.records))
        self.assertTrue(all(sources and all(p['data_class']=='personal' for p in sources) for sources in desktop.send_sources))
    @unittest.skipUnless(sys.platform=='darwin','macOS finite sender workflow')
    def test_nonempty_input_is_preserved_and_no_send_occurs(self):
        desktop=SyntheticDesktop(self.root,existing=True)
        with self.assertRaisesRegex(AXRError,'input_not_exact_unsent_draft_preserved'):self.run_synthetic(desktop)
        self.assertEqual(desktop.sends,0);self.assertTrue(desktop.input.startswith('user draft'))
    @unittest.skipUnless(sys.platform=='darwin','macOS finite sender workflow')
    def test_unknown_submission_stops_plan_without_second_send(self):
        desktop=SyntheticDesktop(self.root,observe=False)
        code,out=self.run_synthetic(desktop)
        self.assertEqual(code,1)
        self.assertEqual(desktop.sends,1)
