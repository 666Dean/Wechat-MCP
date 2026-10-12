# SPDX-License-Identifier: MIT
"""Qt Quick owner app. No independent Service, journal recovery, or model calls."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl, QEvent, QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QFileDialog
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from axr.aet import AXRError
from axr_integration.broker import call, read_connection
from .codex_config import snippet,install,restore


class Controller(QObject):
    changed=Signal();detailChanged=Signal();noticeChanged=Signal();completed=Signal(object)
    def __init__(self,state,helper=None,fixture=False,fixture_case="empty"):
        super().__init__();self.state=state;self.helper=helper;self.fixture=fixture;self.fixture_case=fixture_case
        self._data={'connected':False,'jobs':[],'drafts':[],'conversations':[],'grants':[],'summaries':[]}
        self._preview={};self._detail='';self._notice='连接本地服务，开始你的工作台。';self.selected=None;self.config_review=None;self.config_backup=None
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=2);self.inflight=set();self.broker_process=None;self.worker_process=None;self.worker_job=None
        self.completed.connect(self.accept)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(5000)
        self.refresh()
    @Property('QVariantMap',notify=changed)
    def data(self):return self._data
    @Property('QVariantMap',notify=detailChanged)
    def preview(self):return self._preview
    @Property(str,notify=detailChanged)
    def detail(self):return self._detail
    @Property(str,notify=noticeChanged)
    def notice(self):return self._notice
    def run(self,name,fn):
        if name in self.inflight:return
        self.inflight.add(name)
        self._data['loading']=True;self.changed.emit()
        def work():
            try:value=fn();error=None
            except Exception as exc:value=None;error=str(exc) if isinstance(exc,AXRError) else '操作未完成，请检查本地服务。'
            self.completed.emit({'name':name,'value':value,'error':error})
        self.pool.submit(work)
    @Slot(object)
    def accept(self,result):
        self.inflight.discard(result['name'])
        self._data['loading']=bool(self.inflight)
        if result['error']:
            self._notice={'owner_secret_not_provisioned':'需要完成本机所有者初始化。',
                'owner_state_unavailable':'需要完成本机授权。','local_broker_unavailable':'本地服务未连接，请启动后重试。',
                'account_or_journal_busy':'执行服务正被使用，请先完成服务交接。',
                'send_backend_not_qualified':'当前平台暂不支持自动发送。',
                'authority_missing_expired_revoked_or_exhausted':'当前操作需要授权，或原授权已到期。',
                'owner_os_authentication_failed':'系统身份认证未完成，本次操作未获准。',
                'owner_policy_changed_restart_required':'权限配置已更新，请重新连接本地服务。'}.get(result['error'],'操作未完成，请核对授权与本地服务。')
            self.noticeChanged.emit()
            if result['name']=='refresh':
                self._data.update(connected=False,jobs=[],drafts=[],summaries=[],grants=[])
            self.changed.emit()
            return
        value=result['value'];name=result['name']
        if name=='refresh':
            self._data=value;self._data.update(connected=True,loading=bool(self.inflight),last_sync=time.strftime('%H:%M:%S'),
                worker_state='running' if self.worker_process is not None and self.worker_process.poll() is None else 'stopped')
            self.changed.emit()
        elif name in {'review','draft','config_preview','connection'}:
            self._preview=value;self._detail=json.dumps(value,ensure_ascii=False,indent=2);self.detailChanged.emit()
            if name=='review' and 'intent' in value:self.selected=(value['intent']['execution_id'],value['seal'])
        elif name=='summaries':self._data['summaries']=value['summaries'];self.changed.emit()
        self._notice={'refresh':'本地状态已更新。','approve':'系统认证通过，精确意图已批准。',
            'stop':'已撤销授权并停止监听。','install':'Codex MCP 配置已安装；权限仍由你单独授予。',
            'restore':'已恢复安装前的 Codex 配置。','start':'本地服务已启动。','execute':'执行完成，请查看实际回执。','agent':'10 分钟草稿 Agent 已启动；等待已授权的任务。','grant':'已建立 15 分钟本地读取授权；模型披露仍需精确批准。','cache':'缓存范围已更新，之前的权限已撤销。'}.get(name,'操作已完成。')
        self.noticeChanged.emit()
    @Slot()
    def refresh(self):
        if self.fixture:
            self._data={'connected':False,'status':{'audit_valid':True,'policy_version':1,'listener':{'listen':False,'wake_agent':False,'auto_execute':False},
                'platform':{'mode':'synthetic_preview','send_available':False}},'jobs':[], 'drafts':[], 'grants':[],
                'summaries':[], 'conversations':[], 'attachments':{'enabled':False},'scope':'synthetic_preview'}
            now=time.time()
            self._data.update(last_sync='—',loading=self.fixture_case=='loading',worker_state='stopped')
            if self.fixture_case=='content':
                label='项目工作群 · Product / Engineering · 超长联系人名称与中英文混排验证'
                self._data['conversations']=[{'conversation_id':'fixture-chat','display_name':label,'data_class':'personal'}]
                self._data['jobs']=[{'id':'fixture-job-'+str(i),'state':state,'operation':operation,'target':label,
                    'created':now-i*90,'expires':now+900} for i,(state,operation) in enumerate([
                    ('AwaitingApproval','disclosure.send'),('Executing','messages.read'),('Verifying','files.read'),
                    ('Completed','reply.prepare'),('Unknown','messages.send'),('FailedSafe','files.read')])]
                self._data['drafts']=[{'job_id':'fixture-draft','display_name':label,'expires':now+600}]
                self._data['grants']=[{'conversation_id':'fixture-chat','operations':['messages.read','reply.prepare'],
                    'expires':now+600,'remaining':42,'destinations':[],'exact_intent':False}]
                self._data['summaries']=[{'summary':'合成设计样本：讨论 Meeting Agenda 与文档更新，建议先核对时间，再准备回复。此文本不是微信数据。',
                    'text_records':3,'has_more':True}]
            elif self.fixture_case=='error':
                self._notice='服务连接中断。请检查本地服务后重试。';self.noticeChanged.emit()
            self.changed.emit();return
        self.run('refresh',lambda:call(self.state,'control.snapshot',owner=True))
    @Slot()
    def start(self):
        if self.fixture:return
        def launch():
            try:read_connection(self.state);call(self.state,'status');return {'already_running':True}
            except Exception:pass
            if self.broker_process is not None and self.broker_process.poll() is None:raise AXRError('broker_start_pending')
            cmd=[sys.executable,'-m','axr_integration.broker','--state',str(Path(self.state).resolve()),'--listener']
            if self.helper:cmd+=['--helper',str(Path(self.helper).resolve())]
            self.broker_process=subprocess.Popen(cmd,cwd=str(Path(__file__).resolve().parent.parent),stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(60):
                if self.broker_process.poll() is not None:raise AXRError('broker_start_failed')
                try:call(self.state,'status');return {'running':True}
                except Exception:time.sleep(.15)
            raise AXRError('broker_start_timeout')
        self.run('start',launch)
    @Slot(str)
    def review(self,jid):
        if self.fixture:return
        self.reviewed_job=jid;self.selected=None;self._preview={};self.detailChanged.emit()
        self.run('review',lambda:call(self.state,'control.review',(jid,),owner=True))
    @Slot()
    def approve(self):
        if not self.selected or self.fixture:return
        seal=self.selected[1];jid=self.reviewed_job
        self.run('approve',lambda:call(self.state,'control.approve',(jid,seal),owner=True,timeout=90))
    @Slot(str)
    def execute(self,jid):
        if self.fixture:return
        self.run('execute',lambda:call(self.state,'execute',(jid,)))
    @Slot(str)
    def draft(self,jid):
        self.selected=None;self._preview={};self.detailChanged.emit()
        if self.fixture:return
        self.run('draft',lambda:call(self.state,'control.draft',(jid,),owner=True))
    @Slot()
    def stop(self):
        if self.fixture:return
        self.run('stop',lambda:call(self.state,'control.revoke_all',owner=True))
    @Slot()
    def startAgent(self):
        if self.fixture:return
        def launch():
            if self.worker_process is not None and self.worker_process.poll() is None:raise AXRError('reply_worker_already_running')
            call(self.state,'status')
            root=Path(__file__).resolve().parent.parent
            self.worker_process=subprocess.Popen([sys.executable,str(root/'scripts/run_codex_manual.py'),
                '--state',str(Path(self.state).resolve()),'--broker','--duration','600'],cwd=str(root),
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if os.name=='nt':
                from axr.platform.windows_job import bind_job
                self.worker_job=bind_job(self.worker_process)
            return {'worker_started':True,'ttl_seconds':600,'submission':'human','model_read_requires_exact_approval':True}
        self.run('agent',launch)
    @Slot(str)
    def grantLocal(self,cid):
        if self.fixture:return
        self.run('grant',lambda:call(self.state,'control.grant_local',(cid,900),owner=True,timeout=90))
    @Slot()
    def configureCache(self):
        if self.fixture:return
        selected=QFileDialog.getExistingDirectory(None,'选择微信本地文件缓存目录')
        if selected:self.run('cache',lambda:call(self.state,'control.configure_cache',(str(Path(selected).resolve()),),owner=True,timeout=90))
    @Slot(str)
    def requestTask(self,cid):
        if self.fixture:return
        self.run('task',lambda:call(self.state,'request_task',(cid,int(time.time())-86400,6)))
    @Slot()
    def summaries(self):
        if self.fixture:return
        self.run('summaries',lambda:call(self.state,'control.summaries',owner=True))
    @Slot()
    def configPreview(self):
        self.selected=None
        path=Path.home()/'.codex/config.toml'
        raw=path.read_bytes() if path.exists() else b''
        value=snippet(sys.executable,Path(__file__).resolve().parent.parent/'server.py',self.state)
        self.config_review=(path,value,hashlib.sha256(raw).hexdigest())
        self._detail=value;self.detailChanged.emit();self._notice='请核对下面的 MCP 配置，确认后安装。';self.noticeChanged.emit()
    @Slot()
    def installConfig(self):
        if not self.config_review or self.fixture:return
        path,value,sha=self.config_review
        def commit():
            self.config_backup=install(path,value,sha,Path(self.state)/'desktop-backups');return {'installed':True}
        self.run('install',commit)
    @Slot()
    def restoreConfig(self):
        if not self.config_backup or not self.config_review or self.fixture:return
        backup=dict(self.config_backup);path=self.config_review[0]
        self.run('restore',lambda:restore(path,backup['backup'],backup['installed_sha256']))
    @Slot()
    def testConnection(self):
        self.selected=None;self._preview={};self.detailChanged.emit()
        if self.fixture:return
        def handshake():
            import asyncio
            from mcp import ClientSession,StdioServerParameters
            from mcp.client.stdio import stdio_client
            async def test():
                async with asyncio.timeout(15):
                    params=StdioServerParameters(command=sys.executable,args=[str(Path(__file__).resolve().parent.parent/'server.py'),
                        '--axr-state',str(Path(self.state).resolve()),'--broker'])
                    async with stdio_client(params) as (r,w):
                        async with ClientSession(r,w) as c:
                            await c.initialize();tools=await c.list_tools();status=await c.call_tool('wechat_status',{})
                            if status.is_error:raise AXRError('mcp_status_failed')
                            return {'tool_count':len(tools.tools),'protocol_verified':True}
            return asyncio.run(test())
        self.run('connection',handshake)
    def close(self):
        if self.worker_process is not None and self.worker_process.poll() is None:self.worker_process.terminate()
        if self.worker_job is not None:self.worker_job.Close();self.worker_job=None
        self.timer.stop()
        try:self.timer.timeout.disconnect(self.refresh);self.completed.disconnect(self.accept)
        except RuntimeError:pass
        self.pool.shutdown(wait=False,cancel_futures=True)


def main():
    parser=argparse.ArgumentParser(description='WeChat MCP Desktop — Powered by Stellaria AXR')
    parser.add_argument('--state',default=str(Path.home()/'.wechat-axr'))
    parser.add_argument('--helper');parser.add_argument('--fixture',action='store_true')
    parser.add_argument('--capture',help='Synthetic fixture screenshot only')
    parser.add_argument('--exit-after',type=int)
    parser.add_argument('--width',type=int,default=1280);parser.add_argument('--height',type=int,default=800)
    parser.add_argument('--page',type=int,choices=range(7),default=0)
    parser.add_argument('--theme',choices=['light','dark'],default='light')
    parser.add_argument('--fixture-case',choices=['empty','content','loading','error'],default='empty')
    args=parser.parse_args()
    if args.capture and not args.fixture:parser.error('Screenshots are supported only for the synthetic fixture')
    QQuickStyle.setStyle('Basic')
    app=QApplication(sys.argv);app.setApplicationName('WeChat MCP Desktop');app.setOrganizationName('Stellaria Studio')
    controller=Controller(args.state,args.helper,args.fixture,args.fixture_case)
    engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('owner',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('Main.qml'))))
    if not engine.rootObjects():raise SystemExit(1)
    window=engine.rootObjects()[0]
    window.setWidth(args.width);window.setHeight(args.height);window.setProperty('page',args.page);window.setProperty('darkMode',args.theme=='dark')
    tray=QSystemTrayIcon(QIcon(str(Path(__file__).with_name('icon.svg'))),app)
    menu=QMenu();menu.addAction('打开工作台',lambda:(window.show(),window.raise_(),window.requestActivate()))
    menu.addAction('撤销全部授权',controller.stop);menu.addSeparator();menu.addAction('退出界面',app.quit)
    tray.setContextMenu(menu);tray.setToolTip('WeChat MCP Desktop');tray.show()
    if args.capture:
        def capture():
            window.grabWindow().save(str(Path(args.capture).resolve()));app.quit()
        QTimer.singleShot(1800,capture)
    if args.exit_after:QTimer.singleShot(args.exit_after*1000,app.quit)
    app.aboutToQuit.connect(controller.close)
    code=app.exec()
    engine.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    raise SystemExit(code)


if __name__=='__main__':main()
