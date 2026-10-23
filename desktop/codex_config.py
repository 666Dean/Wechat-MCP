# SPDX-License-Identifier: MIT
"""Reviewable, scoped Codex MCP installation with compare-before-write restoration."""
import hashlib
import json
import re
import time
import tomllib
import sys
from pathlib import Path
from axr.aet import AXRError
from axr.storage import private_directory
from axr import _axr_native as native

NAME='wechat_axr'

def native_frontend():
    if sys.platform=='win32':return str(Path(native.windows_installation_root())/'axr-frontend.exe')
    return '/Library/Application Support/Stellaria AXR/AXR MCP.app/Contents/MacOS/axr-frontend'

def native_registered(config=None):
    path=Path(config or Path.home()/'.codex/config.toml')
    try:
        if path.is_symlink():return False
        value=tomllib.loads(path.read_text()).get('mcp_servers',{}).get(NAME,{})
        return (value.get('command')==native_frontend()
                and value.get('args')==['--mcp'] and value.get('enabled',True) is True and value.get('required',False) is False)
    except (OSError,ValueError,AttributeError):return False

def native_snippet():
    return '\n'.join(['[mcp_servers.wechat_axr]',
        'command = '+json.dumps(native_frontend()),
        'args = ["--mcp"]','enabled = true','required = false','startup_timeout_sec = 15','tool_timeout_sec = 90',''])


def snippet(python,server,state):
    args=[str(Path(server).resolve()),'--axr-state',str(Path(state).resolve()),'--broker']
    quote=lambda x:json.dumps(str(x),ensure_ascii=False)
    return '\n'.join(['[mcp_servers.wechat_axr]','command = '+quote(Path(python).absolute()),
        'args = '+json.dumps(args,ensure_ascii=False),'enabled = true','required = false',
        'startup_timeout_sec = 15','tool_timeout_sec = 90',''])


def replace_section(text, section):
    parsed=tomllib.loads(text)
    # Nested env tables could leave stale authority/launch settings. Refuse them.
    pattern=r'(?m)^\[mcp_servers\.wechat_axr\][^\n]*\n'
    nested=r'(?m)^\[mcp_servers\.(?:wechat_axr\.|["\']wechat_axr["\'])'
    if re.search(nested,text):raise AXRError('codex_nested_config_requires_manual_review')
    match=re.search(pattern,text)
    if match:
        end=re.search(r'(?m)^\[',text[match.end():])
        stop=match.end()+end.start() if end else len(text)
        output=text[:match.start()]+section+'\n'+text[stop:]
    else:
        if NAME in parsed.get('mcp_servers',{}):raise AXRError('codex_config_section_not_canonical')
        output=text.rstrip()+'\n\n'+section
    actual=tomllib.loads(output)
    before={**parsed};after={**actual}
    before['mcp_servers']={k:v for k,v in before.get('mcp_servers',{}).items() if k!=NAME}
    after['mcp_servers']={k:v for k,v in after.get('mcp_servers',{}).items() if k!=NAME}
    if before!=after:raise AXRError('codex_unrelated_settings_changed')
    return output


def install(config, section, expected_sha256, backup_root):
    path=Path(config)
    if path.is_symlink():raise AXRError('codex_config_link_rejected')
    original=path.read_bytes() if path.exists() else b''
    if hashlib.sha256(original).hexdigest()!=expected_sha256:raise AXRError('codex_config_changed_review_again')
    output=replace_section(original.decode('utf8'),section).encode('utf8')
    root=private_directory(backup_root)
    backup=root/('codex-config-'+str(time.time_ns())+'.toml')
    if not native.durable_write(str(backup),original):raise AXRError('codex_backup_failed')
    if (path.read_bytes() if path.exists() else b'')!=original:raise AXRError('codex_config_changed_review_again')
    path.parent.mkdir(parents=True,exist_ok=True)
    if not native.durable_write(str(path),output):raise AXRError('codex_config_write_failed')
    return {'backup':str(backup),'installed_sha256':hashlib.sha256(output).hexdigest()}


def restore(config,backup,installed_sha256):
    path=Path(config);source=Path(backup)
    if path.is_symlink() or source.is_symlink():raise AXRError('codex_config_link_rejected')
    current=path.read_bytes()
    if hashlib.sha256(current).hexdigest()!=installed_sha256:raise AXRError('codex_config_changed_cannot_restore')
    raw=source.read_bytes();tomllib.loads(raw.decode('utf8'))
    if not native.durable_write(str(path),raw):raise AXRError('codex_config_restore_failed')
    return {'restored':True}
