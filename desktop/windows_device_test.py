# SPDX-License-Identifier: MIT
"""Read-only interactive diagnostics; never a substitute for System admission.

Only executable metadata and the existing name-free UIA structure operation are
used. No account database, control value, focus, input or owner key is accessed.
"""
import hashlib,json,os,platform,re,subprocess,sys
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,canonical


def _windows():
    import win32gui,win32process
    windows=[]
    def visit(window,unused):
        if not win32gui.IsWindowVisible(window):return
        _,pid=win32process.GetWindowThreadProcessId(window)
        try:identity=json.loads(native.process_identity(pid))
        except Exception:return
        image=Path(identity['image'])
        if image.name.lower() in ('wechat.exe','weixin.exe'):
            windows.append((window,pid,image,identity['user'],identity['birth']))
    win32gui.EnumWindows(visit,None)
    return windows


def _version(image):
    import win32api
    info=win32api.GetFileVersionInfo(str(image),'\\')
    return '.'.join(str(n) for field in ('FileVersionMS','FileVersionLS')
                    for n in (info[field]>>16,info[field]&65535))


def _sha(image):
    if image.is_symlink() or image.is_junction() or not image.is_file() or image.stat().st_size>512*1024**2:
        raise AXRError('device_test_executable_invalid')
    with image.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _installation():
    from scripts.windows_service import ServiceController
    result={'files_present':False,'verified':False,'configuration':False,'owner_initialized':False,
            'service_state':'Unknown','qualification_permit':False}
    root=Path(native.windows_installation_root())
    result['files_present']=(root/'axr-authority.exe').is_file()
    result['service_state']=ServiceController().status()['state']
    if not result['files_present']:return result
    native.verify_windows_installation(str(root));result['verified']=True
    from desktop.windows_lifecycle import installed_configuration
    config=installed_configuration()['deployment'];result['configuration']=True
    result['owner_initialized']=(Path(config['state'])/'policy.sealed.json').is_file()
    # Presence alone never asserts signature, expiry or current-subject validity.
    result['qualification_permit']=(Path(native.windows_data_root())/'windows-qualification.json').is_file()
    return result


