# SPDX-License-Identifier: MIT
"""Fixed demand-start LocalSystem service control, no arbitrary command/identity."""
import argparse,json,time
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError
from .install_authority_windows import administrator,SERVICE

class ServiceController:
    def __init__(self):
        import win32service
        self.api=win32service;self.image=Path(native.windows_installation_root())/'axr-authority.exe'
    def command(self,mode):
        if mode not in ('serve','initialize','refresh'):raise AXRError('windows_service_fixed_mode_required')
        return '"'+str(self.image)+'" '+{'serve':'--service','initialize':'--initialize-service','refresh':'--refresh-service'}[mode]
    def _open(self,rights,*,create=False):
        api=self.api;manager=api.OpenSCManager(None,None,api.SC_MANAGER_CONNECT|(api.SC_MANAGER_CREATE_SERVICE if create else 0))
        try:service=api.OpenService(manager,SERVICE,rights)
        except BaseException:api.CloseServiceHandle(manager);raise
        return manager,service
    def _close(self,pair):
        for handle in reversed(pair):self.api.CloseServiceHandle(handle)
    def _check(self,service):
        api=self.api;value=api.QueryServiceConfig(service)
        if value[0]!=api.SERVICE_WIN32_OWN_PROCESS or value[1]!=api.SERVICE_DEMAND_START or value[3] not in tuple(self.command(m) for m in ('serve','initialize','refresh')) or value[7] not in ('LocalSystem',r'NT AUTHORITY\SYSTEM'):
            raise AXRError('windows_service_configuration_changed')
    def status(self):
        api=self.api
        try:pair=self._open(api.SERVICE_QUERY_CONFIG|api.SERVICE_QUERY_STATUS)
        except Exception as error:
            if getattr(error,'winerror',None)==1060:return {'registered':False,'state':'Absent'}
            raise
        try:
            self._check(pair[1]);value=api.QueryServiceStatus(pair[1]);state={api.SERVICE_STOPPED:'Stopped',api.SERVICE_RUNNING:'Running'}.get(value[1],'Pending')
            return {'registered':True,'state':state,'exit_code':value[3],'specific_exit_code':value[4]}
        finally:self._close(pair)
    def register(self):
        administrator();native.verify_windows_installation(str(self.image.parent));api=self.api
        manager=api.OpenSCManager(None,None,api.SC_MANAGER_CONNECT|api.SC_MANAGER_CREATE_SERVICE);service=None
        try:
            try:service=api.OpenService(manager,SERVICE,api.SERVICE_QUERY_CONFIG|api.SERVICE_QUERY_STATUS)
            except Exception as error:
                if getattr(error,'winerror',None)!=1060:raise
                service=api.CreateService(manager,SERVICE,'Stellaria AXR Authority',api.SERVICE_ALL_ACCESS,api.SERVICE_WIN32_OWN_PROCESS,
                    api.SERVICE_DEMAND_START,api.SERVICE_ERROR_NORMAL,self.command('serve'),None,0,None,None,None)
            self._check(service)
        finally:
            if service is not None:api.CloseServiceHandle(service)
            api.CloseServiceHandle(manager)
        return {'registered':True,'service_started':False,'authorization_restored':False}
    def run(self,mode='serve',*,timeout=240):
        administrator();native.verify_windows_installation(str(self.image.parent));api=self.api
        pair=self._open(api.SERVICE_QUERY_CONFIG|api.SERVICE_QUERY_STATUS|api.SERVICE_CHANGE_CONFIG|api.SERVICE_START|api.SERVICE_STOP)
        try:
            service=pair[1];self._check(service)
            if api.QueryServiceStatus(service)[1]!=api.SERVICE_STOPPED:raise AXRError('windows_service_must_be_stopped')
            if mode=='serve':
                from axr.deployment_configuration import read
                config=read(self.image.parent/'runtime')['deployment']
                if not (Path(config['state'])/'policy.sealed.json').is_file():raise AXRError('owner_initialization_required')
            api.ChangeServiceConfig(service,api.SERVICE_NO_CHANGE,api.SERVICE_NO_CHANGE,api.SERVICE_NO_CHANGE,self.command(mode),None,0,None,None,None,None)
            try:
                api.StartService(service,None);wall=time.time()+timeout;deadline=time.monotonic()+timeout
                while time.time()<wall and time.monotonic()<deadline:
                    status=api.QueryServiceStatus(service)
                    if mode=='serve' and status[1]==api.SERVICE_RUNNING:return {'service_started':True,'authorization_restored':False}
                    if status[1]==api.SERVICE_STOPPED:
                        if mode!='serve' and status[3]==0 and status[4]==0:return {'completed':mode,'authorization_restored':False,'service_started':False}
                        raise AXRError('windows_service_operation_failed')
                    time.sleep(.1)
                try:api.ControlService(service,api.SERVICE_CONTROL_STOP)
                finally:raise AXRError('windows_service_operation_timed_out')
            finally:
                # Never leave a first-setup/update command as the normal entry.
                # If still stopping, refuse completion and preserve its state.
                if mode!='serve' and api.QueryServiceStatus(service)[1]==api.SERVICE_STOPPED:
                    api.ChangeServiceConfig(service,api.SERVICE_NO_CHANGE,api.SERVICE_NO_CHANGE,api.SERVICE_NO_CHANGE,self.command('serve'),None,0,None,None,None,None)
        finally:self._close(pair)
    def stop(self,*,timeout=30):
        administrator();api=self.api;pair=self._open(api.SERVICE_QUERY_CONFIG|api.SERVICE_QUERY_STATUS|api.SERVICE_STOP)
        try:
            service=pair[1];self._check(service)
            if api.QueryServiceStatus(service)[1]!=api.SERVICE_STOPPED:api.ControlService(service,api.SERVICE_CONTROL_STOP)
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if api.QueryServiceStatus(service)[1]==api.SERVICE_STOPPED:return {'stopped':True,'state_retained':True,'authorization_restored':False}
                time.sleep(.1)
            raise AXRError('windows_service_shutdown_incomplete')
        finally:self._close(pair)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('status','register','initialize','refresh','start','stop'));a=p.parse_args()
    controller=ServiceController();method={'start':lambda:controller.run(),'initialize':lambda:controller.run('initialize'),'refresh':lambda:controller.run('refresh')}.get(a.operation)
    print(json.dumps(method() if method else getattr(controller,a.operation)()))
if __name__=='__main__':main()
