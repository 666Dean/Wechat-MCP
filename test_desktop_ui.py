# SPDX-License-Identifier: MIT
"""Actual Qt/QML fixture layout, capability labels, themes and keyboard navigation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
import unittest
from pathlib import Path
try:
    from PySide6.QtCore import QUrl,QCoreApplication,QEvent,Qt,QObject,QPointF
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtTest import QTest
    from desktop.app import Controller
except ModuleNotFoundError:raise unittest.SkipTest('Desktop optional: install requirements.desktop.txt')


class DesktopUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle('Basic')
        cls.app=QApplication.instance() or QApplication([])
    def create(self,case='empty'):
        controller=Controller('/fixture-unused',fixture=True,fixture_case=case)
        engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('owner',controller)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).parent/'desktop/Main.qml')))
        self.assertTrue(engine.rootObjects());return controller,engine,engine.rootObjects()[0]
    def dispose(self,controller,engine,window):
        window.close();controller.close();engine.deleteLater();controller.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    def visual(self,window,name):
        pending=[window.contentItem()]
        while pending:
            item=pending.pop()
            if item.objectName()==name:return item
            pending.extend(item.childItems())
        return None
    def test_all_pages_sizes_themes_and_nonoverlapping_footer(self):
        c,e,w=self.create('content')
        try:
            for width,height in [(1280,800),(1440,900),(1920,1080)]:
                w.setWidth(width);w.setHeight(height)
                for dark in (False,True):
                    w.setProperty('darkMode',dark)
                    for page in range(10):
                        w.setProperty('page',page);QTest.qWait(35)
                        image=w.grabWindow();self.assertFalse(image.isNull())
                        footer=w.findChild(QObject,'statusBar')
                        viewport=w.findChild(QObject,'contentViewport')
                        self.assertIsNotNone(footer);self.assertIsNotNone(viewport)
                        self.assertEqual(round(footer.property('height')),32)
                        self.assertLessEqual(viewport.property('y')+viewport.property('height'),footer.property('y')+1)
                        self.assertFalse(w.property('connected'));self.assertFalse(w.property('sendAvailable'))
                        card=self.visual(w,'sidebarCard');self.assertIsNotNone(card)
                        top=card.mapToItem(w.contentItem(),QPointF(0,0)).y()
                        bottom=w.contentItem().height()-top-card.height()
                        self.assertAlmostEqual(top,bottom,delta=1)
                        self.assertLessEqual(top,16)
                        if page==7:
                            manual=self.visual(w,'manualDraftText');self.assertIsNotNone(manual)
                            self.assertGreater(manual.width(),200)
        finally:self.dispose(c,e,w)
    def test_empty_loading_error_and_keyboard_page_navigation(self):
        from PySide6.QtCore import QObject
        for case in ['empty','loading','error']:
            c,e,w=self.create(case)
            try:
                QTest.qWait(40)
                self.assertEqual(c.data['loading'],case=='loading')
                self.assertTrue(w.property('previewMode'));self.assertFalse(w.property('connected'))
                nav=self.visual(w,'nav6');self.assertIsNotNone(nav);nav.forceActiveFocus();QTest.keyClick(w,Qt.Key_Return)
                QTest.qWait(20);self.assertEqual(w.property('page'),6)
                nav=self.visual(w,'nav7');self.assertIsNotNone(nav);nav.forceActiveFocus();QTest.keyClick(w,Qt.Key_Return)
                QTest.qWait(20);self.assertEqual(w.property('page'),7)
                self.assertFalse(w.grabWindow().isNull())
            finally:self.dispose(c,e,w)
    def test_manual_copy_revalidates_and_rejects_changed_payload(self):
        import time
        from unittest.mock import patch
        c,e,w=self.create();c.timer.stop();c.fixture=False
        draft={'job_id':'fixture-draft','conversation_id':'fixture-chat','display_name':'Synthetic recipient',
            'text':'Synthetic reviewed reply','expires':time.time()+60,'submission':'human'}
        def ready():
            deadline=time.monotonic()+2
            while c.inflight and time.monotonic()<deadline:
                time.sleep(.01);self.app.processEvents()
            self.assertFalse(c.inflight)
        try:
            with patch('desktop.app.call',return_value=draft) as rpc:
                c.manualDraft('fixture-draft');ready()
                c.copyDraft();ready()
                self.assertEqual(self.app.clipboard().text(),draft['text'])
                self.assertEqual(rpc.call_count,2)
                self.assertEqual(rpc.call_args.args[1],'control.draft');self.assertTrue(rpc.call_args.kwargs['owner'])
            with patch('desktop.app.call',return_value={**draft,'text':'Changed unreviewed text'}):
                c.copyDraft();ready()
                self.assertEqual(self.app.clipboard().text(),draft['text'])
                self.assertFalse(c.manual)
        finally:self.app.clipboard().clear();self.dispose(c,e,w)
    def test_manual_body_clears_on_expiry_revocation_and_disconnect(self):
        import time
        c,e,w=self.create()
        try:
            c._manual={'job_id':'synthetic','text':'Synthetic private draft','expires':time.time()-1}
            c.accept({'name':'refresh','value':{'drafts':[]},'error':None});self.assertFalse(c.manual)
            c._manual={'job_id':'synthetic','text':'Synthetic private draft','expires':time.time()+60}
            c.accept({'name':'stop','value':{'revoked':True},'error':None});self.assertFalse(c.manual)
            c._manual={'job_id':'synthetic','text':'Synthetic private draft','expires':time.time()+60}
            c.accept({'name':'refresh','value':None,'error':'local_broker_unavailable'});self.assertFalse(c.manual)
        finally:self.dispose(c,e,w)
