# SPDX-License-Identifier: MIT
"""Explicit admin install of reviewed code; setup/service/consent stay separate."""
import argparse,ctypes,hashlib,json,os,re,shutil,sys,uuid
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,canonical
from .windows_runtime import inventory,imports

SERVICE='StellariaAXRAuthority'

def administrator():
    if sys.platform!='win32' or not ctypes.windll.shell32.IsUserAnAdmin():raise AXRError('windows_administrator_install_required')

def unredirected(path):
    path=Path(path).absolute()
    for node in (path,*path.parents):
        if node.is_symlink() or node.is_junction():raise AXRError('windows_install_reparse_denied')
    return path

def review(package):
    root=unredirected(package).resolve(strict=True);manifest=root/'package-review.json'
    if not manifest.is_file() or manifest.stat().st_size>2*1024**2:raise AXRError('windows_package_review_required')
    value=json.loads(manifest.read_bytes())
    if (value.get('version')!=2 or value.get('platform')!='windows-x64' or value.get('security_profile')!='formal' or
        value.get('account_data_included') is not False or value.get('vendor_codex_binary_included') is not False or type(value.get('files')) is not dict):
        raise AXRError('windows_public_package_required')
    actual=inventory(root);actual.pop('package-review.json',None)
    if actual!=value['files']:raise AXRError('windows_package_changed_since_review')
    from .package_authority_windows import HOSTS
    required={*HOSTS,'wechat-uia.exe','python312.dll','runtime/deployment.json','runtime/python-runtime.zip','runtime/packages/axr/__init__.py'}
    if not required<=set(actual):raise AXRError('windows_package_incomplete')
    from axr.deployment_configuration import MARKER
    if json.loads((root/'runtime/deployment.json').read_bytes())!=MARKER:raise AXRError('windows_public_package_required')
    for name in (*HOSTS,'wechat-uia.exe'):imports(root/name)
    return value

def protect(path,*,public=False,reader=None):
    import win32con,win32security
    path=unredirected(path);acl=win32security.ACL();flags=3 if path.is_dir() else 0
    administrators=win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid)
    for sid,rights in [(win32security.CreateWellKnownSid(win32security.WinLocalSystemSid),win32con.GENERIC_ALL),(administrators,win32con.GENERIC_ALL)]:
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS,flags,rights,sid)
    readers=['S-1-5-32-545','S-1-15-2-2'] if public else [reader] if reader else []
    for text in readers:acl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS,flags,win32con.GENERIC_READ|win32con.GENERIC_EXECUTE,win32security.ConvertStringSidToSid(text))
    win32security.SetNamedSecurityInfo(str(path),win32security.SE_FILE_OBJECT,win32security.OWNER_SECURITY_INFORMATION|
        win32security.DACL_SECURITY_INFORMATION|win32security.PROTECTED_DACL_SECURITY_INFORMATION,administrators,None,acl,None)

