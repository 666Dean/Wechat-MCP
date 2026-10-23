# SPDX-License-Identifier: MIT
"""Explicit Windows setup actions through a bounded, hash-bound UAC request.

No caller command, script, service account, installation target or output path
is accepted. Requests/results live only in the owner's fixed profile cache.
"""
import ctypes,hashlib,json,re,subprocess,sys,time,uuid
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,canonical
from axr.rooted import RootedDirectory

OPERATIONS=('install','update','initialize','recover','refresh','reconfigure','start','stop')

def profile_for_sid(sid):
    if re.fullmatch(r'S-1-5-21-\d+-\d+-\d+-\d+',sid) is None:raise AXRError('windows_setup_owner_invalid')
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'+'\\'+sid,
            access=winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
        value,kind=winreg.QueryValueEx(key,'ProfileImagePath')
    if kind not in (winreg.REG_SZ,winreg.REG_EXPAND_SZ) or type(value) is not str:raise AXRError('windows_setup_profile_unavailable')
    if value.startswith('%SystemDrive%'):
        buffer=ctypes.create_unicode_buffer(32768);length=ctypes.windll.kernel32.GetSystemDirectoryW(buffer,len(buffer))
        if not 0<length<len(buffer):raise AXRError('windows_setup_profile_unavailable')
        value=Path(buffer.value).drive+value[len('%SystemDrive%'):]
    path=Path(value)
    if not path.is_absolute() or path.drive.startswith('\\') or '%' in value or '..' in path.parts:raise AXRError('windows_setup_profile_unavailable')
    return path

def cache_root(sid):return profile_for_sid(sid)/'AppData/Local/Stellaria/WeChat MCP/setup'

def private_request_directory(path,sid):
    from scripts.install_authority_windows import unredirected
    path=unredirected(path);path.mkdir(parents=True,exist_ok=True);unredirected(path)
    import win32security
    descriptor=win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        'D:P(A;OICI;FA;;;'+sid+')(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)',1)
    win32security.SetNamedSecurityInfo(str(path),win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION|win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,None,descriptor.GetSecurityDescriptorDacl(),None)
    return path

def prepare_request(operation,payload):
    if operation not in OPERATIONS or type(payload) is not dict:raise AXRError('windows_setup_operation_invalid')
    owner=json.loads(native.process_identity(__import__('os').getpid()))['user']
    area=private_request_directory(cache_root(owner),owner)
    directory=private_request_directory(area/('setup-'+uuid.uuid4().hex),owner)
    value={'version':2,'operation':operation,'owner':owner,'nonce':uuid.uuid4().hex,'payload':payload}
    raw=canonical(value)
    if len(raw)>65536:raise AXRError('windows_setup_request_budget')
    rooted=RootedDirectory(directory)
    try:
        with rooted.parent('request.json') as (parent,name):rooted.replace_at(parent,name,raw,lambda:None)
    finally:rooted.close()
    return directory/'request.json',hashlib.sha256(raw).hexdigest(),value

def shell_execute(request,sha):
    from win32com.shell import shell,shellcon
    if getattr(sys,'frozen',False):arguments=['--windows-setup-request',str(request),'--request-sha',sha]
    else:arguments=['-I',str(Path(__file__).with_name('windows_admin_entry.py')),'--windows-setup-request',str(request),'--request-sha',sha]
    buffer=ctypes.create_unicode_buffer(32768);length=ctypes.windll.kernel32.GetSystemDirectoryW(buffer,len(buffer))
    if not 0<length<len(buffer):raise AXRError('windows_setup_launch_failed')
    # SEE_MASK_NOASYNC is absent from some supported pywin32 shellcon builds.
    return shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS|0x100,lpVerb='runas',
        lpFile=sys.executable,lpParameters=subprocess.list2cmdline(arguments),lpDirectory=buffer.value,nShow=0)['hProcess']

