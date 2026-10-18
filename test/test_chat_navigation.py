# SPDX-License-Identifier: MIT
"""Synthetic scoped-proof regression. Does not launch or interact with WeChat."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
try:
    from axr.aet import Action, Resource
    from axr.guard import Guard
except ModuleNotFoundError as exc:
    if exc.name == 'axr':raise unittest.SkipTest('optional AXR SDK unavailable') from exc
    raise


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('AXR_TEST_CHAT_NAVIGATION'),
                     'explicit macOS experimental helper required')
class ChatNavigationProof(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.guard = Guard(Path(self.temp.name)/'guard.db', b'n'*32)
        self.binding = {'pid':123,'window_id':456,'title':'微信',
                        'bounds':{'X':0,'Y':0,'Width':320,'Height':240}}

    def tearDown(self):
        self.guard.close();self.temp.cleanup()

    def request(self, operation='application.navigate',phase=None):
        text = 'fixture recipient' if operation == 'application.navigate' else 'fixture reply'
        binding = copy.deepcopy(self.binding)
        if operation == 'messages.send':
            binding.update(recipient_assurance='cached_exact_draft_and_fresh_search',recipient_witness='a'*64)
        payload = {'text':text,'visual_binding':binding}
        if operation == 'application.navigate':
            payload['navigation_binding']={'menu_path':['编辑','搜索'],'main_window_id':456,'query':text}
            if phase is not None:payload['navigation_binding']['phase']=phase
        action = Action('fixture-owner',Resource('wechat','fixture-account','fixture-chat'),
                        operation,'fixture-purpose',payload)
        grant = self.guard._issue_owner(principal=action.principal,resource=action.resource,
            operations=[operation],purpose=action.purpose,expires_at=time.time()+60,max_uses=1,intent=action.seal)
        gid,version = self.guard.consume(action)
        request={'mode':'validate_scope','operation':operation,'expected_text':text,
                'account':'fixture-account','identity':'fixture-chat','visual_binding':binding,
                'guard_context':self.guard.execution_proof(action,gid,version)}
        if phase is not None:request['navigation_phase']=phase
        return request,grant

    def test_navigation_phases_are_separately_sealed_before_ui(self):
        for phase in ('open','query','select'):
            with self.subTest(phase=phase):
                req,_=self.request(phase=phase)
                self.assertTrue(self.invoke(req)['scope_valid'])
                req['navigation_phase']='query' if phase!='query' else 'select'
                self.assertEqual(self.invoke(req)['error'],'authority_or_scope_changed')

    def invoke(self, req):
        result=subprocess.run([os.environ['AXR_TEST_CHAT_NAVIGATION']],input=json.dumps(req)+'\n',
                              text=True,capture_output=True,timeout=5,check=True)
        result=json.loads(result.stdout)
        self.assertIs(result.get('send_invoked'),False)
        return result

    def test_all_scopes_validate_without_ui(self):
        for operation in ('application.navigate','application.draft','messages.read','messages.send'):
            with self.subTest(operation=operation):
                req,_=self.request(operation);result=self.invoke(req)
                self.assertIs(result['scope_valid'],True)
                self.assertIs(result['ui_accessed'],False)
                self.assertIs(result['send_available'],False)

    def test_substituted_query_target_window_and_operation_denied(self):
        req,_=self.request()
        for field,value in (('expected_text','other'),('identity','other'),('account','other'),('operation','application.draft')):
            changed=copy.deepcopy(req);changed[field]=value
            self.assertEqual(self.invoke(changed)['error'],'authority_or_scope_changed')
        for field,value in (('pid',999),('window_id',999),('bounds',{'X':1})):
            changed=copy.deepcopy(req);changed['visual_binding'][field]=value
            self.assertEqual(self.invoke(changed)['error'],'authority_or_scope_changed')

    def test_revocation_and_missing_proof_denied(self):
        req,grant=self.request();self.guard.revoke_owner(grant)
        self.assertEqual(self.invoke(req)['error'],'authority_or_scope_changed')
        req.pop('guard_context');self.assertEqual(self.invoke(req)['error'],'sealed_scope_required')

    def test_send_requires_exact_recipient_witness(self):
        req,_=self.request('messages.send');req['visual_binding'].pop('recipient_witness')
        self.assertEqual(self.invoke(req)['error'],'recipient_witness_required')

    def test_navigation_proof_also_binds_exact_menu_command(self):
        # Visual binding alone must never stand in for the SDK navigation binding.
        req,_=self.request();req['operation']='application.navigate'
        action=Action('fixture-owner',Resource('wechat','fixture-account','fixture-chat'),
            'application.navigate','fixture-purpose',{'text':req['expected_text'],'visual_binding':self.binding,
              'navigation_binding':{'menu_path':['文件','发起会话'],'main_window_id':456,'query':req['expected_text']}})
        gid=self.guard._issue_owner(principal=action.principal,resource=action.resource,operations=['application.navigate'],
            purpose=action.purpose,expires_at=time.time()+60,max_uses=1,intent=action.seal)
        gid,version=self.guard.consume(action);req['guard_context']=self.guard.execution_proof(action,gid,version)
        self.assertEqual(self.invoke(req)['error'],'authority_or_scope_changed')
