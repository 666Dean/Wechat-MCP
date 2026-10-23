# SPDX-License-Identifier: MIT
"""Build and check an account-free Windows x64 desktop candidate; never install."""
import argparse,hashlib,importlib.metadata,json,os,platform,shutil,subprocess,sys
from pathlib import Path
from .install_authority_windows import review
from .windows_runtime import inventory

ROOT=Path(__file__).resolve().parents[1]

def inspect_privacy(app):
    from PyInstaller.archive.readers import CArchiveReader
    forbidden=[str(Path.home()).encode(),str(ROOT).encode(),str(ROOT).replace('\\','/').encode()]
    for path in app.rglob('*'):
        if path.is_symlink() or path.is_junction():raise ValueError('windows_desktop_link_denied')
        if not path.is_file():continue
        if path.name=='direct_url.json':raise ValueError('windows_desktop_install_origin_metadata_denied')
        data=path.read_bytes()
        if any(value in data for value in forbidden):raise ValueError('windows_desktop_private_path')
    archive=CArchiveReader(str(app/'WeChatMCP.exe'));checked=0
    for name,entry in archive.toc.items():
        if entry[-1]=='z':
            nested=archive.open_embedded_archive(name)
            for module in nested.toc:
                data=nested.extract(module,raw=True)
                if data and any(value in data for value in forbidden):raise ValueError('windows_desktop_private_python_path')
                checked+=1
        elif entry[-1] in ('s','m','M','x'):
            data=archive.extract(name)
            if data and any(value in data for value in forbidden):raise ValueError('windows_desktop_private_python_entry')
            checked+=1
    return {'private_paths':0,'external_links':0,'python_archive_entries':checked}

