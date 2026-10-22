# SPDX-License-Identifier: MIT
"""Offscreen Windows Qt owner routing; no native owner, Hello or WeChat launch."""
import sys,time,unittest
from unittest.mock import patch
try:
    import test_desktop_ui as fixtures
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
except (ImportError,unittest.SkipTest):raise unittest.SkipTest('Desktop optional dependency unavailable')


@unittest.skipUnless(sys.platform=='win32','Windows independent owner UI')
class WindowsServiceDesktop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.DesktopUI.setUpClass()
    def setUp(self):
        self.fixture=fixtures.DesktopUI();self.controller,self.engine,self.window=self.fixture.create()
        self.controller.timer.stop();self.addCleanup(self.fixture.dispose,self.controller,self.engine,self.window)
    def test_pending_disclosure_has_real_review_button_and_fixed_owner_route(self):
        c,w=self.controller,self.window
        c._data.update(connected=True,status={'pending_review_supported':True,'manual_approval_required':True},
            jobs=[{'id':'fixture-disclosure','state':'AwaitingDisclosureApproval','operation':'disclosure.send',
                'created':time.time(),'expires':time.time()+100}])
        c.changed.emit();w.setProperty('page',2);QTest.qWait(60)
        self.assertEqual(len(w.property('approvals').toVariant()),1)
        button=self.fixture.visual(w,'pendingReview_fixture-disclosure');self.assertIsNotNone(button)
        self.assertEqual(button.property('text'),'核对并批准')
        c.fixture=False
        with patch.object(c,'run') as run,patch('desktop.app.call',return_value={'state':'DisclosureReady'}) as call:
            button.clicked.emit();run.call_args.args[1]()
        self.assertEqual(call.call_args.args[1],'control.approve_pending')
        self.assertEqual(call.call_args.args[2],('fixture-disclosure',));self.assertTrue(call.call_args.kwargs['owner'])
    def test_independent_approval_switch_tracks_authority_and_requests_owner_only(self):
        c,w=self.controller,self.window
        c._data.update(connected=True,status={'pending_review_supported':True,'manual_approval_required':True})
        c.changed.emit();w.setProperty('page',6);QTest.qWait(60)
        control=self.fixture.visual(w,'manualApprovalSwitch');self.assertIsNotNone(control);self.assertTrue(control.property('checked'))
        c._data['status']={**c._data['status'],'manual_approval_required':False};c.changed.emit();QTest.qWait(30)
        self.assertFalse(control.property('checked'))
        c.fixture=False
        with patch.object(c,'run') as run,patch('desktop.app.call',return_value={}) as call:
            control.setProperty('checked',True);control.clicked.emit();run.call_args.args[1]()
        self.assertEqual(call.call_args.args[1:3],('control.set_manual_approval',(True,)))
        self.assertTrue(call.call_args.kwargs['owner'])