def invoke(operation,payload=None,*,timeout=420):
    request,sha,value=prepare_request(operation,payload or {})
    try:process=shell_execute(request,sha)
    except Exception as error:
        if getattr(error,'winerror',None)==1223:raise AXRError('windows_setup_cancelled') from None
        raise AXRError('windows_setup_launch_failed') from None
    import win32event,win32process,win32api
    deadline=time.monotonic()+timeout;wall=time.time()+timeout
    try:
        while time.monotonic()<deadline and time.time()<wall:
            if win32event.WaitForSingleObject(process,100)==win32event.WAIT_OBJECT_0:break
        else:raise AXRError('windows_setup_outcome_unknown_no_retry')
        exit_code=win32process.GetExitCodeProcess(process)
    finally:win32api.CloseHandle(process)
    directory=RootedDirectory(request.parent)
    try:response=json.loads(directory.read('outcome.json',16384))
    except Exception:raise AXRError('windows_setup_outcome_unknown_no_retry') from None
    finally:directory.close()
    if (type(response) is not dict or response.get('version')!=2 or response.get('nonce')!=value['nonce'] or response.get('operation')!=operation):
        raise AXRError('windows_setup_outcome_unknown_no_retry')
    if exit_code or response.get('state')!='Completed':
        code=response.get('error','windows_setup_operation_failed')
        raise AXRError(code if type(code) is str and re.fullmatch('[a-z][a-z0-9_]{0,99}',code) else 'windows_setup_operation_failed')
    return response['result']

def execute(operation,payload):
    from scripts.install_authority_windows import install,administrator
    administrator()
    if operation=='reconfigure':
        if set(payload)!={'source','owner'}:raise AXRError('windows_setup_request_invalid')
        from scripts.reconfigure_windows import correct
        return correct(payload['source'],payload['owner'])
    if operation in ('install','update'):
        if set(payload)!={'package','configuration','local_assets'}:raise AXRError('windows_setup_request_invalid')
        if operation=='update':
            from scripts.windows_service import ServiceController
            service=ServiceController();service.register();service.stop()
        return install(payload['package'],configuration=payload['configuration'],local_assets=payload['local_assets'],replace_stopped=operation=='update')
    if operation not in OPERATIONS or payload:raise AXRError('windows_setup_request_invalid')
    from scripts.windows_service import ServiceController
    service=ServiceController()
    if operation=='stop':return service.stop()
    service.register()
    if operation in ('initialize','recover'):
        result=service.run(operation)
        try:return {**result,**service.run(),'initialized':True}
        except AXRError as error:return {**result,'initialized':True,'service_started':False,'start_error':str(error)}
    return service.run({'initialize':'initialize','recover':'recover','refresh':'refresh','start':'serve'}[operation])

def admin_main(request_path,sha):
    # Read/replace only through the held original directory. A user's request
    # path cannot redirect the admin into writing a different application's file.
    from scripts.install_authority_windows import unredirected,administrator
    administrator();request=unredirected(request_path).absolute();directory=RootedDirectory(request.parent)
    try:
        raw=directory.read(request.name,65536)
        if type(sha) is not str or re.fullmatch('[0-9a-f]{64}',sha) is None or hashlib.sha256(raw).hexdigest()!=sha:
            raise AXRError('windows_setup_request_changed')
        def unique(items):
            value={}
            for key,item in items:
                if key in value:raise AXRError('windows_setup_request_invalid')
                value[key]=item
            return value
        value=json.loads(raw,object_pairs_hook=unique)
        if (type(value) is not dict or set(value)!={'version','operation','owner','nonce','payload'} or type(value['version']) is not int or value['version']!=2 or
            value['operation'] not in OPERATIONS or type(value['payload']) is not dict or type(value['nonce']) is not str or re.fullmatch('[0-9a-f]{32}',value['nonce']) is None or
            request.name!='request.json' or request.parent.parent!=cache_root(value['owner']) or re.fullmatch('setup-[0-9a-f]{32}',request.parent.name) is None):
            raise AXRError('windows_setup_request_invalid')
        if value['operation'] in ('install','update') and value['payload'].get('configuration',{}).get('deployment',{}).get('owner_user')!=value['owner']:
            raise AXRError('windows_setup_owner_invalid')
        if value['operation']=='reconfigure' and value['payload'].get('owner')!=value['owner']:raise AXRError('windows_setup_owner_invalid')
        try:result=execute(value['operation'],value['payload']);state='Completed';error=None
        except Exception as failure:
            code=str(failure) if isinstance(failure,AXRError) else ''
            error=code if re.fullmatch('[a-z][a-z0-9_]{0,99}',code) else 'windows_setup_operation_failed';result=None;state='FailedSafe'
        response=canonical({'version':2,'operation':value['operation'],'nonce':value['nonce'],'state':state,'result':result,'error':error})
        if len(response)>16384:raise AXRError('windows_setup_response_budget')
        with directory.parent('outcome.json') as (parent,name):directory.replace_at(parent,name,response,lambda:None)
        return 0 if state=='Completed' else 1
    finally:directory.close()

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--windows-setup-request',type=Path,required=True);p.add_argument('--request-sha',required=True);a=p.parse_args(argv)
    try:return admin_main(a.windows_setup_request,a.request_sha)
    except Exception:return 1
if __name__=='__main__':raise SystemExit(main())