def validate_configuration(configuration,local_assets):
    if (type(configuration) is not dict or set(configuration)!={'version','application_module','deployment'} or configuration['version']!=2 or
        configuration['application_module']!='axr_applications.wechat' or len(canonical(configuration))>32768):raise AXRError('windows_install_configuration_invalid')
    config=configuration['deployment'];root=Path(native.windows_installation_root());data=Path(native.windows_data_root());owner=config.get('owner_user','')
    if re.fullmatch(r'S-1-5-21-\d+-\d+-\d+-\d+',owner) is None or Path(config.get('state',''))!=data/'state/wechat':raise AXRError('windows_install_owner_or_state_invalid')
    if re.fullmatch(r'\\\\\.\\pipe\\Stellaria\.AXR\.[A-Za-z0-9_.-]{1,120}',config.get('endpoint','')) is None:raise AXRError('windows_install_endpoint_invalid')
    app=config['application'];provider=app['codex_provider']
    if (app.get('navigation_helper')!=str(root/'wechat-uia.exe') or app.get('sqlcipher_library')!='@resources/bin/sqlcipher.dll' or
        provider.get('binary')!='@resources/provider/codex.exe' or provider.get('tls_bundle')!='@resources/provider/ca-bundle.pem' or
        Path(provider.get('workspace',''))!=data/'source'):
        raise AXRError('windows_install_fixed_assets_required')
    if set(local_assets) not in ({'codex','ca'},{'codex','ca','hello_trust'}):raise AXRError('windows_install_local_assets_required')
    for name,field in [('codex','sha256'),('ca','tls_sha256')]:
        source=unredirected(local_assets[name]);maximum=512*1024**2 if name=='codex' else 2*1024**2
        if not source.is_file() or not 1<=source.stat().st_size<=maximum or hashlib.sha256(source.read_bytes()).hexdigest()!=provider.get(field):
            raise AXRError('windows_install_local_asset_changed')
    imports(local_assets['codex'])
    # Source inference copies its executable directory, so only self-contained
    # vendor CLI images with OS imports are accepted at this install boundary.
    system=Path(os.environ['SystemRoot'])/'System32'
    if any(not name.startswith(('api-ms-','ext-ms-')) and not (system/name).is_file() for name in imports(local_assets['codex'])):
        raise AXRError('windows_install_provider_dependency_unqualified')
    from axr_applications.windows_enrollment import MACHINE_TRUST
    value=MACHINE_TRUST
    if 'hello_trust' in local_assets:
        trust=unredirected(local_assets['hello_trust'])
        if not trust.is_file() or trust.stat().st_size>140000:raise AXRError('windows_install_hello_roots_required')
        value=json.loads(trust.read_bytes())
    if type(value) is not dict or type(value.get('version')) is not int:raise AXRError('windows_install_hello_roots_required')
    if value!=MACHINE_TRUST and (set(value)!={'version','roots'} or type(value['version']) is not int or value['version']!=2 or type(value['roots']) is not list or
        not 1<=len(value['roots'])<=8 or any(type(v) is not str or not 2<=len(v)<=16384 or len(v)%2 or re.fullmatch('[0-9a-f]+',v) is None for v in value['roots'])):
        raise AXRError('windows_install_hello_roots_required')
    return root,data,owner

