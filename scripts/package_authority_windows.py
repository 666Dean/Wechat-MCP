# SPDX-License-Identifier: MIT
"""Stage account-free Windows authority code. Never install or touch credentials."""
import argparse,hashlib,importlib.metadata,importlib.util,json,os,shutil,subprocess,sys,sysconfig
from pathlib import Path
from .windows_runtime import imports,inventory
from .package_authority_macos import stdlib_archive

HOSTS=('axr-authority.exe','axr-owner.exe','axr-frontend.exe','axr-runtime-check.exe')

def stage(root,build,dependencies,output,vc_runtime,vc_notice):
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12):raise ValueError('windows_python312_required')
    root,build,dependencies=map(lambda p:Path(p).resolve(strict=True),(root,build,dependencies));output=Path(output).absolute()
    if output.exists():raise ValueError('windows_package_output_must_be_new')
    from .validate_windows_credentials import validate,single_product
    validate(build,dependencies/'bin/sqlcipher.dll')
    cache=(build/'CMakeCache.txt').read_text()
    if 'AXR_SECURITY_RELEASE:BOOL=ON' not in cache or 'AXR_AUTHORITY_HOST:BOOL=ON' not in cache:raise ValueError('formal_windows_hosts_required')
    runtime=output/'runtime';packages=runtime/'packages';dynamic=runtime/'lib-dynload'
    for path in (packages,dynamic):path.mkdir(parents=True,exist_ok=False)
    def copy(source,target):
        source=Path(source);target=Path(target)
        if source.is_symlink() or source.is_junction() or not source.is_file():raise ValueError('windows_runtime_regular_file_required')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    for name in HOSTS:copy(build/'AXR/Release'/name,output/name)
    copy(build/'Release/wechat-uia.exe',output/'wechat-uia.exe')
    for name,source in [('axr',root/'AXR/axr'),('axr_applications',root/'axr_applications'),('axr_integration',root/'axr_integration'),('adapters',root/'adapters')]:
        shutil.copytree(source,packages/name,ignore=lambda directory,names:[n for n in names if n in ('__pycache__','bin') or
            Path(directory,n).is_file() and not n.endswith('.py')])
    extension=single_product(build/'AXR/Release','_axr_native*.pyd');copy(extension,packages/'axr'/extension.name)
    extension=single_product(build/'Release','_wechat_credentials*.pyd');copy(extension,packages/'axr_applications'/extension.name)
    stdlib=Path(sysconfig.get_path('stdlib'));base=Path(sys.base_prefix)
    stdlib_archive(stdlib,runtime/'python-runtime.zip')
    # CPython standard extensions and DLLs only; no site, user startup or venv.
    for path in (base/'DLLs').glob('*.pyd'):
        if path.name.startswith(('_test','_tkinter','xxlimited')):continue
        copy(path,dynamic/path.name)
    vc_runtime=Path(vc_runtime).resolve(strict=True)
    for name in ('python312.dll','python3.dll'):copy(base/name,output/name)
    for name in ('vcruntime140.dll','vcruntime140_1.dll'):copy(vc_runtime/name,output/name)
    modules=('win32api','win32security','win32file','win32pipe','win32event','win32process','win32service','win32profile','win32cred','_win32sysloader')
    for name in (*modules,'win32con','ntsecuritycon','pywintypes'):
        spec=importlib.util.find_spec(name)
        if spec is None or spec.origin is None:raise ValueError('windows_runtime_module_missing')
        source=Path(spec.origin);copy(source,(dynamic if source.suffix=='.pyd' else packages)/source.name)
    site=Path(importlib.util.find_spec('win32api').origin).parent.parent
    copy(site/'pywin32_system32/pywintypes312.dll',output/'pywintypes312.dll')
    zstd=importlib.util.find_spec('zstandard')
    if zstd is None or not zstd.submodule_search_locations:raise ValueError('windows_zstandard_required')
    shutil.copytree(next(iter(zstd.submodule_search_locations)),packages/'zstandard',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyi','py.typed'))
    copy(dependencies/'bin/sqlcipher.dll',runtime/'bin/sqlcipher.dll')
    # One ABI-compatible SQLite runtime serves SDK and CPython. Do not let two
    # same-basename DLL versions race the Windows loader; validate both below.
    copy(dependencies/'bin/sqlite3.dll',output/'sqlite3.dll')
    # Every non-OS import resolves to one explicit, hash-consistent binary.
    # VC runtime is app-local even when the developer's System32 has a copy.
    searches=[build/'AXR/Release',build/'Release',dependencies/'bin',base/'DLLs',site/'pywin32_system32',vc_runtime]
    system=Path(os.environ['SystemRoot'])/'System32'
    pending=[p for p in output.rglob('*') if p.suffix.lower() in ('.exe','.pyd','.dll')];seen=set()
    while pending:
        path=pending.pop();name=path.name.lower()
        if path in seen:continue
        seen.add(path)
        for dependency in imports(path):
            vc=dependency.startswith(('vcruntime','msvcp','concrt','vcomp'))
            if dependency.startswith(('api-ms-','ext-ms-')) or (not vc and (system/dependency).is_file()):continue
            target=output/dependency
            if target.is_file():continue
            matches=[p for directory in searches for p in directory.glob('*') if p.name.lower()==dependency and p.is_file() and not p.is_symlink()]
            hashes={hashlib.sha256(p.read_bytes()).hexdigest() for p in matches}
            if len(hashes)!=1:raise ValueError('windows_runtime_dependency_missing_or_ambiguous_'+dependency)
            copy(matches[0],target);pending.append(target)
    from axr.deployment_configuration import MARKER
    (runtime/'deployment.json').write_text(json.dumps(MARKER),encoding='utf8')
    for name,source in [('Application',root/'LICENSE'),('AXR',root/'AXR/LICENSE'),('Python',base/'LICENSE.txt'),
        ('Application-notices',root/'THIRD_PARTY_NOTICES.md'),('AXR-notices',root/'AXR/THIRD_PARTY_NOTICES.md')]:copy(source,runtime/'licenses'/(name+'.txt'))
    for name in ('openssl','sqlite3','sqlcipher','nlohmann-json'):copy(dependencies/'share'/name/'copyright',runtime/'licenses'/(name+'.txt'))
    copy(vc_notice,runtime/'licenses/Microsoft-VC-Redist.txt')
    for name in ('pywin32','zstandard'):
        distribution=importlib.metadata.distribution(name);found=[]
        for entry in distribution.files or ():
            if '.dist-info/' in str(entry).replace('\\','/') and any(part.lower().startswith(('license','copying')) for part in Path(entry).parts):
                source=distribution.locate_file(entry)
                if source.is_file():copy(source,runtime/'licenses'/(name+'-'+hashlib.sha256(str(entry).encode()).hexdigest()[:8]+'-'+source.name));found.append(source)
        if not found:raise ValueError('windows_dependency_license_missing_'+name)
    # Fresh isolated host: no site/env/PATH fallback, no authority/owner action.
    result=subprocess.run([str(output/'axr-runtime-check.exe'),'--validate-runtime'],capture_output=True,timeout=30,
        env={k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','TEMP','TMP')})
    if result.returncode:raise ValueError('windows_staged_runtime_validation_failed')
    report=json.loads(result.stdout)
    if report.get('runtime_valid') is not True or report.get('authority_started') is not False:raise ValueError('windows_staged_runtime_validation_failed')
    (output/'runtime-validation.json').write_text(json.dumps(report,sort_keys=True)+'\n',encoding='utf8')
    manifest={'version':2,'platform':'windows-x64','security_profile':'formal','application':'WeChat MCP',
        'account_data_included':False,'vendor_codex_binary_included':False,'files':inventory(output)}
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],cwd=root,text=True))
    manifest.update(source_revision=revision,source_dirty=dirty)
    (output/'package-review.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n',encoding='utf8')
    return manifest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for field in ('build','dependencies','output','vc-runtime','vc-notice'):p.add_argument('--'+field,type=Path,required=True)
    a=p.parse_args();value=stage(Path(__file__).resolve().parents[1],a.build,a.dependencies,a.output,a.vc_runtime,a.vc_notice)
    print(json.dumps({'files':len(value['files']),'account_data_included':False,'installed':False}))
if __name__=='__main__':main()
