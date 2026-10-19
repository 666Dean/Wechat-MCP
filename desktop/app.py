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
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl, QEvent, QCoreApplication, Qt
from PySide6.QtGui import QIcon,QDesktopServices
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QFileDialog
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from axr.aet import AXRError
from axr_integration.broker import call as legacy_call, read_connection
from .authority_client import call as authority_call,installed as authority_installed
from .codex_config import snippet,native_snippet,install,restore
from .owner_agent import OwnerAgentBridge

def call(*args,**kwargs):
    return (authority_call if authority_installed() else legacy_call)(*args,**kwargs)


class Controller(QObject):
    assistantChanged=Signal();threadsChanged=Signal();changed=Signal();detailChanged=Signal();manualChanged=Signal();noticeChanged=Signal();completed=Signal(object)
    agentEvent=Signal(object);agentApprovalChanged=Signal()
    def __init__(self,state,helper=None,fixture=False,fixture_case="empty"):
        super().__init__();self.state=state;self.helper=helper;self.fixture=fixture;self.fixture_case=fixture_case
        self._data={'connected':False,'jobs':[],'drafts':[],'conversations':[],'grants':[],'summaries':[]}
        self._assistant={'thread_id':'','thread_title':'','persona':'','style':'简洁、自然、直接；不编造事实。','attribution':True};self._threads=[];self._threads_cursor=None
        self._preview={};self._manual={};self._detail='';self._notice='连接本地服务，开始你的工作台。';self.selected=None;self.config_review=None;self.config_backup=None
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=2);self.inflight=set();self.broker_process=None;self.worker_process=None;self.worker_job=None
        self.completed.connect(self.accept)
        self._agent_approval={};self._agent_approvals=[];self.agent_bridge=OwnerAgentBridge(self.agentEvent.emit);self.agentEvent.connect(self.acceptAgent)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(10000)
        if not self.fixture and authority_installed():QTimer.singleShot(0,self.start)
        self.refresh()
    @Property('QVariantMap',notify=assistantChanged)
    def assistant(self):return self._assistant
    @Property('QVariantList',notify=threadsChanged)
    def codexThreads(self):return self._threads
    @Property('QVariantMap',notify=agentApprovalChanged)
    def agentApproval(self):return self._agent_approval
    @Slot(bool)
    def setForeground(self,foreground):self.timer.setInterval(10000 if foreground else 30000)
    @Slot(object)
    def acceptAgent(self,event):
        if event['kind']=='approval':
            self._agent_approvals.append(event)
            if len(self._agent_approvals)==1:self._agent_approval=event;self.agentApprovalChanged.emit()
            return
        self._agent_approvals=[];self._agent_approval={};self.agentApprovalChanged.emit()
        payload={k:v for k,v in event.items() if k!='kind'}
        self.run('owner_finish',lambda:call(self.state,'control.finish_owner_task',(payload,),owner=True))
    @Slot(bool)
    def decideAgent(self,approved):
        self.agent_bridge.decide(self._agent_approval.get('request_key'),approved)
        if self._agent_approvals:self._agent_approvals.pop(0)
        self._agent_approval=self._agent_approvals[0] if self._agent_approvals else {}
        QTimer.singleShot(0,self.agentApprovalChanged.emit)
    @Slot(str)
    def openSystemPermission(self,kind):
        if self.fixture or sys.platform!='darwin':return
        pane={'database':'Privacy_AllFiles','accessibility':'Privacy_Accessibility'}.get(kind)
        if pane:
            from axr.platform.macos_application import register_bundle
            try:register_bundle(Path('/Library/Application Support/Stellaria AXR/AXR Authority.app'))
            except AXRError:
                self._notice='应用尚未完成安装，无法准备系统权限入口。';self.noticeChanged.emit();return
            QDesktopServices.openUrl(QUrl('x-apple.systempreferences:com.apple.preference.security?'+pane))
    @Slot()
    def loadAssistant(self):
        if not self.fixture:self.run('assistant_load',lambda:call(self.state,'control.assistant_settings',owner=True))
    @Slot()
    def loadThreads(self):
        if not self.fixture:self.run('threads',lambda:call(self.state,'control.codex_threads',owner=True))
    @Slot()
    def loadMoreThreads(self):
        if not self.fixture and self._threads_cursor:
            self.run('threads_more',lambda:call(self.state,'control.codex_threads',(self._threads_cursor,),owner=True))
    @Slot('QVariantMap')
    def saveAssistant(self,value):
        if not self.fixture:self.run('assistant_save',lambda:call(self.state,'control.save_assistant_settings',(dict(value),),owner=True))
    @Slot()
    def installHooks(self):
        if not self.fixture:self.run('hooks',lambda:call(self.state,'control.install_hooks',owner=True))
    @Slot(str)
    def approveAuthorization(self,key):
        if not self.fixture:self.run('authorization',lambda:call(self.state,'control.approve_authorization',(key,),owner=True,timeout=90))
    @Slot()
    def importPersona(self):
        if self.fixture:return
        path,_=QFileDialog.getOpenFileName(None,'导入助理人设','', '文本 (*.txt *.md)')
        if not path:return
        source=Path(path)
        try:
            if source.is_symlink() or source.stat().st_size>12000:
                self._notice='人设文件应为 12KB 以内的纯文本。';self.noticeChanged.emit();return
            self._assistant['persona']=source.read_text(encoding='utf8')
        except (UnicodeError,OSError):
            self._notice='无法读取此人设文件，请选择 UTF-8 纯文本。';self.noticeChanged.emit();return
        self.assistantChanged.emit()

    @Property('QVariantMap',notify=changed)
    def data(self):return self._data
    @Property('QVariantMap',notify=detailChanged)
    def preview(self):return self._preview
    @Property('QVariantMap',notify=manualChanged)
    def manual(self):return self._manual
    @Property(bool,notify=changed)
    def restoreAvailable(self):return self.config_backup is not None
    @Property(str,notify=detailChanged)
    def detail(self):return self._detail
    @Property(str,notify=noticeChanged)
    def notice(self):return self._notice
    def run(self,name,fn):
        if name in self.inflight:return
        self.inflight.add(name)
        self._data['loading']=True;self._data['automatic_pending']='automatic' in self.inflight;self.changed.emit()
        def work():
            try:value=fn();error=None
            except Exception as exc:value=None;error=str(exc) if isinstance(exc,AXRError) else '操作未完成，请检查本地服务。'
            self.completed.emit({'name':name,'value':value,'error':error})
        self.pool.submit(work)
    @Slot(object)
    def accept(self,result):
        self.inflight.discard(result['name'])
        self._data['loading']=bool(self.inflight);self._data['automatic_pending']='automatic' in self.inflight
        if result['error']:
            self._notice={'owner_secret_not_provisioned':'需要完成本机所有者初始化。',
                'owner_state_unavailable':'需要完成本机授权。','local_broker_unavailable':'本地服务未连接，请启动后重试。',
                'account_or_journal_busy':'执行服务正被使用，请先完成服务交接。',
                'send_backend_not_qualified':'当前平台暂不支持自动发送。',
                'incoming_isolated_authority_required':'自动回复需要完成安全服务升级，当前权限未开启。',
                'authority_store_owner_migration_required':'请先在本机完成安全升级，旧授权将被撤销。',
                'security2_application_authority_bridge_required':'安全服务尚未完成安装，请保持自动回复关闭。',
                'automatic_reply_helper_required':'请更新本地服务以启用自动回复。',
                'automatic_reply_scope_invalid':'请选择至少两个已绑定私聊，或全部可用私聊。',
                'automatic_reply_already_active':'自动回复已经开启，请先停止当前会话。',
                'wechat_full_disk_access_required':'请先在系统设置中允许 AXR Authority 完全磁盘访问，再开启服务；尚未请求身份认证。',
                'wechat_accessibility_required':'请先允许 AXR Authority 使用“设备控制和数据访问”（旧版名为“辅助功能”），再开启自动回复；尚未请求身份认证。',
                'wechat_main_window_unavailable':'请打开微信主窗口后重试；尚未请求身份认证。',
                'runtime_account_witness_changed':'当前微信账号与已绑定账号不一致，请核对登录账号；尚未请求身份认证。',
                'wechat_owner_review_expired_or_changed':'本次确认已过期或范围发生变化，未开启服务。请核对范围后重新开启。',
                'wechat_self_agent_binding_required':'请先选择并保存 Codex 对话，并在回复范围中包含本人私聊。',
                'wechat_initialization_approval_changed':'设置与已批准内容不一致，已保留进度。请先核对配置，避免重复认证。',
                'wechat_initialization_recovery_requires_review':'初始化已有运行记录，不能按空事务接续。请保留数据并检查服务状态。',
                'independent_authority_control_unavailable':'本地安全服务未连接，请先启动服务；无需重新登录微信。',
                'unlimited_requires_bound_codex_thread':'请先选择并保存固定 Codex 对话，再开启不限模式。',
                'stop_automatic_before_settings_change':'请先停止自动回复，再更改助理偏好。',
                'authority_missing_expired_revoked_or_exhausted':'当前操作需要授权，或原授权已到期。',
                'owner_os_authentication_failed':'系统身份认证未完成，本次操作未获准。',
                'owner_policy_changed_restart_required':'权限配置已更新，请重新连接本地服务。'}.get(result['error'],'操作未完成，请核对授权与本地服务。')
            if result['error'].startswith('owner_os_authentication_failed'):
                self._notice=('系统取消了身份认证，请保持认证窗口在前台后重试。'
                    if result['error']=='owner_os_authentication_failed:owner_auth_denied:os_error_-4' else
                    '身份认证已超时，请重新发起。' if ':owner_auth_timed_out' in result['error'] else
                    '暂时无法进行本机身份认证，请检查系统状态。' if ':owner_auth_unavailable' in result['error'] else
                    '系统身份认证未完成，本次操作未获准。')
            self.noticeChanged.emit()
            if result['name']=='refresh':
                self._data.update(connected=False,jobs=[],drafts=[],summaries=[],grants=[])
            if result['name'] in {'refresh','manual_draft','copy_draft'}:
                self._manual={};self.manualChanged.emit()
            self.changed.emit()
            return
        value=result['value'];name=result['name']
        if name=='assistant_load':
            self._assistant=value;self.assistantChanged.emit();return
        if name in ('threads','threads_more'):
            self._threads=(self._threads if name=='threads_more' else [])+value['threads'];self._threads_cursor=value.get('next_cursor');self.threadsChanged.emit();return
        if name=='assistant_save':self.loadAssistant()
        if name=='owner_claim':
            if value.get('ready'):self.agent_bridge.start(value)
            return
        if name=='stop':
            self._manual={};self._preview={};self.manualChanged.emit();self.detailChanged.emit()
        if name=='install':self.changed.emit()
        if name=='refresh':
            self._data=value;self._data.update(connected=True,loading=bool(self.inflight),last_sync=time.strftime('%H:%M:%S'),
                automatic_pending='automatic' in self.inflight,worker_state='running' if self.worker_process is not None and self.worker_process.poll() is None else 'stopped')
            if value.get('owner_agent_enabled'):
                binding=value.get('thread_binding',{})
                running=bool(self.agent_bridge.thread and self.agent_bridge.thread.is_alive())
                if running and binding.get('state') in ('busy','paused'):self.agent_bridge.stop()
                elif not running and binding.get('state')=='idle' and not self.fixture:
                    self.run('owner_claim',lambda:call(self.state,'control.claim_owner_task',owner=True))
            elif self.agent_bridge.thread and self.agent_bridge.thread.is_alive():self.agent_bridge.stop()
            if self._manual and (self._manual.get('expires',0)<=time.time() or
                    not any(d['job_id']==self._manual.get('job_id') for d in value.get('drafts',[]))):
                self._manual={};self.manualChanged.emit()
            self.changed.emit()
        elif name=='manual_draft':
            self._manual=value;self.manualChanged.emit()
        elif name=='copy_draft':
            # Revalidate the sealed draft through the owner broker immediately
            # before explicit copying. Never copy a changed/unreviewed payload.
            if (value.get('expires',0)<=time.time() or any(value.get(k)!=self._manual.get(k)
                    for k in ('job_id','conversation_id','text'))):
                self._manual={};self.manualChanged.emit()
                self._notice='草稿已变化或到期，请重新查看。';self.noticeChanged.emit();return
            QApplication.clipboard().setText(value['text'])
        elif name=='manual_observe':
            self._notice='已找到与你提交的草稿一致的发出记录。' if value.get('database_record_observed') else '尚未找到对应发出记录，请稍后核对。'
            self.noticeChanged.emit();return
        elif name in {'review','draft','config_preview','connection'}:
            self._preview=value;self._detail=json.dumps(value,ensure_ascii=False,indent=2);self.detailChanged.emit()
            if name=='review' and 'intent' in value:self.selected=(value['intent']['execution_id'],value['seal'])
        elif name=='summaries':self._data['summaries']=value['summaries'];self.changed.emit()
        self._notice={'refresh':'已同步。','approve':'已批准这一次操作。',
            'stop':'已撤销授权并停止监听。','install':'Codex MCP 配置已安装；权限仍由你单独授予。',
            'restore':'已恢复安装前的 Codex 设置。','start':'本地服务已启动。','execute':'请查看处理结果。','agent':'助理已启动，等待授权范围内的新任务。','grant':'已授权此会话的本地读取，有效期 15 分钟。','cache':'文件目录已更新，请重新授权。',
            'automatic':'自动回复已开启。微信需要保持登录且可见。','automatic_stop':'自动回复已停止，当前发送权限已撤销。',
            'assistant_save':'助理偏好已保存，下次开启服务时生效。','hooks':'连接事件已配置，请在 Codex 的 /hooks 审核并信任。',
            'authorization':'目标授权已更新，可以继续原任务。',
            'copy_draft':'已复制，请核对微信目标后由你发送。','manual_draft':'请核对收件人与回复内容。'}.get(name,'操作已完成。')
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
                label='项目讨论 · Product & Design · 产品规划与文档协作事项'
                self._data['conversations']=[{'conversation_id':'fixture-chat','display_name':label,'data_class':'personal'}]
                self._data['jobs']=[{'id':'fixture-job-'+str(i),'state':state,'operation':operation,'target':label,
                    'created':now-i*90,'expires':now+900} for i,(state,operation) in enumerate([
                    ('AwaitingApproval','disclosure.send'),('Executing','messages.read'),('Verifying','files.read'),
                    ('Completed','reply.prepare'),('Unknown','messages.send'),('FailedSafe','files.read')])]
                self._data['drafts']=[{'job_id':'fixture-draft','display_name':label,'expires':now+600}]
                self._manual={'job_id':'fixture-draft','conversation_id':'fixture-chat','display_name':label,
                    'text':'这是合成界面样本。\n\n建议先确认会议时间，再整理文档更新与待办事项。\n\n— Codex · AI 助理',
                    'expires':now+600,'submission':'human'};self.manualChanged.emit()
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
            if authority_installed():
                subprocess.run(['/bin/launchctl','kickstart','gui/'+str(os.getuid())+'/org.stellaria.axr.authority'],check=True,capture_output=True)
                for _ in range(30):
                    try:return authority_call(self.state,'status')
                    except AXRError:time.sleep(.2)
                raise AXRError('independent_authority_control_unavailable')
            try:read_connection(self.state);call(self.state,'status');return {'already_running':True}
            except Exception:pass
            if self.broker_process is not None and self.broker_process.poll() is None:raise AXRError('broker_start_pending')
            cmd=[sys.executable,'-m','axr_integration.broker','--state',str(Path(self.state).resolve()),'--listener']
            if self.helper:
                cmd+=['--helper',str(Path(self.helper).resolve())]
                chat=Path(self.helper).resolve().parent.parent/'wechat-chat-navigation-experimental'
                if chat.is_file():cmd+=['--chat-helper',str(chat)]
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
    @Slot(str)
    def manualDraft(self,jid):
        self._manual={};self.manualChanged.emit()
        if not self.fixture:self.run('manual_draft',lambda:call(self.state,'control.draft',(jid,),owner=True))
    @Slot()
    def copyDraft(self):
        if self.fixture or not self._manual:return
        jid=self._manual['job_id']
        self.run('copy_draft',lambda:call(self.state,'control.draft',(jid,),owner=True))
    @Slot()
    def observeManual(self):
        if self.fixture or not self._manual:return
        jid=self._manual['job_id']
        self.run('manual_observe',lambda:call(self.state,'observe_manual_reply',(jid,)))
    @Slot()
    def stop(self):
        if self.fixture:return
        self.agent_bridge.stop()
        self.run('stop',lambda:call(self.state,'control.revoke_all',owner=True))
    @Slot('QVariantList',int,int,bool,bool)
    def startAutomatic(self,targets,minutes,replies,overwrite=False,self_agent=False):
        if self.fixture:return
        if overwrite and not authority_installed():
            self._notice='强制覆盖需要独立安全服务。';self.noticeChanged.emit();return
        arguments=(list(targets),minutes*60,replies,overwrite,self_agent) if authority_installed() else (list(targets),minutes*60,replies)
        self.run('automatic',lambda:call(self.state,'control.start_automatic',arguments,owner=True,timeout=180))
    @Slot()
    def stopAutomatic(self):
        if self.fixture:return
        self.agent_bridge.stop()
        self.run('automatic_stop',lambda:call(self.state,'control.stop_automatic',owner=True))
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
        value=native_snippet() if authority_installed() else snippet(sys.executable,Path(__file__).resolve().parent.parent/'server.py',self.state)
        self.config_review=(path,value,hashlib.sha256(raw).hexdigest())
        self._detail=value;self.detailChanged.emit();self._notice='确认后连接 Codex。现有设置会保留。';self.noticeChanged.emit()
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
                    params=(StdioServerParameters(command='/Library/Application Support/Stellaria AXR/AXR MCP.app/Contents/MacOS/axr-frontend',args=['--mcp'])
                        if authority_installed() else StdioServerParameters(command=sys.executable,args=[str(Path(__file__).resolve().parent.parent/'server.py'),
                        '--axr-state',str(Path(self.state).resolve()),'--broker']))
                    async with stdio_client(params) as (r,w):
                        async with ClientSession(r,w) as c:
                            await c.initialize();tools=await c.list_tools();status=await c.call_tool('wechat_status',{})
                            if status.is_error:raise AXRError('mcp_status_failed')
                            return {'tool_count':len(tools.tools),'protocol_verified':True}
            return asyncio.run(test())
        self.run('connection',handshake)
    def close(self):
        self.agent_bridge.stop()
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
    parser.add_argument('--page',type=int,choices=range(10),default=0)
    parser.add_argument('--theme',choices=['light','dark'],default='light')
    parser.add_argument('--fixture-case',choices=['empty','content','loading','error'],default='empty')
    args=parser.parse_args()
    if args.capture and not args.fixture:parser.error('Screenshots are supported only for the synthetic fixture')
    QQuickStyle.setStyle('Basic')
    app=QApplication(sys.argv);app.setApplicationName('WeChat MCP Desktop');app.setOrganizationName('Stellaria Studio')
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark if args.theme=='dark' else Qt.ColorScheme.Light)
    controller=Controller(args.state,args.helper,args.fixture,args.fixture_case)
    engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('owner',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('Main.qml'))))
    if not engine.rootObjects():raise SystemExit(1)
    window=engine.rootObjects()[0]
    app.applicationStateChanged.connect(lambda state:controller.setForeground(state==Qt.ApplicationActive))
    window.setWidth(args.width);window.setHeight(args.height);window.setProperty('page',args.page);window.setProperty('darkMode',args.theme=='dark')
    window.darkModeChanged.connect(lambda:app.styleHints().setColorScheme(
        Qt.ColorScheme.Dark if window.property('darkMode') else Qt.ColorScheme.Light))
    tray=QSystemTrayIcon(QIcon(str(Path(__file__).with_name('icon.svg'))),app)
    menu=QMenu();menu.addAction('打开工作台',lambda:(window.show(),window.raise_(),window.requestActivate()))
    menu.addAction('撤销全部授权',lambda:window.requestRevoke());menu.addSeparator();menu.addAction('退出界面',app.quit)
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
