# SPDX-License-Identifier: MIT
"""Read-only official app-server metadata client. No composer or private app IPC."""
import asyncio,json,shutil
from axr.aet import AXRError

async def _request(method,params):
    binary=shutil.which('codex')
    if not binary:raise AXRError('codex_cli_required')
    process=await asyncio.create_subprocess_exec(binary,'app-server','--listen','stdio://',
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=1024*1024)
    async def send(value):process.stdin.write((json.dumps(value)+'\n').encode());await process.stdin.drain()
    try:
        await send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'wechat_axr_desktop','version':'0.9.0'}}})
        for _ in range(50):
            line=await asyncio.wait_for(process.stdout.readline(),10)
            if not line:raise AXRError('codex_metadata_disconnected')
            row=json.loads(line)
            if row.get('id')==1:
                await send({'method':'initialized'});await send({'id':2,'method':method,'params':params})
            if row.get('id')==2:
                if 'error' in row:raise AXRError('codex_metadata_unavailable')
                return row['result']
        raise AXRError('codex_metadata_budget')
    finally:
        if process.returncode is None:process.terminate()
        await process.wait()

def threads(cursor=None):
    data=asyncio.run(_request('thread/list',{'limit':50,'cursor':cursor,'sortKey':'updated_at',
        'useStateDbOnly':True,'sourceKinds':['appServer','cli','exec','unknown']}))
    return {'threads':[{'id':t['id'],'title':t.get('name') or '未命名对话'} for t in data['data']],
            'next_cursor':data.get('nextCursor')}


def models():
    data=asyncio.run(_request('model/list',{'limit':100}))
    return {'models':[{'id':m['model'],'title':m['displayName'],
        'efforts':[e['reasoningEffort'] for e in m.get('supportedReasoningEfforts',[])],
        'default_effort':m.get('defaultReasoningEffort','')} for m in data['data'] if not m.get('hidden')]}
