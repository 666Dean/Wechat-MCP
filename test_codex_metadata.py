# SPDX-License-Identifier: MIT
"""Public read-only metadata protocol: desktop sources, pagination and failures."""
import asyncio
import json
import sys
import unittest
from unittest.mock import patch
from axr.aet import AXRError
from axr_integration import codex_bridge

class MetadataTests(unittest.TestCase):
    def test_desktop_source_is_visible_and_cursor_is_preserved(self):
        async def request(method,params):
            self.assertEqual(method,'thread/list');self.assertIn('vscode',params['sourceKinds'])
            self.assertEqual(params['cursor'],'page-two');self.assertTrue(params['useStateDbOnly'])
            return {'data':[{'id':'synthetic','name':'Synthetic desktop task','preview':'not exposed'}],'nextCursor':'next'}
        with patch.object(codex_bridge,'_request',request):value=codex_bridge.threads('page-two')
        self.assertEqual(value,{'threads':[{'id':'synthetic','title':'Synthetic desktop task'}],'next_cursor':'next'})

    def test_rejected_initialize_never_requests_history(self):
        script="import json,sys;assert json.loads(sys.stdin.readline())['method']=='initialize';print(json.dumps({'id':1,'error':{'message':'synthetic rejection'}}),flush=True);assert not sys.stdin.readline()"
        real=asyncio.create_subprocess_exec
        async def process(*args,**kwargs):return await real(sys.executable,'-u','-c',script,**kwargs)
        with patch.object(codex_bridge.shutil,'which',return_value='/fixture/codex'),patch.object(codex_bridge.asyncio,'create_subprocess_exec',process):
            with self.assertRaisesRegex(AXRError,'^codex_metadata_unavailable$'):
                asyncio.run(codex_bridge._request('thread/list',{}))
