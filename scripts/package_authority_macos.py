#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage a self-contained hardened authority; never install or authorize.

The output is a reviewable bundle. Root-owned installation and authenticated
owner enrollment are separate, explicit steps. No Keychain reads occur here.
"""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import sysconfig
import zipfile

SYSTEM=('/System/Library/','/usr/lib/')

def command(args):
    return subprocess.run([str(x) for x in args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout

def macho(path):
    with path.open('rb') as stream:return stream.read(4) in (b'\xcf\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbf')

def dependencies(path):
    return [line.strip().split(' (',1)[0] for line in command(['/usr/bin/otool','-L',path]).splitlines()[1:]]

def rpaths(path):
    lines=command(['/usr/bin/otool','-l',path]).splitlines();out=[]
    for i,line in enumerate(lines):
        if line.strip()=='cmd LC_RPATH':out.append(lines[i+2].strip().split(' ',1)[1].rsplit(' (offset ',1)[0])
    return out

def stdlib_archive(stdlib,target):
    # No site-packages, user hooks, startup files, tests or bytecode.
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for directory,folders,files in os.walk(stdlib):
            folders[:]=sorted(x for x in folders if x not in {'site-packages','lib-dynload','test','tests','idlelib','tkinter','turtledemo','ensurepip','__pycache__','venv'})
            for name in sorted(files):
                if not name.endswith('.py'):continue
                path=Path(directory)/name;archive.writestr(str(path.relative_to(stdlib)),path.read_bytes())

def verify_navigation_build(root,build):
    output=build/'wechat-chat-navigation-experimental'
    try:
        manifest=json.loads(output.with_suffix('.build.json').read_bytes())
        actual={'source_sha256':hashlib.sha256((root/'adapters/macos/experimental_chat_navigation.swift').read_bytes()).hexdigest(),
                'core_sha256':hashlib.sha256((build/'AXR/libaxr.a').read_bytes()).hexdigest(),
                'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
        if manifest!=actual:raise ValueError()
    except (OSError,ValueError):raise ValueError('native navigation helper must be rebuilt from reviewed source/core') from None
    return output

def verify_optimized_runtime(build):
    try:
        cache=(build/'CMakeCache.txt').read_text()
        values=[line.split('=',1)[1] for line in cache.splitlines() if line.startswith('CMAKE_BUILD_TYPE:')]
        if len(values)!=1 or values[0] not in ('Release','RelWithDebInfo'):raise ValueError()
    except (OSError,ValueError):raise ValueError('deployment requires an optimized Release or RelWithDebInfo build') from None

def stage(root,build,output,deployment,*,identity='-'):
    if sys.platform!='darwin' or sys.version_info[:2]!=(3,12):raise ValueError('macOS Python 3.12 packaging required')
    verify_optimized_runtime(build)
    if not identity or identity=='-':raise ValueError('dynamic embedded runtime requires one local signing team; ad-hoc needs a fully static host')
    if deployment.get('application',{}).get('navigation_helper'):verify_navigation_build(root,build)
    output=output.absolute()
    if output.exists() or output.is_symlink():raise ValueError('output must be new; existing bundles are never overwritten')
    app=output/'AXR Authority.app';contents=app/'Contents';resources=contents/'Resources';executables=contents/'MacOS';frameworks=contents/'Frameworks'
    for path in (resources/'lib-dynload',resources/'packages',executables,frameworks):path.mkdir(parents=True,exist_ok=False)
    with (contents/'Info.plist').open('wb') as stream:plistlib.dump({'CFBundleIdentifier':'org.stellaria.axr.authority','CFBundleExecutable':'axr-authority','CFBundleName':'AXR Authority','CFBundlePackageType':'APPL','LSUIElement':True},stream)
    exe=executables/'axr-authority';shutil.copy2(build/'AXR/axr-authority',exe)
    native=next((build/'AXR').glob('_axr_native*.so'));consumer=next(build.glob('_wechat_credentials*.so'))
    for package,source in [('axr',root/'AXR/axr'),('axr_applications',root/'axr_applications'),('adapters',root/'adapters'),('axr_integration',root/'axr_integration')]:
        shutil.copytree(source,resources/'packages'/package,ignore=lambda directory,names:[n for n in names if n=='__pycache__' or (Path(directory,n).is_file() and not n.endswith('.py')) or n=='bin'])
    shutil.copy2(native,resources/'packages/axr'/native.name);shutil.copy2(consumer,resources/'packages/axr_applications'/consumer.name)
    stdlib=Path(sysconfig.get_path('stdlib'));stdlib_archive(stdlib,resources/'python312.zip')
    # Only standard extension modules needed by this fixed runtime. Missing ones
    # are errors, not a fallback to the developer's Python installation.
    extensions=('_asyncio','_bisect','_blake2','_bz2','_contextvars','_csv','_ctypes','_datetime','_decimal','_elementtree','_hashlib','_heapq','_json','_lzma','_md5','_multiprocessing','_opcode','_pickle','_posixshmem','_posixsubprocess','_queue','_random','_sha1','_sha2','_sha3','_socket','_sqlite3','_ssl','_struct','_typing','array','binascii','fcntl','grp','math','mmap','pyexpat','resource','select','termios','unicodedata','zlib')
    for name in extensions:
        if name in sys.builtin_module_names:continue
        found=list((stdlib/'lib-dynload').glob(name+'.*.so'))
        if len(found)!=1:raise ValueError('missing standard runtime extension: '+name)
        shutil.copy2(found[0],resources/'lib-dynload'/found[0].name)
    # Resolve each dependency using the SOURCE image's rpaths before rewriting.
    origins={exe:(build/'AXR/axr-authority').resolve(),resources/'packages/axr'/native.name:native.resolve(),resources/'packages/axr_applications'/consumer.name:consumer.resolve()}
    enclave=build/'AXR/libaxr-enclave.dylib'
    if not enclave.is_file():raise ValueError('native Secure Enclave bridge required')
    shutil.copy2(enclave,frameworks/enclave.name);origins[frameworks/enclave.name]=enclave.resolve()
    for path in (resources/'lib-dynload').iterdir():origins[path]=(stdlib/'lib-dynload'/path.name).resolve()
    # WeChat text can be Zstd-compressed. Do not accidentally depend on the
    # developer virtualenv when decoding a real message in the installed host.
    zstd=importlib.util.find_spec('zstandard')
    if zstd is None or not zstd.submodule_search_locations:raise ValueError('pinned zstandard runtime required')
    zstd_root=Path(next(iter(zstd.submodule_search_locations)))
    shutil.copytree(zstd_root,resources/'packages/zstandard',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyi','py.typed'))
    for path in (resources/'packages/zstandard').rglob('*.so'):origins[path]=(zstd_root/path.relative_to(resources/'packages/zstandard')).resolve()
    supplied=deployment.get('sqlcipher_library')
    # The application configuration, when present, owns its native dependency.
    if not supplied:supplied=deployment.get('application',{}).get('sqlcipher_library')
    if supplied:
        cipher=Path(supplied).resolve(strict=True);dest=frameworks/'libwechat-sqlcipher.dylib';shutil.copy2(cipher,dest);origins[dest]=cipher
        if 'application' in deployment:deployment={**deployment,'application':{**deployment['application'],'sqlcipher_library':'@resources/../Frameworks/libwechat-sqlcipher.dylib'}}
        else:deployment={**deployment,'sqlcipher_library':'@resources/../Frameworks/libwechat-sqlcipher.dylib'}
    navigation=build/'wechat-chat-navigation-experimental'
    if navigation.is_file():
        (resources/'bin').mkdir();helper=resources/'bin/wechat-navigation';shutil.copy2(navigation,helper);origins[helper]=navigation.resolve()
        if 'application' in deployment:deployment={**deployment,'application':{**deployment['application'],'navigation_helper':'@resources/bin/wechat-navigation'}}
    owner_auth=build/'AXR/axr-helper'
    if not owner_auth.is_file():raise ValueError('native owner authentication helper required')
    (resources/'bin').mkdir(exist_ok=True)
    auth=resources/'bin/axr-helper';shutil.copy2(owner_auth,auth);origins[auth]=owner_auth.resolve()
    copied={str(source):dest for dest,source in origins.items()};pending=list(origins)
    index=0
    while index<len(pending):
        dest=pending[index];source=origins[dest];index+=1
        for dependency in dependencies(source):
            if dependency.startswith(SYSTEM):continue
            if source.suffix=='.dylib' and dependency==dependencies(source)[0]:continue # LC_ID_DYLIB, not a dependency
            candidates=[]
            expanded=dependency.replace('@loader_path',str(source.parent)).replace('@executable_path',str((build/'AXR').resolve()))
            if expanded.startswith('@rpath/'):
                for rp in rpaths(source):
                    rp=rp.replace('@loader_path',str(source.parent)).replace('@executable_path',str((build/'AXR').resolve()))
                    candidates.append(Path(rp)/dependency[len('@rpath/'):])
                candidates.extend([Path(sysconfig.get_config_var('LIBDIR'))/Path(dependency).name])
            else:candidates.append(Path(expanded))
            resolved=next((p.resolve() for p in candidates if p.is_absolute() and p.is_file()),None)
            if resolved is None:raise ValueError('unresolved native dependency: '+dependency)
            if str(resolved) not in copied:
                name=hashlib.sha256(str(resolved).encode()).hexdigest()[:12]+'-'+resolved.name;new=frameworks/name
                shutil.copy2(resolved,new);copied[str(resolved)]=new;origins[new]=resolved;pending.append(new)
            replacement='@loader_path/'+os.path.relpath(copied[str(resolved)],dest.parent)
            command(['/usr/bin/install_name_tool','-change',dependency,replacement,dest])
        # No inherited developer rpath may remain as an alternate load source.
        for rp in rpaths(dest):command(['/usr/bin/install_name_tool','-delete_rpath',rp,dest])
        if dest.suffix=='.dylib':command(['/usr/bin/install_name_tool','-id','@loader_path/'+dest.name,dest])
    configuration={'version':2,'application_module':'axr_applications.wechat','deployment':deployment}
    (resources/'deployment.json').write_text(json.dumps(configuration,ensure_ascii=False,separators=(',',':')))
    for name,source in [('AXR',root/'AXR/LICENSE'),('Application',root/'LICENSE')]:shutil.copy2(source,resources/(name+'-LICENSE.txt'))
    license_root=resources/'licenses';license_root.mkdir()
    shutil.copy2(stdlib/'LICENSE.txt',license_root/'Python.txt')
    shutil.copy2(root/'THIRD_PARTY_NOTICES.md',license_root/'Application-notices.md')
    shutil.copy2(root/'AXR/THIRD_PARTY_NOTICES.md',license_root/'AXR-notices.md')
    distribution=importlib.metadata.distribution('zstandard')
    for source in distribution.files or []:
        if '.dist-info/licenses/' in str(source):
            shutil.copy2(distribution.locate_file(source),license_root/('zstandard-'+Path(source).name))
    # Seal inner code before the outer resource envelope. No get-task-allow,
    # DYLD environment, unsigned-memory or library-validation exception.
    for dest in pending:command(['/usr/bin/codesign','--force','--sign',identity,'--options','runtime','--timestamp=none',dest])
    command(['/usr/bin/codesign','--force','--sign',identity,'--options','runtime','--timestamp=none','--identifier','org.stellaria.axr.authority',app])
    command(['/usr/bin/codesign','--verify','--deep','--strict',app])
    for dest in pending:
        if any(not d.startswith(SYSTEM+('@loader_path/',)) for d in dependencies(dest)[1 if dest.suffix=='.dylib' else 0:]):raise ValueError('external dependency remains')
    # A separate signing identity is required for the user-presence key. Keep
    # the same self-contained runtime, never a symlink into the checkout.
    owner=output/'AXR Owner.app';shutil.copytree(app,owner)
    owner_exe=owner/'Contents/MacOS/axr-owner';old_exe=owner/'Contents/MacOS/axr-authority';old_exe.unlink()
    shutil.copy2(build/'AXR/axr-owner',owner_exe)
    # Host links are identical except for the fixed entry-point macro.
    for before,after in zip(dependencies(build/'AXR/axr-authority'),dependencies(exe)):
        if before!=after:command(['/usr/bin/install_name_tool','-change',before,after,owner_exe])
    for rp in rpaths(owner_exe):command(['/usr/bin/install_name_tool','-delete_rpath',rp,owner_exe])
    with (owner/'Contents/Info.plist').open('wb') as stream:plistlib.dump({'CFBundleIdentifier':'org.stellaria.axr.owner','CFBundleExecutable':'axr-owner','CFBundleName':'AXR Owner','CFBundlePackageType':'APPL','LSUIElement':True},stream)
    command(['/usr/bin/codesign','--force','--sign',identity,'--options','runtime','--timestamp=none',owner_exe])
    command(['/usr/bin/codesign','--force','--sign',identity,'--options','runtime','--timestamp=none','--identifier','org.stellaria.axr.owner',owner])
    command(['/usr/bin/codesign','--verify','--deep','--strict',owner])
    frontend=output/'AXR MCP.app';shutil.copytree(app,frontend)
    frontend_exe=frontend/'Contents/MacOS/axr-frontend'
    (frontend/'Contents/MacOS/axr-authority').unlink();shutil.copy2(build/'AXR/axr-frontend',frontend_exe)
    for before,after in zip(dependencies(build/'AXR/axr-authority'),dependencies(exe)):
        if before!=after:command(['/usr/bin/install_name_tool','-change',before,after,frontend_exe])
    for rp in rpaths(frontend_exe):command(['/usr/bin/install_name_tool','-delete_rpath',rp,frontend_exe])
    with (frontend/'Contents/Info.plist').open('wb') as stream:plistlib.dump({'CFBundleIdentifier':'org.stellaria.axr.frontend','CFBundleExecutable':'axr-frontend','CFBundleName':'WeChat MCP','CFBundlePackageType':'APPL','LSUIElement':True},stream)
    command(['/usr/bin/codesign','--force','--sign',identity,'--options','runtime','--timestamp=none',frontend_exe])
    command(['/usr/bin/codesign','--force','--sign',identity,'--options','runtime','--timestamp=none','--identifier','org.stellaria.axr.frontend',frontend])
    command(['/usr/bin/codesign','--verify','--deep','--strict',frontend])
    # Separate, non-authority development tool. Never install this validation
    # surface in the customer application. It cannot open authority-only keys.
    validation=output/'AXR Runtime Check.app';shutil.copytree(app,validation)
    validation_exe=validation/'Contents/MacOS/axr-runtime-check'
    (validation/'Contents/MacOS/axr-authority').unlink();shutil.copy2(build/'AXR/axr-runtime-check',validation_exe)
    for before,after in zip(dependencies(build/'AXR/axr-authority'),dependencies(exe)):
        if before!=after:command(['/usr/bin/install_name_tool','-change',before,after,validation_exe])
    for rp in rpaths(validation_exe):command(['/usr/bin/install_name_tool','-delete_rpath',rp,validation_exe])
    with (validation/'Contents/Info.plist').open('wb') as stream:plistlib.dump({'CFBundleIdentifier':'org.stellaria.axr.validation','CFBundleExecutable':'axr-runtime-check','CFBundleName':'AXR Runtime Check','CFBundlePackageType':'APPL','LSUIElement':True},stream)
    command(['/usr/bin/codesign','--force','--sign',identity,'--options','runtime','--timestamp=none',validation_exe])
    command(['/usr/bin/codesign','--force','--sign',identity,'--options','runtime','--timestamp=none','--identifier','org.stellaria.axr.validation',validation])
    command(['/usr/bin/codesign','--verify','--deep','--strict',validation])
    inventory={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file()}
    report={'version':2,'bundle':'AXR Authority.app','files':inventory,'native_images':len(pending),'vendor_certificate_required':False,'installed':False,'owner_enrolled':False,'wechat_authorized':False,'qualification':'local-deployment-candidate','redistribution_inventory_qualified':False}
    (output/'package-review.json').write_text(json.dumps(report,sort_keys=True,indent=2))
    return {'bundle':str(app),'native_images':len(pending),'installed':False,'owner_enrolled':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--build',required=True,type=Path);parser.add_argument('--output',required=True,type=Path);parser.add_argument('--deployment',required=True,type=Path);parser.add_argument('--identity',required=True,help='Local development or distribution signing identity; Developer ID is optional')
    args=parser.parse_args();config=json.loads(args.deployment.read_text());print(json.dumps(stage(Path(__file__).resolve().parent.parent,args.build,args.output,config,identity=args.identity)))
if __name__=='__main__':main()
