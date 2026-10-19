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
                        self.assertEqual(round(footer.property('height')),0)
                        self.assertIsNotNone(self.visual(w,'connectionStatus'))
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

    def test_automatic_settings_scopes_and_stop_remain_accessible_during_auth(self):
        from unittest.mock import patch
        c,e,w=self.create();c.timer.stop()
        try:
            c._data.update(connected=True,scope='work_and_daily_assistance',status={'automatic_reply':{'active':False,'supported':True}},
                conversations=[{'conversation_id':'peer','display_name':'项目讨论 · Product & Design'},
                               {'conversation_id':'self','display_name':'本人'}])
            c.changed.emit();w.setProperty('page',6);QTest.qWait(40)
            menu=self.visual(w,'settingsAccessMenu');self.assertIsNotNone(menu)
            start=self.visual(w,'autoStart');stop=self.visual(w,'autoStop')
            self.assertTrue(start.isEnabled());self.assertFalse(stop.isEnabled())
            c._data['status']['permissions']={'database':False,'accessibility':True}
            c.changed.emit();QTest.qWait(20);self.assertFalse(start.isEnabled())
            c._data['status']['permissions']={'database':True,'accessibility':True}
            c._data['automatic_pending']=True;c.changed.emit();QTest.qWait(20)
            self.assertTrue(stop.isEnabled());c.fixture=False
            with patch.object(c,'run') as run:
                stop.forceActiveFocus();QTest.keyClick(w,Qt.Key_Return);QTest.qWait(20)
                run.assert_not_called()
                from PySide6.QtCore import QMetaObject
                dialog=w.findChild(QObject,'stopDialog');self.assertTrue(dialog.property('visible'))
                QMetaObject.invokeMethod(dialog,'accept');QTest.qWait(20)
                self.assertEqual(run.call_args.args[0],'automatic_stop')
            c.fixture=True
            c._data['status']={'owner_authorized':True,'automatic_reply':{'active':True,'targets':['peer','self'],'expires':None}}
            c.changed.emit();QTest.qWait(20)
            self.assertTrue(menu.isVisible());self.assertTrue(start.isEnabled());self.assertTrue(stop.isEnabled())
            self.assertEqual(w.allowance(None),'不限次数')
        finally:self.dispose(c,e,w)

    def test_full_access_requires_risk_confirmation_and_contact_search_is_paged(self):
        from unittest.mock import patch
        from PySide6.QtCore import QMetaObject
        c,e,w=self.create();c.timer.stop()
        try:
            c._data['conversations']=[{'conversation_id':'fixture-'+str(i),'display_name':'Contact '+str(i)} for i in range(3402)]
            c.changed.emit()
            with patch.object(c,'applyScope') as apply:
                w.openAccess(2);QTest.qWait(40)
                risk=w.findChild(QObject,'fullAccessRiskDialog');editor=w.findChild(QObject,'accessDialog')
                self.assertTrue(risk.property('visible'));self.assertFalse(editor.property('visible'));apply.assert_not_called()
                QMetaObject.invokeMethod(risk,'close');QTest.qWait(10);apply.assert_not_called()
                w.openAccess(1);QTest.qWait(40)
                self.assertTrue(editor.property('visible'))
                contacts=self.visual(w,'accessContactList');self.assertEqual(contacts.property('count'),30)
                search=self.visual(w,'accessSearch');search.setProperty('text','Contact 3401');QTest.qWait(40)
                self.assertEqual(contacts.property('count'),1)
                search.setProperty('text','no matching contact');QTest.qWait(20);self.assertEqual(contacts.property('count'),0)
        finally:self.dispose(c,e,w)

    def test_thread_list_is_readable_during_scope_but_cannot_rebind(self):
        c,e,w=self.create();c.timer.stop()
        try:
            c._data.update(connected=True,scope='work_and_daily_assistance',status={'owner_authorized':True,'automatic_reply':{'active':False}})
            c.changed.emit();w.setProperty('page',6);QTest.qWait(30)
            mode=self.visual(w,'replyModeStatus');self.assertIn('不自动发送',mode.property('text'))
            self.visual(w,'settingsPage').setProperty('section',1);QTest.qWait(30)
            self.assertTrue(self.visual(w,'loadThreads').isEnabled())
            c.accept({'name':'threads','value':{'threads':[{'id':'fixture-thread','title':'Synthetic task'}],'next_cursor':'more'},'error':None})
            QTest.qWait(20)
            self.assertTrue(self.visual(w,'threadSelector').isEnabled());self.assertTrue(self.visual(w,'moreThreads').isVisible())
            self.assertTrue(c.threadsHasMore)
            c.inflight.add('threads_more');c.changed.emit();QTest.qWait(20)
            self.assertFalse(self.visual(w,'loadThreads').isEnabled())
        finally:self.dispose(c,e,w)

    def test_model_reasoning_keyboard_and_rapid_project_navigation(self):
        c,e,w=self.create();c.timer.stop()
        try:
            c._models=[{'id':'synthetic-model','title':'Synthetic model','efforts':['low','medium','high'],'default_effort':'medium'}]
            c.modelsChanged.emit();QTest.qWait(30)
            picker=self.visual(w,'reasoningSelector');picker.forceActiveFocus();QTest.keyClick(w,Qt.Key_Space);QTest.qWait(30)
            popup=w.findChild(QObject,'reasoningPopup');self.assertTrue(popup.property('visible'))
            self.assertLessEqual(popup.property('width'),264)
            model=self.visual(w,'modelSelector');model.forceActiveFocus();QTest.keyClick(w,Qt.Key_Space);QTest.qWait(20)
            models=self.visual(w,'modelChoiceList');self.assertTrue(models.isVisible())
            QTest.keyClick(w,Qt.Key_Down);QTest.keyClick(w,Qt.Key_Return);QTest.qWait(30)
            self.assertEqual(picker.property('modelId'),'synthetic-model')
            self.assertFalse(models.isVisible())
            slider=self.visual(w,'reasoningSlider');slider.forceActiveFocus();QTest.keyClick(w,Qt.Key_Right);QTest.qWait(20)
            self.assertEqual(picker.property('value'),'high')
            QTest.keyClick(w,Qt.Key_Escape);QTest.qWait(20);self.assertFalse(popup.property('visible'))
            for page in [8,2,9,8,0,7,2,0]:
                nav=self.visual(w,'nav'+str(page));nav.forceActiveFocus();QTest.keyClick(w,Qt.Key_Return)
                QTest.qWait(12);self.assertEqual(w.property('page'),page)
            self.assertFalse(w.grabWindow().isNull())
        finally:self.dispose(c,e,w)

    def test_all_contacts_can_exclude_one_without_granting_or_losing_search(self):
        c,e,w=self.create();c.timer.stop()
        try:
            c._data['conversations']=[{'conversation_id':'fixture-'+str(i),'display_name':'Contact '+str(i)} for i in range(3402)]
            c.changed.emit();w.openAccess(1);QTest.qWait(30)
            editor=w.findChild(QObject,'accessDialog');editor.setProperty('allContacts',True)
            editor.toggleRecipient('fixture-8');QTest.qWait(20)
            self.assertFalse(editor.property('allContacts'))
            selected=editor.property('selectedIds').toVariant();self.assertEqual(len(selected),3401);self.assertNotIn('fixture-8',selected)
            self.visual(w,'accessSearch').setProperty('text','Contact 8');QTest.qWait(20)
            self.assertGreater(self.visual(w,'accessContactList').property('count'),0)
            editor.close();self.assertFalse(w.property('scopeActive'))
        finally:self.dispose(c,e,w)

    def test_composer_keeps_input_on_queue_failure_and_preserves_new_edits(self):
        from unittest.mock import patch
        c,e,w=self.create();c.timer.stop();c.fixture=False
        try:
            composer=self.visual(w,'chatComposer');composer.setProperty('text','Synthetic task')
            c._attachment={'name':'fixture.txt','text':'Synthetic reference'}
            with patch.object(c,'run'),patch.object(c,'refresh'):
                c.submitChat('Synthetic task','','')
                c.accept({'name':'chat_prompt','error':'local_broker_unavailable','value':None})
                self.assertEqual(composer.property('text'),'Synthetic task');self.assertTrue(c._attachment)
                c.submitChat('Synthetic task','','');composer.setProperty('text','New unsent edit')
                c.accept({'name':'chat_prompt','error':None,'value':{'job_id':'synthetic','state':'AwaitingAgent'}})
                self.assertEqual(composer.property('text'),'New unsent edit');self.assertFalse(c._attachment)
                c.submitChat('New unsent edit','','')
                c.accept({'name':'chat_prompt','error':None,'value':{'job_id':'synthetic-2','state':'AwaitingAgent'}})
                self.assertEqual(composer.property('text'),'')
        finally:self.dispose(c,e,w)

    def test_right_edge_menus_keep_all_choices_inside_window_on_resize(self):
        c,e,w=self.create();c.timer.stop()
        try:
            for width,height in [(1024,680),(1280,800),(1440,900)]:
                w.setWidth(width);w.setHeight(height);w.setProperty('page',6);QTest.qWait(35)
                menu=self.visual(w,'settingsAccessMenu');menu.forceActiveFocus();QTest.keyClick(w,Qt.Key_Space);QTest.qWait(35)
                popup=menu.findChild(QObject,'glassChoicePopup');self.assertTrue(popup.property('visible'))
                self.assertGreaterEqual(popup.property('height'),130)
                self.assertGreaterEqual(popup.property('x'),12);self.assertGreaterEqual(popup.property('y'),12)
                self.assertLessEqual(popup.property('x')+popup.property('width'),width-12)
                self.assertLessEqual(popup.property('y')+popup.property('height'),height-12)
                w.setWidth(width+60);QTest.qWait(30)
                self.assertLessEqual(popup.property('x')+popup.property('width'),w.width()-12)
                popup.close();w.setProperty('page',0);QTest.qWait(20)
                quick=self.visual(w,'quickAccessMenu');quick.forceActiveFocus();QTest.keyClick(w,Qt.Key_Space);QTest.qWait(25)
                popup=quick.findChild(QObject,'glassChoicePopup');self.assertGreaterEqual(popup.property('height'),130)
                self.assertGreaterEqual(popup.property('x'),12);self.assertLessEqual(popup.property('y')+popup.property('height'),height-12)
                popup.close()
        finally:self.dispose(c,e,w)

    def test_wrapped_messages_and_all_settings_categories_remain_scrollable(self):
        c,e,w=self.create();c.timer.stop()
        try:
            w.setWidth(1024);w.setHeight(680)
            c._data['owner_messages']=[{'id':'long-fixture','prompt':'Product 讨论与长任务描述 '*70,'answer':'Synthetic answer\n'*30,'state':'Completed'}]
            c.changed.emit();QTest.qWait(60)
            bubble=self.visual(w,'userMessageBubble');self.assertGreater(bubble.height(),40)
            self.assertLessEqual(bubble.width(),self.visual(w,'conversationTranscript').width())
            text=next(i for i in bubble.childItems() if i.metaObject().className().startswith('QQuickText'))
            self.assertLessEqual(text.y()+text.property('contentHeight'),bubble.height())
            w.setProperty('page',6);QTest.qWait(30)
            for section in range(3):
                category=self.visual(w,'settingsCategory'+str(section));category.forceActiveFocus();QTest.keyClick(w,Qt.Key_Space);QTest.qWait(30)
                self.assertEqual(self.visual(w,'settingsPage').property('section'),section)
                self.assertFalse(w.grabWindow().isNull())
        finally:self.dispose(c,e,w)