def check_runtime(app,output):
    executable=app/'WeChatMCP.exe'
    clean=output/'smoke';clean.mkdir();temporary=clean/'tmp';temporary.mkdir()
    environment={k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','SYSTEMDRIVE')}
    environment.update(TEMP=str(temporary),TMP=str(temporary),USERPROFILE=str(clean),HOME=str(clean),APPDATA=str(clean/'AppData/Roaming'),LOCALAPPDATA=str(clean/'AppData/Local'),PATH=str(Path(os.environ['SystemRoot'])/'System32'),QT_QPA_PLATFORM='offscreen')
    report=clean/'runtime.json'
    subprocess.run([str(executable),'--runtime-check','--check-output',str(report)],check=True,env=environment,cwd=clean,timeout=45)
    screenshot=clean/'fixture.png'
    subprocess.run([str(executable),'--fixture','--capture',str(screenshot),'--exit-after','8'],check=True,env=environment,cwd=clean,timeout=45)
    if not screenshot.is_file() or screenshot.stat().st_size<1024:raise ValueError('windows_desktop_fixture_render_failed')
    return {'runtime':json.loads(report.read_bytes()),'synthetic_qt_render':True}

def notices(target,components,qt):
    target.mkdir(parents=True)
    shutil.copytree(components/'runtime/licenses',target/'runtime')
    if not (qt/'LGPL-3.0-only.txt').is_file() or not (qt/'GPL-3.0-only.txt').is_file():
        raise ValueError('windows_qt_upstream_notices_required')
    shutil.copytree(qt,target/'QtForPython')
    records=[]
    for dist in sorted(importlib.metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
        name=dist.metadata['Name'];found=[]
        for entry in dist.files or ():
            parts=Path(entry).parts
            if not any(p.endswith('.dist-info') for p in parts) or not any(p.lower().startswith(('license','copying','notice')) for p in parts):continue
            source=Path(dist.locate_file(entry))
            if not source.is_file():continue
            output=target/'python'/name/Path(*parts[1:]);output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,output)
            found.append(output.relative_to(target).as_posix())
        records.append({'name':name,'version':dist.version,'notices':found})
    (target/'BUILD-DEPENDENCIES.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf8')
    (target/'SOURCE-AND-REPLACEMENT.md').write_text('''# Source and library replacement

The combined application is AGPL-3.0-only; individual MIT and dependency
licenses remain in force. Matching source and build scripts are available at
the source revision in BUILDINFO.json. Build-only packages may appear in the
dependency inventory; that list does not assert all packages were shipped.

Qt/PySide/Shiboken are dynamically linked in _internal/PySide6 and shiboken6.
Compatible x64 replacement libraries may be substituted and this application
rebuilt for debugging permitted modifications. No project restriction prevents
reverse engineering for that purpose. Replacement does not authorize the AXR
service, whose exact installed code separately requires owner review.

Qt 6.10.2 sources: https://download.qt.io/archive/qt/6.10/6.10.2/single/
PySide 6.10.2 sources: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.2-src/
PyInstaller bootloader: https://github.com/pyinstaller/pyinstaller/tree/v6.22.0
Python 3.12 sources: https://www.python.org/downloads/source/
''',encoding='utf8')

def build(output,components,qt):
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12) or platform.machine().lower() not in ('amd64','x86_64'):
        raise ValueError('windows_python312_x64_required')
    if importlib.metadata.version('PyInstaller')!='6.22.0':raise ValueError('pyinstaller_622_required')
    if importlib.metadata.version('PySide6-Essentials')!='6.10.2':raise ValueError('pyside_6102_required')
    output=Path(output).absolute();components=Path(components).resolve(strict=True);qt=Path(qt).resolve(strict=True)
    if output.exists():raise ValueError('windows_desktop_output_must_be_new')
    reviewed=review(components)
    inputs=output/'inputs';inputs.mkdir(parents=True)
    runtime=inputs/'runtime';runtime.mkdir()
    # SDK Python and native extension must both come from the formal build.
    shutil.copytree(components/'runtime/packages/axr',runtime/'axr')
    notices(inputs/'licenses',components,qt)
    from desktop.app_icon import windows_icon
    icon=windows_icon(ROOT/'desktop/icon.svg',inputs/'WeChatMCP.ico')
    datas=[(str(p),'desktop') for p in (ROOT/'desktop').iterdir() if p.suffix in ('.qml','.svg') or p.name=='qmldir']
    datas += [(str(components),'authority-components'),(str(inputs/'licenses'),'licenses')]
    binaries=[(str(p),'.') for p in components.iterdir() if p.suffix.lower()=='.dll']
    spec=inputs/'windows.spec'
    spec.write_text(f'''a=Analysis([{str(ROOT/'desktop/release_entry.py')!r}],pathex={[str(runtime),str(ROOT)]!r},binaries={binaries!r},datas={datas!r},
 hiddenimports=['PySide6.QtQuick','PySide6.QtQuickControls2','PySide6.QtSvg','PySide6.QtNetwork','PySide6.QtOpenGL','win32com.shell.shell','win32timezone','scripts.install_authority_windows','scripts.windows_service','desktop.windows_setup','desktop.windows_provisioning','mcp.client.stdio'],
 excludes=['pytest','numpy','scipy','torch','pandas','matplotlib','tkinter','PyQt5','PyQt6','wx','wxauto4','apsw'])
a.datas=[e for e in a.datas if not e[0].replace(chr(92),'/').endswith('.dist-info/direct_url.json')]
# Qt uses the Windows OS unversioned ICU API. A vcpkg icuuc.dll on the
# builder PATH has version-suffixed exports and breaks Qt import. Never
# redistribute or shadow this OS component with that unrelated ICU runtime.
a.binaries=[e for e in a.binaries if e[0].lower()!='icuuc.dll' and not (e[0].lower().startswith('icudt') and e[0].lower().endswith('.dll'))]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='WeChatMCP',debug=False,strip=False,upx=False,console=False,icon={str(icon)!r})
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='WeChatMCP')
''',encoding='utf8')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(output/'dist'),'--workpath',str(output/'work'),str(spec)],
        check=True,cwd=ROOT,env={**os.environ,'PYTHONHASHSEED':'0'})
    app=output/'dist/WeChatMCP';executable=app/'WeChatMCP.exe'
    # PyInstaller hooks must not silently replace our formal native SDK.
    expected=next((runtime/'axr').glob('_axr_native*.pyd'))
    actual=next((app/'_internal/axr').glob('_axr_native*.pyd'))
    if hashlib.sha256(expected.read_bytes()).digest()!=hashlib.sha256(actual.read_bytes()).digest():raise ValueError('windows_desktop_sdk_mismatch')
    checks={**check_runtime(app,output),'privacy':inspect_privacy(app)}
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True))
    value={'version':1,'platform':'windows-x64','source_revision':revision,'source_dirty':dirty,'component_source_revision':reviewed['source_revision'],
        'account_data_included':False,'vendor_codex_binary_included':False,'installed':False,'hardware_validated':False,
        'checks':checks,'files':inventory(app)}
    (output/'BUILDINFO.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')
    return value

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('output','components','qt-notices'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();value=build(args.output,args.components,args.qt_notices)
    print(json.dumps({'files':len(value['files']),'checks':value['checks'],'installed':False}))
if __name__=='__main__':main()
