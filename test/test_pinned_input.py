# SPDX-License-Identifier: MIT
"""Native proof tests use synthetic identities and never access a real UI."""
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
    from axr.aet import Action,Resource
    from axr.guard import Guard
except ModuleNotFoundError as exc:
    if exc.name=='axr':raise unittest.SkipTest('optional native AXR SDK unavailable') from exc
    raise


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('AXR_TEST_PINNED_INPUT'),
                     'explicit macOS experimental helper build required')
class PinnedInputProof(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.guard=Guard(Path(self.temp.name)/'guard.db',b'g'*32)
        binding={'pid':123,'window_id':456,'title':'fixture title',
                 'bounds':{'X':0,'Y':0,'Width':320,'Height':240},
                 'input_initialization':'owner_attested_empty_and_focused'}
        self.action=Action('fixture-owner',Resource('wechat','fixture-account','fixture-chat'),
            'messages.send','fixture-purpose',{'text':'fixture reply','visual_binding':binding})
        self.grant=self.guard._issue_owner(principal=self.action.principal,resource=self.action.resource,
            operations=['messages.send'],purpose=self.action.purpose,expires_at=time.time()+60,
            max_uses=1,intent=self.action.seal)
        gid,version=self.guard.consume(self.action)
        self.request={'mode':'validate_scope','title':binding['title'],'window_id':456,
            'expected_text':'fixture reply','account':'fixture-account','identity':'fixture-chat',
            'visual_binding':binding,'guard_context':self.guard.execution_proof(self.action,gid,version)}

    def tearDown(self):
        self.guard.close();self.temp.cleanup()

    def invoke(self,request):
        result=subprocess.run([os.environ['AXR_TEST_PINNED_INPUT']],input=json.dumps(request)+'\n',
            capture_output=True,text=True,timeout=5,check=True)
        reply=json.loads(result.stdout)
        self.assertIs(reply.get('send_invoked'),False)
        return reply

    def test_scope_validation_has_no_ui_or_send_capability(self):
        reply=self.invoke(self.request)
        self.assertIs(reply['scope_valid'],True)
        self.assertIs(reply['ui_accessed'],False)
        self.assertIs(reply['send_available'],False)

    def test_substitution_denied_before_ui(self):
        for field,value in [('account','other-account'),('identity','other-chat'),
                            ('expected_text','other reply'),('title','other title'),('window_id',999)]:
            with self.subTest(field=field):
                request=copy.deepcopy(self.request);request[field]=value
                self.assertIn(self.invoke(request)['error'],('authority_or_scope_changed','sealed_scope_required'))
        for field,value in [('pid',999),('bounds',{'X':1,'Y':0,'Width':320,'Height':240}),
                            ('input_initialization','unverified')]:
            with self.subTest(binding_field=field):
                request=copy.deepcopy(self.request);request['visual_binding'][field]=value
                self.assertEqual(self.invoke(request)['error'],'authority_or_scope_changed')

    def test_revoked_proof_denied_before_ui(self):
        self.guard.revoke_owner(self.grant)
        self.assertEqual(self.invoke(self.request)['error'],'authority_or_scope_changed')

    def test_read_and_stage_require_proof_before_ui(self):
        for mode in ('read','send','prepare_send'):
            with self.subTest(mode=mode):
                request=copy.deepcopy(self.request);request['mode']=mode;request.pop('guard_context')
                self.assertEqual(self.invoke(request)['error'],'sealed_scope_required')