def _structure(package,pin):
    from scripts.install_authority_windows import review,unredirected
    root=unredirected(package).resolve(strict=True);manifest=review(root)
    helper=root/'wechat-uia.exe'
    env={key:value for key,value in os.environ.items() if key.upper() in
         ('SYSTEMROOT','WINDIR','TEMP','TMP','SYSTEMDRIVE')}
    env['PATH']=str(root)+os.pathsep+str(Path(os.environ['SystemRoot'])/'System32')
    completed=subprocess.run([str(helper)],input=canonical({'op':'structure','executable_hash':pin})+b'\n',
        capture_output=True,timeout=25,cwd=root,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    if completed.returncode or len(completed.stdout)>262144:raise AXRError('device_test_structure_failed')
    value=json.loads(completed.stdout)
    if value.get('error'):raise AXRError('device_test_structure_unavailable')
    nodes=value.get('nodes')
    if value.get('text_redacted') is not True or type(nodes) is not list or not 1<=len(nodes)<=500:
        raise AXRError('device_test_structure_invalid')
    clean=[]
    for node in nodes:
        if type(node) is not dict:raise AXRError('device_test_structure_invalid')
        path=node.get('path');children=node.get('children');role=node.get('role')
        if (type(path) is not list or len(path)>16 or any(type(n) is not int or not 0<=n<500 for n in path)
            or type(children) is not int or not 0<=children<=500 or role not in ('Text','Edit','List','Button','Other')
            or set(node)!={'path','role','identifier','children'}):
            raise AXRError('device_test_structure_invalid')
        # Automation IDs are not needed for path preparation; never export them.
        clean.append({'path':path,'role':role,'children':children})
    # The native walk is preorder and can stop at either bound. An Edit seen
    # before an omitted branch does not establish that the tree is complete.
    paths=[tuple(node['path']) for node in clean]
    if paths[0]!=() or paths!=sorted(set(paths)):
        raise AXRError('device_test_structure_invalid')
    by_path={tuple(node['path']):node for node in clean}
    children_by_path={path:[] for path in paths}
    for path in paths[1:]:
        if path[:-1] not in by_path:raise AXRError('device_test_structure_invalid')
        children_by_path[path[:-1]].append(path[-1])
    depth_limited=False
    for path,node in by_path.items():
        indices=children_by_path[path]
        if indices!=list(range(len(indices))) or len(indices)>node['children']:
            raise AXRError('device_test_structure_invalid')
        if len(indices)<node['children']:
            if len(path)==16:depth_limited=True
            elif len(nodes)!=500:raise AXRError('device_test_structure_invalid')
    return {'state':'Observed','nodes':clean,'node_budget_reached':len(nodes)==500,
            'depth_budget_reached':depth_limited,
            'text_redacted':True,'helper_sha256':manifest['files']['wechat-uia.exe'],
            'component_revision':manifest['source_revision']}


def inspect_device(*,package=None,wechat_sha256=None):
    """Return metadata only, with explicit blockers; no tasks or retries.

    Structure is opt-in and requires both a reviewed local component package
    and the caller's exact executable hash. The result is an interactive-user
    observation and cannot establish cross-session, account or device authority.
    """
    if sys.platform!='win32':raise AXRError('windows_device_test_required')
    if (package is None)!=(wechat_sha256 is None):raise AXRError('device_test_package_and_pin_required')
    if wechat_sha256 is not None and (type(wechat_sha256) is not str or re.fullmatch('[0-9a-f]{64}',wechat_sha256) is None):
        raise AXRError('device_test_executable_pin_required')
    result={'version':2,'evidence':'interactive_metadata_only','wechat':{'window_count':0},
            'windows_version':platform.version(),'architecture':platform.machine(),
            'installation':{},'structure':{'state':'NotRequested'},'blockers':[],
            'content_read':False,'input_performed':False,'model_called':False,'send_invoked':False,
            'authorization_granted':False,'runtime_qualified':False,'retry':False}
    windows=_windows();result['wechat']['window_count']=len(windows)
    if len(windows)!=1:result['blockers'].append('wechat_window_missing_or_ambiguous')
    else:
        window,pid,image,owner,birth=windows[0]
        current=json.loads(native.process_identity(os.getpid()))['user']
        if owner!=current:result['blockers'].append('wechat_interactive_owner_mismatch')
        else:
            pin=_sha(image);result['wechat'].update(version=_version(image),executable_sha256=pin)
            if package is not None:
                if pin!=wechat_sha256:raise AXRError('device_test_executable_pin_changed')
                structure=_structure(package,pin)
                # The bounded operation is diagnostic only; reject a changed window/epoch.
                if _windows()!=windows or _sha(image)!=pin:raise AXRError('device_test_application_changed')
                result['structure']=structure
                if structure['node_budget_reached']:
                    result['blockers'].append('uia_structure_budget_reached')
                elif structure.get('depth_budget_reached'):
                    result['blockers'].append('uia_structure_depth_reached')
                elif not any(node['role']=='Edit' for node in structure['nodes']):
                    result['blockers'].append('uia_edit_controls_not_exposed')
    try:result['installation']=_installation()
    except Exception:result['blockers'].append('protected_installation_unavailable')
    installed=result['installation']
    if not installed.get('verified'):result['blockers'].append('protected_service_installation_required')
    if not installed.get('configuration'):result['blockers'].append('owner_configuration_required')
    if not installed.get('owner_initialized'):result['blockers'].append('owner_initialization_required')
    if installed.get('service_state')!='Stopped':result['blockers'].append('stopped_registered_service_required')
    if not installed.get('qualification_permit'):result['blockers'].append('signed_qualification_plan_required')
    result['state']='Blocked' if result['blockers'] else 'PrerequisitesObserved'
    return result


def describe_result(value):
    wechat=value['wechat'];installed=value['installation']
    lines=['微信窗口：'+str(wechat['window_count'])+' 个']
    if 'version' in wechat:lines.append('微信版本：'+wechat['version'])
    lines.append('受保护组件：'+('校验通过' if installed.get('verified') else '尚未安装或无法校验'))
    lines.append('本人初始化：'+('已发现状态文件，仍需正式校验' if installed.get('owner_initialized') else '尚未完成'))
    labels={'wechat_window_missing_or_ambiguous':'请保持一个微信主窗口可见',
            'wechat_interactive_owner_mismatch':'微信与当前用户不一致',
            'uia_structure_budget_reached':'控件数量超出本次检查范围',
            'uia_structure_depth_reached':'控件层级超出本次检查范围',
            'uia_edit_controls_not_exposed':'微信未暴露可用的输入控件',
            'protected_installation_unavailable':'无法校验受保护安装',
            'protected_service_installation_required':'请完成受保护组件安装',
            'owner_configuration_required':'请完成本人配置',
            'owner_initialization_required':'请完成本人初始化',
            'stopped_registered_service_required':'验收前需要已登记且停止的服务',
            'signed_qualification_plan_required':'验收前需要本机对应的已签署计划'}
    lines.extend(labels.get(code,'本机条件尚未核实') for code in value['blockers'])
    lines.append('仅检查本机元数据；未读取聊天、输入、发送或授予权限。')
    return '\n'.join(lines)
