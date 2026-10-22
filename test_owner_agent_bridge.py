# SPDX-License-Identifier: MIT
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from desktop.owner_agent import OwnerAgentBridge

class OwnerAgentTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','Windows anonymous-pipe cancellation')
    def test_windows_idle_app_server_stops_and_releases_reader(self):
        script="import sys,time;sys.stdin.readline();time.sleep(30)"
        launched=threading.Event();finished=threading.Event();events=[];real=subprocess.Popen
        bridge=OwnerAgentBridge(lambda event:(events.append(event),finished.set() if event['kind']=='finished' else None))
        def fixture(args,**kwargs):
            process=real([sys.executable,'-u','-c',script],**kwargs);launched.set();return process
        with patch('desktop.owner_agent.codex_binary',return_value='/fixture/codex'),patch('desktop.owner_agent.subprocess.Popen',side_effect=fixture):
            bridge.start({'job_id':'idle-fixture','worker_token':'synthetic','expires':time.time()+10})
            self.assertTrue(launched.wait(2));bridge.stop();self.assertTrue(finished.wait(3));bridge.thread.join(1)
        self.assertIsNotNone(bridge.process.poll());self.assertTrue(events[-1]['failed'])
        self.assertFalse(any(thread.name=='owner-codex-output' and thread.is_alive() for thread in threading.enumerate()))

    @unittest.skipUnless(sys.platform=='win32','Windows bounded pipe protocol')
    def test_windows_oversized_app_server_frame_is_rejected(self):
        script="import sys,time;sys.stdin.readline();sys.stdout.write('x'*(2*1024*1024));sys.stdout.flush();time.sleep(30)"
        finished=threading.Event();events=[];real=subprocess.Popen
        bridge=OwnerAgentBridge(lambda event:(events.append(event),finished.set() if event['kind']=='finished' else None))
        def fixture(args,**kwargs):return real([sys.executable,'-u','-c',script],**kwargs)
        with patch('desktop.owner_agent.codex_binary',return_value='/fixture/codex'),patch('desktop.owner_agent.subprocess.Popen',side_effect=fixture):
            bridge.start({'job_id':'budget-fixture','worker_token':'synthetic','expires':time.time()+10})
            self.assertTrue(finished.wait(4));bridge.thread.join(1)
        self.assertTrue(events[-1]['failed']);self.assertIsNotNone(bridge.process.poll())

    def test_approval_is_exact_one_time_and_never_truncates_a_diff(self):
        row={'id':12,'method':'item/commandExecution/requestApproval','params':{'command':'echo synthetic','cwd':'fixture'}}
        value=OwnerAgentBridge.approval(row,{})
        self.assertIn('echo synthetic',value['detail'])
        self.assertIsNone(OwnerAgentBridge.approval({'id':1,'method':'unknown/approval'},{}))
        row['method']='item/fileChange/requestApproval';row['params']['itemId']='large'
        self.assertIsNone(OwnerAgentBridge.approval(row,{'large':{'changes':{'diff':'x'*50000}}}))
        bridge=OwnerAgentBridge(lambda e:None);bridge.pending={'12':12}
        with patch.object(bridge,'send') as send:
            self.assertTrue(bridge.decide('12',True));self.assertFalse(bridge.decide('12',True))
            self.assertEqual(send.call_args.args[0],{'id':12,'result':{'decision':'accept'}})
    def test_official_protocol_resume_and_approval_response_without_chat_or_tools(self):
        # A subprocess speaks real stdio framing. It never invokes Codex,
        # WeChat, owner credentials, a model or a developer conversation.
        script='''import json,sys
def read():return json.loads(sys.stdin.readline())
def send(v):print(json.dumps(v),flush=True)
assert read()['method']=='initialize';send({'id':1,'result':{}})
assert read()['method']=='initialized'
r=read();assert r['method']=='thread/resume';assert r['params']['approvalPolicy']=='untrusted';assert r['params']['sandbox']=='workspace-write'
send({'id':2,'result':{'thread':{'id':'synthetic-thread'}}})
r=read();assert r['method']=='turn/start';assert r['params']['threadId']=='synthetic-thread';assert r['params']['model']=='synthetic-model';assert r['params']['effort']=='high'
send({'id':3,'result':{'turn':{'id':'synthetic-turn'}}})
send({'id':31,'method':'item/commandExecution/requestApproval','params':{'threadId':'synthetic-thread','turnId':'synthetic-turn','command':'echo synthetic'}})
r=read();assert r=={'id':31,'result':{'decision':'decline'}}
send({'method':'item/agentMessage/delta','params':{'threadId':'synthetic-thread','turnId':'synthetic-turn','itemId':'answer','delta':'Synthetic'}})
send({'method':'item/completed','params':{'threadId':'synthetic-thread','turnId':'synthetic-turn','item':{'type':'agentMessage','id':'answer','text':'Synthetic command declined'}}})
send({'method':'turn/completed','params':{'threadId':'synthetic-thread','turn':{'id':'synthetic-turn','status':'completed'}}})
'''
        events=[];finished=threading.Event();bridge=None
        def emit(event):
            events.append(event)
            if event['kind']=='approval':bridge.decide(event['request_key'],False)
            if event['kind']=='finished':finished.set()
        bridge=OwnerAgentBridge(emit);real_popen=subprocess.Popen
        def fixture(args,**kwargs):return real_popen([sys.executable,'-u','-c',script],**kwargs)
        with patch('desktop.owner_agent.codex_binary',return_value='/fixture/codex'),patch('desktop.owner_agent.subprocess.Popen',side_effect=fixture):
            bridge.start({'job_id':'synthetic-job','thread_id':'synthetic-thread','worker_token':'synthetic-token','text':'synthetic task','model':'synthetic-model','effort':'high','expires':time.time()+10})
            self.assertTrue(finished.wait(5));bridge.thread.join(2)
        self.assertEqual(events[-1],{'kind':'finished','job_id':'synthetic-job','failed':False,'text':'Synthetic command declined'})
        self.assertEqual(len([e for e in events if e['kind']=='approval']),1)
        self.assertEqual([e for e in events if e['kind']=='delta'][0]['text'],'Synthetic')
