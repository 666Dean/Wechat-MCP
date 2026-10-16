# SPDX-License-Identifier: MIT
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
try:from axr.aet import AXRError
except ModuleNotFoundError:raise unittest.SkipTest('AXR optional')
from axr_integration.broker import Broker,RemoteService,call,read_connection
from desktop.codex_config import snippet,replace_section,install,restore
import hashlib


class Fixture:
    def __init__(self):self.calls=0
    def status(self):return {'fixture':True,'calls':self.calls,'send_available':False}
    def conversations(self,offset=0,limit=100):self.calls+=1;return {'conversations':[],'calls':self.calls}
    def close(self):pass


class DesktopBroker(unittest.TestCase):
    def test_two_clients_share_one_authority_and_cannot_manage_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=Fixture();broker=Broker(tmp,service=service)
            thread=threading.Thread(target=broker.serve);thread.start()
            try:
                a=RemoteService(tmp);b=RemoteService(tmp)
                self.assertEqual(a.conversations()['calls'],1)
                self.assertEqual(b.conversations()['calls'],2)
                self.assertEqual(a.status()['calls'],2)
                for method in ['control.approve','control.revoke_all','control.grant_local','control.configure_cache','control.start_automatic','control.stop_automatic','close','_active','guard']:
                    with self.assertRaises(AXRError):call(tmp,method)
                self.assertEqual(service.calls,2)
                with self.assertRaises(AXRError):Broker(tmp,service=Fixture())
                # A stale epoch/token is rejected; no arbitrary exception is returned.
                data=read_connection(tmp);original_epoch=data['epoch'];data['epoch']='stale'
                path=Path(tmp)/'desktop-runtime/client.json';path.write_text(json.dumps(data));path.chmod(0o600)
                with self.assertRaisesRegex(AXRError,'authentication'):a.conversations()
                data['epoch']=original_epoch;path.write_text(json.dumps(data));path.chmod(0o600)
            finally:
                broker.server.shutdown();thread.join();broker.close()
            self.assertFalse((Path(tmp)/'desktop-runtime/client.json').exists())
    def test_optional_client_remains_available_when_broker_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(RemoteService(tmp).status()['initialization']['state'],'broker_unavailable')
    def test_interpreter_entry_is_preserved_without_dereferencing_venv(self):
        import sys,tomllib
        entry=Path(sys.executable).absolute()
        section=snippet(entry,'/server.py','/state')
        self.assertEqual(tomllib.loads(section)['mcp_servers']['wechat_axr']['command'],str(entry))
        from scripts.build_desktop import build
        with tempfile.TemporaryDirectory() as tmp:
            app=build(tmp,entry,Path.cwd(),'/state',platform='darwin')
            self.assertIn(str(entry), (app/'Contents/MacOS/WeChatMCP').read_text())
    def test_config_preserves_others_and_rejects_stale_overwrite_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=root/'config.toml'
            original='model = "fixture"\n[mcp_servers.other]\ncommand = "keep"\n'
            config.write_text(original)
            section=snippet('/python','/server.py','/state')
            sha=hashlib.sha256(config.read_bytes()).hexdigest()
            result=install(config,section,sha,root/'backup')
            self.assertIn('command = "keep"',config.read_text());self.assertIn('required = false',config.read_text())
            with self.assertRaisesRegex(AXRError,'changed'):install(config,section,sha,root/'backup')
            restore(config,result['backup'],result['installed_sha256'])
            self.assertEqual(config.read_text(),original)
            with self.assertRaises(AXRError):replace_section('[mcp_servers.wechat_axr.env]\na="b"\n',section)

class OwnerAuthenticationRace(unittest.TestCase):
    def test_emergency_revocation_interrupts_pending_auth_and_cannot_revive_permission(self):
        import test_axr
        from unittest.mock import patch
        from axr.owner import review
        fixture=test_axr.ServiceTests();fixture.setUp();service=fixture.service
        entered=threading.Event();release=threading.Event();result={}
        class Wrapper:
            _delegate=service
            def _active(self):return self._delegate
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            helper=Path(tmp)/'helper';helper.write_text('synthetic only')
            broker=Broker(tmp,helper=helper,service=Wrapper())
            thread=threading.Thread(target=broker.serve);thread.start()
            action=service._action('friend','messages.send',{'text':'synthetic'},destination='wechat:'+fixture.resource.key)
            job=service.runtime.propose(action);seal=review(service.store,job['id'],service.principal)['seal']
            def auth(*args,**kwargs):entered.set();release.wait(3);return {'result':{'verified':True}}
            def approve_later():
                try:call(tmp,'control.approve',(job['id'],seal),owner=True);result['approved']=True
                except AXRError as exc:result['error']=str(exc)
            try:
                with patch('axr.host.Supervisor.invoke',side_effect=auth),patch.object(service.store,'seal_config',create=True):
                    waiter=threading.Thread(target=approve_later);waiter.start()
                    self.assertTrue(entered.wait(2))
                    stopped=call(tmp,'control.revoke_all',owner=True,timeout=2)
                    self.assertTrue(stopped['revoked']);release.set();waiter.join(3)
                self.assertNotIn('approved',result)
                self.assertEqual(result['error'],'owner_policy_changed_review_again')
                with self.assertRaises(AXRError):service.guard.check(action)
            finally:
                release.set();broker.server.shutdown();thread.join();broker.close();fixture.tearDown()