def install(package,*,configuration,local_assets,replace_stopped=False):
    administrator();package=unredirected(package);approved=review(package)
    root,data,owner=validate_configuration(configuration,local_assets);unredirected(root);unredirected(data)
    owner_pin=None
    if root.exists():
        if not replace_stopped:raise AXRError('windows_existing_install_requires_update')
        from .windows_service import ServiceController
        if ServiceController().status()['state']!='Stopped':raise AXRError('windows_install_stopped_service_required')
        native.verify_windows_installation(str(root))
        current=json.loads(Path(native.windows_deployment_configuration()).read_bytes())
        from axr_applications.wechat import provider_build_update
        old,new=current['deployment'],configuration['deployment']
        if ({k:v for k,v in old.items() if k!='application'}!={k:v for k,v in new.items() if k!='application'} or
            not provider_build_update(old['application'],new['application'],bundled_path='@resources/provider/codex.exe')):
            raise AXRError('windows_update_configuration_changed')
        if (root/'runtime/owner-key.json').exists():
            from axr_applications.windows_enrollment import installed_json,hex_bytes
            owner_pin=installed_json(root/'runtime','owner-key.json',32768)
            if (set(owner_pin)!={'version','provider','public_key'} or type(owner_pin['version']) is not int or owner_pin['version']!=2 or
                owner_pin['provider']!='WindowsHello/RSA2048' or len(hex_bytes(owner_pin['public_key'],294))!=294):raise AXRError('wechat_owner_public_key_pin_changed')
    elif replace_stopped:raise AXRError('windows_existing_install_required')
    stage=root.with_name('.Stellaria-AXR-stage-'+uuid.uuid4().hex);stage.mkdir();protect(stage,public=True)
    # Leave an interrupted protected stage for explicit inspection; do not
    # recursively delete directories or roll back credentials/authority state.
    from axr.rooted import RootedDirectory
    source=RootedDirectory(package)
    try:
        for relative,sha in approved['files'].items():
            raw=source.read(relative,128*1024**2)
            if hashlib.sha256(raw).hexdigest()!=sha:raise AXRError('windows_package_changed_during_copy')
            target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    finally:source.close()
    (stage/'package-review.json').write_bytes(canonical(approved))
    for node in (stage,*stage.rglob('*')):protect(node,public=True)
    if review(stage)!=approved:raise AXRError('windows_package_changed_during_copy')
    selections=[('codex','runtime/provider/codex.exe'),('ca','runtime/provider/ca-bundle.pem')]
    if 'hello_trust' in local_assets:selections.append(('hello_trust','runtime/hello-trust.json'))
    for name,relative in selections:
        path=unredirected(local_assets[name]);source=RootedDirectory(path.parent)
        try:raw=source.read(path.name,512*1024**2 if name=='codex' else 2*1024**2)
        finally:source.close()
        if name!='hello_trust' and hashlib.sha256(raw).hexdigest()!=configuration['deployment']['application']['codex_provider']['sha256' if name=='codex' else 'tls_sha256']:
            raise AXRError('windows_install_local_asset_changed')
        target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);protect(target,public=True)
    if 'hello_trust' not in local_assets:
        from axr_applications.windows_enrollment import MACHINE_TRUST
        target=stage/'runtime/hello-trust.json';target.write_bytes(canonical(MACHINE_TRUST));protect(target,public=True)
    for node in (stage/'runtime/provider',):protect(node,public=True)
    # Bind all code, packages, DLLs and local public provider assets. Mutable
    # owner/connection metadata is separate and never defines executable code.
    manifest={'version':2,'files':inventory(stage)}
    (stage/'installation-review.json').write_bytes(canonical(manifest));protect(stage/'installation-review.json',public=True)
    if owner_pin is not None:
        pin=stage/'runtime/owner-key.json';pin.write_bytes(canonical(owner_pin)+b'\n');protect(pin,public=True)
    native.verify_windows_runtime_files(str(stage))
    data.mkdir(parents=True,exist_ok=True);protect(data,reader=owner)
    target=data/'deployment.json'
    if target.exists() and not replace_stopped and target.read_bytes()!=canonical(configuration):raise AXRError('windows_existing_configuration_requires_review')
    temporary=data/('deployment-'+uuid.uuid4().hex+'.tmp');temporary.write_bytes(canonical(configuration));protect(temporary,reader=owner)
    # Same-volume rename keeps the code switch bounded. Preserve the old code
    # for recovery, while existing task/credential state remains untouched.
    backup=None
    if root.exists():backup=root.with_name('.Stellaria-AXR-previous-'+uuid.uuid4().hex);root.rename(backup)
    try:stage.rename(root)
    except BaseException:
        if backup is not None:backup.rename(root)
        raise
    os.replace(temporary,target);native.verify_windows_installation(str(root))
    return {'installed':True,'owner_enrolled':False,'wechat_authorized':False,'service_started':False,'build_reenrollment_required':bool(backup)}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,required=True);p.add_argument('--configuration',type=Path,required=True)
    for name in ('codex','ca'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--hello-trust',type=Path)
    p.add_argument('--replace-stopped',action='store_true');a=p.parse_args()
    configuration=json.loads(a.configuration.read_bytes())
    assets={'codex':a.codex,'ca':a.ca}
    if a.hello_trust:assets['hello_trust']=a.hello_trust
    print(json.dumps(install(a.package,configuration=configuration,local_assets=assets,replace_stopped=a.replace_stopped)))
if __name__=='__main__':main()
