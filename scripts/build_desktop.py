# SPDX-License-Identifier: MIT
"""Create a local development app launcher. Runtime is required; no signing claim."""
import argparse
import os
import plistlib
import shlex
import sys
from pathlib import Path


def build(output,python,root,state,helper=None,platform=sys.platform):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    args=[str(Path(python).absolute()),'-m','desktop.app','--state',str(Path(state).resolve())]
    if helper:args+=['--helper',str(Path(helper).resolve())]
    if platform=='darwin':
        app=output/'WeChat MCP Desktop.app';contents=app/'Contents';(contents/'MacOS').mkdir(parents=True,exist_ok=True)
        (contents/'Resources').mkdir(exist_ok=True)
        metadata={'CFBundleName':'WeChat MCP Desktop','CFBundleDisplayName':'WeChat MCP Desktop',
            'CFBundleIdentifier':'studio.stellaria.wechat-mcp-desktop','CFBundleVersion':'0.7.0',
            'CFBundleShortVersionString':'0.7.0','CFBundlePackageType':'APPL','CFBundleExecutable':'WeChatMCP',
            'NSHighResolutionCapable':True,'CFBundleIconFile':'AppIcon.icns'}
        from desktop.app_icon import mac_icon
        mac_icon(Path(root)/'desktop/icon.svg',contents/'Resources/AppIcon.icns')
        (contents/'Info.plist').write_bytes(plistlib.dumps(metadata))
        launcher=contents/'MacOS/WeChatMCP'
        launcher.write_text('#!/bin/sh\ncd '+shlex.quote(str(Path(root).resolve()))+' || exit 1\nexec '+shlex.join(args)+'\n')
        launcher.chmod(0o755);return app
    if platform=='win32':
        path=output/'WeChat MCP Desktop.cmd'
        pythonw=Path(python).with_name('pythonw.exe')
        if pythonw.is_file():args[0]=str(pythonw.absolute())
        if any('"' in x or '%' in x or '\n' in x for x in [*args,str(root)]):raise ValueError('unsupported launcher path')
        path.write_text('@echo off\ncd /d "'+str(Path(root).resolve())+'"\nstart "WeChat MCP Desktop" '+
            ' '.join('"'+x+'"' for x in args)+'\n',encoding='utf8');return path
    raise ValueError('Desktop launchers support macOS and Windows')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='.local-private/apps')
    p.add_argument('--state',required=True);p.add_argument('--helper');args=p.parse_args()
    import PySide6.QtQuick
    print(build(args.output,sys.executable,Path(__file__).resolve().parents[1],args.state,args.helper))


if __name__=='__main__':main()
