# SPDX-License-Identifier: MIT
"""Interactive real MCP review client; no raw transcript or message file.

JSON stdin: catalog, page(index), ack(summary), status, quit.
--show-content explicitly forwards only exact owner-approved context to caller.
Run one broker per state, alongside the authenticated owner_review controller.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(state,show):
    root=Path(__file__).resolve().parents[1]
    args=StdioServerParameters(command=sys.executable,args=[str(root/'server.py'),'--axr-state',str(state),'--manual-replies'],cwd=str(root))
    with open(os.devnull,'w') as errors:
        async with stdio_client(args,errlog=errors) as (r,w):
            async with ClientSession(r,w) as c:
                await c.initialize();bindings=[];cursors={};pending=None;completed=set()
                async def call(tool,args):
                    value=await c.call_tool(tool,args)
                    if value.is_error:raise ValueError('mcp_operation_failed')
                    return json.loads(value.content[0].text)
                while True:
                    line=await asyncio.to_thread(sys.stdin.readline)
                    if not line:break
                    try:
                        request=json.loads(line);op=request['op']
                        if op=='quit':break
                        if op=='status':value=await call('wechat_status',{})
                        elif op=='catalog':
                            if pending:raise ValueError('review_page_pending')
                            bindings=[];offset=0
                            while True:
                                data=await call('wechat_find_conversations',{'offset':offset,'limit':100})
                                bindings.extend(data['conversations']);offset=data['next_offset']
                                if offset is None:break
                            value={'conversations':[{'index':i,**b} for i,b in enumerate(bindings)],'coverage':data['account_review']}
                        elif op=='page':
                            if pending:raise ValueError('review_page_pending')
                            index=request['index']
                            if type(index) is not int or not 0<=index<len(bindings) or index in completed:raise ValueError('review_index_invalid_or_finished')
                            data=await call('wechat_request_task',{'conversation_id':bindings[index]['conversation_id'],
                                'limit':6,'cursor':cursors.get(index)})
                            if 'task_id' not in data:raise ValueError('review_read_not_completed')
                            pending=(index,data)
                            for attempt in range(50):
                                context=await call('wechat_get_task_context',{'task_id':data['task_id']})
                                if context.get('body_disclosed') is True:break
                                await asyncio.sleep(.2)
                            else:raise ValueError('review_exact_approval_pending')
                            result=data['read_job']['result']
                            value={'index':index,'name':bindings[index]['display_name'],'kind':bindings[index].get('kind'),
                                'count':result['count'],'scanned':result['scanned'],'has_more':result['has_more'],
                                'budget_truncated':result['budget_truncated'],'body_disclosed':True}
                            if show:value['messages']=context['disclosure']['result']['messages']
                        elif op=='ack':
                            if not pending:raise ValueError('review_no_pending_page')
                            index,data=pending
                            value=await call('wechat_acknowledge_review',{'task_id':data['task_id'],'summary':request.get('summary','')})
                            cursors[index]=data['read_job']['result']['cursor']
                            if not data['read_job']['result']['has_more']:completed.add(index)
                            pending=None;value.update(index=index,conversations_finished=len(completed))
                        else:raise ValueError('review_command_unknown')
                        print(json.dumps(value,ensure_ascii=False),flush=True)
                    except (ValueError,KeyError,TypeError):
                        print(json.dumps({'error':'review_command_failed','pending_page':pending is not None}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True);p.add_argument('--show-content',action='store_true')
    args=p.parse_args()
    try:asyncio.run(run(Path(args.state).resolve(),args.show_content))
    except KeyboardInterrupt:pass
    except Exception:p.exit(1,'MCP review stopped; no raw diagnostic or body is logged.\n')


if __name__=='__main__':main()
