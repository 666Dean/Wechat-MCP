# SPDX-License-Identifier: MIT
"""Stopping while OS authentication is pending cannot revive authority."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from axr.aet import AXRError
    from axr_integration.broker import Broker,call
    import test_axr
except ModuleNotFoundError as exc:
    if exc.name=='axr':raise unittest.SkipTest('optional AXR SDK unavailable') from exc
    raise


class PendingAutomaticAuthorization(unittest.TestCase):
    def test_lifecycle_ack_bypasses_database_and_operation_locks(self):
        fixture=test_axr.ServiceTests();fixture.setUp();service=fixture.service
        class Wrapper:
            _delegate=service
            def _active(self):return self._delegate
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            broker=Broker(tmp,service=Wrapper());broker.router.bind('fixture')
            thread=threading.Thread(target=broker.serve);thread.start()
            try:
                with broker.control_lock,service.runtime.lock:
                    event=call(tmp,'control.codex_lifecycle',('fixture','UserPromptSubmit','turn','codex_hook_v1'),owner=True,timeout=1)
                    self.assertTrue(event['recorded'])
                    self.assertEqual(broker.router.status()['state'],'busy')
                    stopped=call(tmp,'control.codex_lifecycle',('fixture','Stop','turn','codex_hook_v1'),owner=True,timeout=1)
                    self.assertFalse(stopped['continue_pending'])
            finally:
                broker.server.shutdown();thread.join();broker.close();fixture.tearDown()
    def test_stop_cancels_pending_auth_before_session_exists(self):
        fixture=test_axr.ServiceTests();fixture.setUp();service=fixture.service
        entered=threading.Event();release=threading.Event();result={}
        class Wrapper:
            _delegate=service
            def _active(self):return self._delegate
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            helper=Path(tmp)/'helper';helper.write_bytes(b'fixture')
            broker=Broker(tmp,helper=helper,chat_helper=helper,service=Wrapper())
            thread=threading.Thread(target=broker.serve);thread.start()
            def auth(*a,**kw):entered.set();release.wait(3);return {'result':{'verified':True}}
            def start():
                try:call(tmp,'control.start_automatic',(['peer','self'],300,2),owner=True);result['started']=True
                except AXRError as exc:result['error']=str(exc)
            try:
                with patch('axr_integration.automatic_reply.validate_scope',return_value=helper),patch('axr.host.Supervisor.invoke',side_effect=auth):
                    waiter=threading.Thread(target=start);waiter.start();self.assertTrue(entered.wait(2))
                    self.assertTrue(call(tmp,'control.stop_automatic',owner=True,timeout=2)['stopped'])
                    release.set();waiter.join(3)
                self.assertNotIn('started',result);self.assertEqual(result['error'],'owner_policy_changed_review_again')
                self.assertIsNone(service.automatic);self.assertIsNone(broker.automatic_worker)
            finally:
                release.set();broker.server.shutdown();thread.join();broker.close();fixture.tearDown()
