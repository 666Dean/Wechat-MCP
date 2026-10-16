# SPDX-License-Identifier: MIT
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import run_codex_manual as worker


class CodexManualWorker(unittest.TestCase):
    def test_automatic_worker_requires_shared_broker_and_has_no_issuer_tools(self):
        with self.assertRaisesRegex(ValueError,'requires_broker'):
            worker.run(Path('/fixture'),Path('/state'),60,automatic=True)
        with patch.object(worker.shutil,'which',return_value='codex'):
            args=worker.command(Path('/fixture'),Path('/state'),60,broker=True,automatic=True)
        settings=[args[i+1] for i,v in enumerate(args) if v=='-c']
        server_args=json.loads(next(v.split('=',1)[1] for v in settings if v.startswith('mcp_servers.wechat_axr.args=')))
        self.assertIn('--broker',server_args);self.assertNotIn('--listener',server_args)
        self.assertFalse(any('owner' in t or 'send' in t or 'execute' in t for t in worker.TOOLS))

    def test_bound_thread_is_status_routing_and_never_inherits_developer_history(self):
        identity='00000000-0000-4000-8000-000000000001'
        with patch.object(worker.shutil,'which',return_value='codex'):
            args=worker.command(Path('/fixture'),Path('/state'),300,broker=True,automatic=True,thread_id=identity)
        self.assertNotIn('resume',args);self.assertIn('--ephemeral',args);self.assertNotIn(identity,args)
        self.assertIn('multi_agent',args);self.assertIn('memories',args);self.assertIn('hooks',args)
        self.assertIn('--ignore-user-config',args)
        with self.assertRaises(ValueError):worker.command(Path('/fixture'),Path('/state'),300,thread_id=identity)

    def test_overview_cannot_enable_manual_reply_worker(self):
        with self.assertRaisesRegex(ValueError,'requires_review'):
            worker.run(Path('/fixture'),Path('/state'),60,overview=True)
    def test_review_worker_cannot_prepare_reply_or_send(self):
        with patch.object(worker.shutil,'which',return_value='codex'):
            args=worker.command(Path('/fixture'),Path('/state'),60,review=True)
        settings=[args[i+1] for i,v in enumerate(args) if v=='-c']
        enabled=next(v.split('=',1)[1] for v in settings if v.startswith('mcp_servers.wechat_axr.enabled_tools='))
        self.assertEqual(json.loads(enabled),worker.REVIEW_TOOLS)
        self.assertNotIn('wechat_prepare_reply',json.loads(enabled))
        self.assertNotIn('wechat_finish_task',json.loads(enabled))
        self.assertIn('wechat_acknowledge_review',json.loads(enabled))
        server_args=json.loads(next(v.split('=',1)[1] for v in settings if v.startswith('mcp_servers.wechat_axr.args=')))
        self.assertNotIn('--listener',server_args)

    def test_review_rejects_unexpected_reply_event_without_logging_body(self):
        class Process:
            pid=1
            stdin=io.StringIO()
            stdout=io.StringIO(json.dumps({'type':'item.completed','item':{'type':'mcp_tool_call',
                'tool':'wechat_prepare_reply','status':'completed','result':{'private':'fixture secret'}}})+'\n')
            stderr=io.StringIO()
            def poll(self):return 0
            def wait(self,timeout):return 0
        output=io.StringIO()
        with patch.object(worker,'command',return_value=['fixture']),patch.object(worker.subprocess,'Popen',return_value=Process()),patch.object(worker.sys,'stdout',output):
            with self.assertRaisesRegex(ValueError,'unexpected_codex_tool'):
                worker.run(Path('/fixture'),Path('/state'),60,review=True)
        self.assertNotIn('fixture secret',output.getvalue())

    def test_only_scoped_manual_mcp_without_external_tools(self):
        with patch.object(worker.shutil,'which',return_value='codex'):
            args=worker.command(Path('/fixture'),Path('/state'),60)
        settings=[args[i+1] for i,v in enumerate(args) if v=='-c']
        self.assertIn('approval_policy="never"',settings)
        self.assertIn('web_search="disabled"',settings)
        self.assertIn('--ignore-user-config',args)
        enabled=next(v.split('=',1)[1] for v in settings if v.startswith('mcp_servers.wechat_axr.enabled_tools='))
        self.assertEqual(json.loads(enabled),worker.TOOLS)
        self.assertFalse(any('send' in t or 'owner' in t or 'execute' in t for t in worker.TOOLS))
        self.assertTrue(any('--manual-replies' in v for v in settings))

    def test_model_events_do_not_print_authorized_chat_text(self):
        secret='fixture private body'
        event={'type':'item.completed','item':{'type':'mcp_tool_call','tool':'wechat_get_task_context','status':'completed',
            'result':{'content':[{'type':'text','text':json.dumps({'body_disclosed':True,'messages':[secret]})}]}}}
        class Process:
            pid=1
            stdin=io.StringIO()
            stdout=io.StringIO(json.dumps(event)+'\n')
            stderr=io.StringIO(secret)
            def poll(self):return 0
            def wait(self,timeout):return 0
        output=io.StringIO()
        with patch.object(worker,'command',return_value=['fixture']),patch.object(worker.subprocess,'Popen',return_value=Process()),patch.object(worker.sys,'stdout',output):
            result=worker.run(Path('/fixture'),Path('/state'),60)
        self.assertEqual(result['disclosed_batches'],1)
        self.assertNotIn(secret,output.getvalue()+json.dumps(result))
        self.assertFalse(result['chat_logs_saved']);self.assertFalse(result['agent_sent'])

    def test_unexpected_agent_file_or_web_action_fails_closed(self):
        class Process:
            pid=1
            stderr=io.StringIO()
            def poll(self):return 0
            def wait(self,timeout):return 0
        for kind in ('command_execution','file_change','web_search'):
            process=Process();process.stdin=io.StringIO()
            process.stdout=io.StringIO(json.dumps({'type':'item.started','item':{'type':kind}})+'\n')
            with patch.object(worker,'command',return_value=['fixture']),patch.object(worker.subprocess,'Popen',return_value=process):
                with self.assertRaisesRegex(ValueError,'unexpected_codex_command'):
                    worker.run(Path('/fixture'),Path('/state'),60)


if __name__=='__main__':unittest.main()
