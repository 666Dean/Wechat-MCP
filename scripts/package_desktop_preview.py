# SPDX-License-Identifier: MIT
"""Build an account-free macOS Developer Preview; never install or authorize.

The distributable contains the desktop runtime, not an owner's authority
deployment, a vendor Codex application, credentials, databases or live state.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import zipfile

NAME='WeChat MCP Developer Preview'
VERSION='0.1.0-dp1'
TAG='v0.1.0-dp1'
MINIMUM='27.0'
ROOT=Path(__file__).resolve().parent.parent

def run(args,**kwargs):
    return subprocess.run([str(a) for a in args],check=True,**kwargs)

def text(args):return subprocess.check_output([str(a) for a in args],text=True).strip()

def license_inventory(destination,upstream):
    destination.mkdir(parents=True)
    inventory=[]
    for distribution in sorted(importlib.metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
        name=distribution.metadata['Name'];licenses=[]
        for entry in distribution.files or ():
            parts=Path(str(entry)).parts
            if not any(p.endswith('.dist-info') for p in parts):continue
            if not any(p.lower().startswith(('license','copying','notice')) for p in parts):continue
            source=Path(distribution.locate_file(entry))
            if not source.is_file():continue
            relative=Path(name)/Path(*parts[1:]);target=destination/relative
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);licenses.append(str(relative))
        inventory.append({'name':name,'version':distribution.version,'license':distribution.metadata.get('License-Expression') or distribution.metadata.get('License',''),'notices':licenses})
    for source in ('LICENSE','LICENSES.md','THIRD_PARTY_NOTICES.md','AXR/LICENSE','AXR/THIRD_PARTY_NOTICES.md'):
        target=destination/'project'/source;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/source,target)
    # Runtime/linked library notices are not Python distribution metadata.
    shutil.copytree(ROOT/'AXR/licenses',destination/'project/AXR/licenses')
    shutil.copytree(upstream/'QtForPython',destination/'QtForPython')
    for name,source in [('Python',upstream/'Python-LICENSE.txt'),('OpenSSL',Path('/opt/homebrew/opt/openssl@4/LICENSE.txt'))]:
        if not source.is_file():raise RuntimeError('missing runtime notice: '+name)
        target=destination/name/'LICENSE.txt';target.parent.mkdir(parents=True);shutil.copy2(source,target)
    (destination/'BUILD-DEPENDENCIES.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    (destination/'SOURCE-AND-REPLACEMENT.md').write_text('''# Source and library replacement

The combined AXR-linked application is distributed under AGPL-3.0-only;
individual MIT and third-party notices remain in force. Matching project source
and build scripts accompany the release as a separate source archive.

Qt/PySide/Shiboken are dynamically linked, not statically embedded. Their
original LGPL/GPL and component notices are included. Debugging/reverse
engineering to test permitted library modifications is not restricted by this
project. A developer may replace compatible arm64 Qt/PySide libraries in a copy
of the .app (Contents/Frameworks/PySide6 and shiboken6), then rebuild/re-sign that
copy. Such changes do not grant any AXR service authority.

Exact upstream sources for the 6.10.2 binary components:
https://download.qt.io/archive/qt/6.10/6.10.2/single/
https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.2-src/
Python 3.14.6: https://www.python.org/downloads/release/python-3146/
OpenSSL 4.0.0: https://github.com/openssl/openssl/releases/tag/openssl-4.0.0
PyInstaller bootloader: https://github.com/pyinstaller/pyinstaller/tree/v6.22.0
The build dependency inventory also includes build-only packages; it is not a
claim that every installed build package is included in the runtime.
''')

def inspect_bundle(app):
    """Refuse outside links, a private user path, and non-relocatable dylibs."""
    forbidden=(str(Path.home()).encode(),b'/var/folders/')
    binaries=0
    for path in app.rglob('*'):
        if path.is_symlink():
            if not path.resolve().is_relative_to(app.resolve()):raise RuntimeError('external bundle symlink')
            continue
        if not path.is_file():continue
        data=path.read_bytes()
        if any(value in data for value in forbidden):raise RuntimeError('private path in artifact: '+str(path.relative_to(app)))
        if path.suffix=='.zip':
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if any(value in archive.read(name) for value in forbidden):raise RuntimeError('private path in zip entry: '+name)
        if data[:4] not in (b'\xcf\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xfe\xed\xfa\xcf',b'\xbe\xba\xfe\xca'):continue
        binaries+=1
        dependencies=text(['/usr/bin/otool','-L',path]).splitlines()[1:]
        for line in dependencies:
            dependency=line.strip().split(' (',1)[0]
            if dependency.startswith('/') and not dependency.startswith(('/System/Library/','/usr/lib/')):raise RuntimeError('non-relocatable native dependency')
        loads=text(['/usr/bin/otool','-l',path]).splitlines()
        for line in loads:
            if line.strip().startswith('minos '):
                version=tuple(map(int,line.split()[1].split('.')))
                if version[:2]>(27,0):raise RuntimeError('minimum OS exceeds release declaration')
    # Compressed Python archives need a separate scan; a raw binary scan cannot
    # see their code constants, tracebacks or embedded data.
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(app/'Contents/MacOS/WeChatMCP'))
    checked=0
    for name,entry in archive.toc.items():
        if entry[-1]=='z':
            nested=archive.open_embedded_archive(name)
            for module in nested.toc:
                data=nested.extract(module,raw=True)
                if data and any(value in data for value in forbidden):raise RuntimeError('private path in Python module: '+module)
                checked+=1
        elif entry[-1] in ('s','m','M','x'):
            data=archive.extract(name)
            if any(value in data for value in forbidden):raise RuntimeError('private path in Python entry: '+name)
            checked+=1
    run(['/usr/bin/codesign','--verify','--deep','--strict',app],capture_output=True)
    return {'native_images':binaries,'python_archive_entries':checked,'external_bundle_links':0,'private_user_paths':0,'non_system_absolute_dependencies':0}

def disk_image(output,app):
    payload=output/'image';payload.mkdir()
    shutil.copytree(app,payload/app.name,symlinks=True)
    (payload/'Applications').symlink_to('/Applications')
    shutil.copy2(ROOT/'docs/releases/0.1.0-dp1.zh-CN.md',payload/'发行说明.md')
    shutil.copy2(output/'BUILDINFO.json',payload/'BUILDINFO.json')
    (payload/'.metadata_never_index').touch()
    (payload/'安装与功能.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>WeChat MCP Developer Preview</title>
<style>body{margin:0;background:#eef1ef;color:#1d302c;font:16px -apple-system,BlinkMacSystemFont,sans-serif;line-height:1.8}main{max-width:800px;margin:48px auto;padding:40px;background:#fff;border:1px solid #e4e8e4;border-radius:24px}h1{font-size:32px;line-height:1.3;margin:12px 0}h2{font-size:20px;margin-top:32px}.badge{color:#285c4d;font-size:13px;background:#eff5f0;border-radius:16px;padding:7px 12px}.note{background:#faf3e6;border-radius:14px;padding:18px}a{color:#285c4d}li{margin:8px 0}small{color:#74817b}</style>
<main><span class="badge">macOS · Apple Silicon · Developer Preview 1</span><h1>WeChat MCP<br>Developer Preview</h1><p>把消息与助理接在一起，访问与行动始终由你决定。</p>
<h2>开始使用</h2><ol><li>将 App 拖入 Applications，然后从应用程序启动。</li><li>按首次向导连接本人已准备的 AXR 安全服务、Codex 与微信权限。</li><li>先选择少量测试联系人，核对授权与实际结果，再逐步扩大范围。</li></ol>
<div class="note"><strong>这是开发者预览版。</strong>当前包需要 macOS 27.0 或更新系统、Apple Silicon。桌面运行时已包含，但本人账号的安全服务部署与凭据准备仍需另行完成；不包含他人的配置、密钥或授权。此包未经 Apple 公证，系统可能要求本人核对并批准打开，不要关闭系统整体安全检查。</div>
<h2>本版提供</h2><ul><li>Qt 对话工作台、实际模型与思考强度选择、人设和回复风格。</li><li>授权私聊文字读取、入站合批回复、独立人工草稿面板与本人任务入口。</li><li>精确范围、本机确认、停止撤权、已有输入保护，以及 Unknown 不重发。</li><li>空闲发送或仅微信本已前台时发送，避免主动抢占其他应用。</li></ul>
<h2>使用前请了解</h2><p>可靠的无前台发送尚未跑通；普通键盘路径仍需微信前台和临时剪贴板。最近的新发送测试没有取得精确数据库确认，保留 Unknown、没有重发。本版不承诺所有设备自动发送成功或全天无人值守。</p>
<p>附件、简报与待办的独立服务迁移仍有缺口；不包含支付、转账、朋友圈、小程序、群管理或附件自动发送。</p>
<p><a href="发行说明.md">完整功能、安装前提与已知限制</a> · <a href="https://github.com/666Dean/Wechat-MCP/releases/tag/v0.1.0-dp1">GitHub Release、对应源码和校验</a> · <a href="https://github.com/666Dean/Wechat-MCP/blob/v0.1.0-dp1/docs/INDEPENDENT_SERVICE.md">本机安全服务部署</a></p>
<small>Powered by Stellaria AXR · 本项目不是腾讯、微信或 OpenAI 的官方产品。组合发行遵循 AGPL-3.0-only；依赖原有许可及替换说明在 App 的 Contents/Resources/licenses 中。</small></main></html>''',encoding='utf-8')
    dmg=output/('WeChat-MCP-Developer-Preview-'+VERSION+'-macOS-arm64.dmg')
    run(['/usr/bin/hdiutil','create','-volname',NAME,'-srcfolder',payload,'-format','UDZO',dmg])
    run(['/usr/bin/hdiutil','verify',dmg],capture_output=True)
    mount=output/'mounted';mount.mkdir()
    run(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,dmg],capture_output=True)
    try:
        mounted=mount/app.name;inspect_bundle(mounted)
        report=output/'mounted-runtime-check.json'
        env={'HOME':str(output/'smoke-home'),'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'en_US.UTF-8','TMPDIR':str(output/'smoke-tmp')}
        run([mounted/'Contents/MacOS/WeChatMCP','--runtime-check','--check-output',report],cwd=output/'smoke-home',env=env,timeout=40)
        run([mounted/'Contents/MacOS/WeChatMCP','--fixture','--capture',output/'mounted-fixture.png','--exit-after','5'],cwd=output/'smoke-home',env=env,timeout=45)
        if not (output/'mounted-fixture.png').is_file():raise RuntimeError('mounted Qt render missing')
    finally:run(['/usr/bin/hdiutil','detach',mount],capture_output=True)
    buildinfo=json.loads((output/'BUILDINFO.json').read_text())
    buildinfo['checks'].update(dmg_verified=True,readonly_mount_runtime=json.loads(report.read_text()),
                              mounted_fixture_render=True)
    (output/'BUILDINFO.json').write_text(json.dumps(buildinfo,indent=2)+'\n')
    shutil.copy2(ROOT/'docs/releases/0.1.0-dp1.zh-CN.md',output/'RELEASE-NOTES.zh-CN.md')
    assets=[dmg,output/('WeChat-MCP-'+VERSION+'-source.tar.gz'),output/'BUILDINFO.json',output/'RELEASE-NOTES.zh-CN.md']
    (output/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in assets))
    return dmg

def build(output,native,notices):
    if sys.platform!='darwin' or platform.machine()!='arm64':raise RuntimeError('macOS arm64 builder required')
    if output.exists():raise RuntimeError('output must be new')
    run(['git','diff','--exit-code'],cwd=ROOT,capture_output=True);run(['git','diff','--cached','--exit-code'],cwd=ROOT,capture_output=True)
    commit=text(['git','-C',ROOT,'rev-parse','HEAD']);output.mkdir(parents=True)
    inputs=output/'inputs';runtime=inputs/'runtime';runtime.mkdir(parents=True)
    shutil.copytree(ROOT/'AXR/axr',runtime/'axr',ignore=lambda d,n:[p for p in n if p=='__pycache__' or (Path(d,p).is_file() and not p.endswith('.py'))])
    shutil.copy2(native,runtime/'axr'/native.name)
    licenses=inputs/'licenses';license_inventory(licenses,notices)
    from desktop.app_icon import mac_icon
    icon=mac_icon(ROOT/'desktop/icon.svg',inputs/'AppIcon.icns')
    buildinfo={'name':NAME,'version':VERSION,'tag':TAG,'source_commit':commit,'platform':'macOS','architecture':'arm64','minimum_macos':MINIMUM,
               'python':platform.python_version(),'qt':'6.10.2','signature':'ad-hoc; not notarized','account_data_included':False,'authority_deployment_included':False,'vendor_codex_binary_included':False}
    (inputs/'BUILDINFO.json').write_text(json.dumps(buildinfo,indent=2)+'\n')
    datas=[(str(p),'desktop') for p in (ROOT/'desktop').iterdir() if p.suffix in ('.qml','.svg') or p.name=='qmldir']
    datas += [(str(licenses),'licenses'),(str(inputs/'BUILDINFO.json'),'.')]
    spec=inputs/'preview.spec'
    spec.write_text(f'''# Generated from the reviewed packaging script.
a=Analysis([{str(ROOT/'desktop/release_entry.py')!r}],pathex={[str(runtime),str(ROOT)]!r},binaries=[],datas={datas!r},
 hiddenimports=['PySide6.QtQuick','PySide6.QtQuickControls2','PySide6.QtSvg','PySide6.QtNetwork','PySide6.QtOpenGL','scripts.install_authority_macos','scripts.register_authority_service'],
 excludes=['pytest','numpy','scipy','torch','pandas','matplotlib','tkinter','PyQt5','PyQt6','wx','wxauto4','win32com','apsw'])
# Pip's PEP 610 install-origin metadata is not needed by the application and can
# contain the builder's private checkout URI. Keep runtime version/license data.
a.datas=[entry for entry in a.datas if not entry[0].endswith('.dist-info/direct_url.json')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='WeChatMCP',debug=False,strip=True,upx=False,console=False,target_arch='arm64',codesign_identity=None)
coll=COLLECT(exe,a.binaries,a.datas,strip=True,upx=False,name='WeChatMCP')
app=BUNDLE(coll,name={NAME+'.app'!r},icon={str(icon)!r},bundle_identifier='studio.stellaria.wechat-mcp.preview',
 info_plist={{'CFBundleDisplayName':{NAME!r},'CFBundleShortVersionString':'0.1.0','CFBundleVersion':'1','LSMinimumSystemVersion':{MINIMUM!r},'NSHighResolutionCapable':True}})
''')
    env={**os.environ,'PYTHONHASHSEED':'0','PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR':'1'}
    run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',output/'dist','--workpath',output/'work',spec],env=env,cwd=ROOT)
    app=output/'dist'/(NAME+'.app');checks=inspect_bundle(app)
    clean_home=output/'smoke-home';clean_home.mkdir();temporary=output/'smoke-tmp';temporary.mkdir()
    environment={'HOME':str(clean_home),'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'en_US.UTF-8','TMPDIR':str(temporary)}
    report=output/'runtime-check.json'
    run([app/'Contents/MacOS/WeChatMCP','--runtime-check','--check-output',report],env=environment,cwd=clean_home,timeout=40)
    checks['clean_environment_runtime']=json.loads(report.read_text())
    (output/'BUILDINFO.json').write_text(json.dumps({**buildinfo,'checks':checks},indent=2)+'\n')
    source=output/('WeChat-MCP-'+VERSION+'-source.tar.gz')
    run(['git','-C',ROOT,'archive','--format=tar.gz','--prefix=WeChat-MCP-'+VERSION+'/',commit,'-o',source])
    return disk_image(output,app)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--native',type=Path,required=True);p.add_argument('--notices',type=Path,required=True)
    a=p.parse_args();print(build(a.output.absolute(),a.native.resolve(strict=True),a.notices.resolve(strict=True)))

if __name__=='__main__':main()
