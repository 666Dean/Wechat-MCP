# SPDX-License-Identifier: MIT
"""Read-only official app-server metadata client. No composer or private app IPC."""
import asyncio,json,shutil,sys
from pathlib import Path
from axr.aet import AXRError

def codex_binary():
    binary=shutil.which('codex')
    if binary:return binary
    # Finder launches do not inherit the interactive shell PATH. Reuse a
    # known installed runtime; never launch a login shell or modify Codex data.
    if sys.platform=='darwin':
        for path in (Path('/Library/Application Support/Stellaria AXR/AXR Authority.app/Contents/Resources/CodexCLI.app/Contents/MacOS/codex'),
                     Path('/Library/Application Support/Stellaria AXR/Codex Provider/codex'),
                     Path('/Applications/Codex.app/Contents/Resources/codex'),
                     Path('/opt/homebrew/bin/codex'),Path('/usr/local/bin/codex'),
                     Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex')):
            if path.is_file():return str(path)
    raise AXRError('codex_cli_required')

async def _request(method,params):
    binary=codex_binary()
    process=await asyncio.create_subprocess_exec(binary,'app-server','--listen','stdio://',
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=1024*1024)
    async def send(value):process.stdin.write((json.dumps(value)+'\n').encode());await process.stdin.drain()
    async def receive():
        await send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'wechat_axr_desktop','version':'0.9.0'}}})
        for _ in range(50):
            line=await process.stdout.readline()
            if not line:raise AXRError('codex_metadata_disconnected')
            row=json.loads(line)
            if row.get('id')==1:
                if 'error' in row:raise AXRError('codex_metadata_unavailable')
                await send({'method':'initialized'});await send({'id':2,'method':method,'params':params})
            if row.get('id')==2:
                if 'error' in row:raise AXRError('codex_metadata_unavailable')
                return row['result']
        raise AXRError('codex_metadata_budget')
    try:
        return await asyncio.wait_for(receive(),20)
    except TimeoutError:raise AXRError('codex_metadata_timeout') from None
    except (ValueError,KeyError,BrokenPipeError,ConnectionError):raise AXRError('codex_metadata_unavailable') from None
    finally:
        if process.returncode is None:
            try:process.terminate()
            except ProcessLookupError:pass
        try:await asyncio.wait_for(process.wait(),2)
        except TimeoutError:process.kill();await process.wait()

def threads(cursor=None):
    data=asyncio.run(_request('thread/list',{'limit':50,'cursor':cursor,'sortKey':'updated_at',
        'useStateDbOnly':True,'sourceKinds':['appServer','vscode','cli','exec','unknown']}))
    return {'threads':[{'id':t['id'],'title':t.get('name') or '未命名对话'} for t in data['data']],
            'next_cursor':data.get('nextCursor')}


def models():
    data=asyncio.run(_request('model/list',{'limit':100}))
    return {'models':[{'id':m['model'],'title':m['displayName'],
        'efforts':[e['reasoningEffort'] for e in m.get('supportedReasoningEfforts',[])],
        'default_effort':m.get('defaultReasoningEffort','')} for m in data['data'] if not m.get('hidden')]}
