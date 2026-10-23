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
    def test_opening_desktop_only_schedules_read_only_connection_without_admin_start(self):
        from desktop.app import Controller
        with patch('desktop.app.authority_installed',return_value=True),patch('desktop.app.QTimer.singleShot') as schedule,patch.object(Controller,'run'):
            c=Controller('/unused-synthetic-startup')
        try:
            self.assertNotIn('start',[call.args[1].__name__ for call in schedule.call_args_list])
        finally:c.fixture=True;c.close()
    def test_offscreen_fixture_registers_os_collection_fonts_with_real_chinese_glyph(self):
        import os
        from pathlib import Path
        if not (Path(os.environ['SystemRoot'])/'Fonts/msyh.ttc').is_file():self.skipTest('optional Windows Chinese OS fonts')
        from desktop.fonts import configure
        from PySide6.QtWidgets import QApplication
        self.assertTrue(configure(QApplication.instance()))
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
    def test_windows_maintenance_has_fixed_buttons_and_cancel_does_not_elevate(self):
        from PySide6.QtCore import QObject
        c,w=self.controller,self.window
        c._setup_environment={'platform':'windows','installed':True,'credential':'synthetic.key'};c.setupChanged.emit()
        setup=w.findChild(QObject,'setupDialog');setup.open();setup.setProperty('step',1);QTest.qWait(40)
        c.fixture=False
        with patch.object(c,'run') as run:
            for name,dialog in (('updateWindowsService','windowsUpdateConfirmation'),('correctWindowsCredential','windowsSourceConfirmation')):
                button=self.fixture.visual(w,name);self.assertIsNotNone(button);self.assertTrue(button.isEnabled())
                button.clicked.emit();QTest.qWait(20)
                confirm=w.findChild(QObject,dialog);self.assertTrue(confirm.property('visible'));confirm.close()
                run.assert_not_called()
    def test_source_switch_clears_old_selection_and_late_inspection_cannot_change_visible_key_mode(self):
        c=self.controller;c._setup_inputs={'credential':'synthetic.key','index':False}
        c.setSetupCredentialMode('password');c.setSetupCredentialSource(True)
        self.assertNotIn('credential',c._setup_inputs);self.assertEqual(c.setupEnvironment['credential'],'')
        c.accept({'name':'setup_environment','error':None,'value':{'key_mode':'file','credential':'old.key','index':False}})
        self.assertEqual(c.setupEnvironment['key_mode'],'password');self.assertTrue(c.setupEnvironment['index'])
        self.assertEqual(c.setupEnvironment['credential'],'')
    def test_explicit_stop_and_review_buttons_use_separate_fixed_service_actions(self):
        from PySide6.QtCore import QObject
        c,w=self.controller,self.window;c._setup_environment={'platform':'windows','installed':True};c.setupChanged.emit()
        setup=w.findChild(QObject,'setupDialog');setup.open();setup.setProperty('step',1);QTest.qWait(40);c.fixture=False
        with patch.object(c,'run') as run,patch('desktop.windows_setup.invoke',return_value={}) as invoke:
            for name,operation in (('stopWindowsService','stop'),('reviewWindowsBuild','refresh')):
                self.fixture.visual(w,name).clicked.emit();run.call_args.args[1]();invoke.assert_called_with(operation)
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
