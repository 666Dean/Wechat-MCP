# SPDX-License-Identifier: MIT
"""Actual Qt/QML fixture layout, capability labels, themes and keyboard navigation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
import unittest
from pathlib import Path
try:
    from PySide6.QtCore import QUrl,QCoreApplication,QEvent,Qt,QObject
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
                    for page in range(7):
                        w.setProperty('page',page);QTest.qWait(35)
                        image=w.grabWindow();self.assertFalse(image.isNull())
                        footer=w.findChild(QObject,'statusBar')
                        viewport=w.findChild(QObject,'contentViewport')
                        self.assertIsNotNone(footer);self.assertIsNotNone(viewport)
                        self.assertEqual(round(footer.property('height')),32)
                        self.assertLessEqual(viewport.property('y')+viewport.property('height'),footer.property('y')+1)
                        self.assertFalse(w.property('connected'));self.assertFalse(w.property('sendAvailable'))
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
                self.assertFalse(w.grabWindow().isNull())
            finally:self.dispose(c,e,w)
