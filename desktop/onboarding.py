# SPDX-License-Identifier: MIT
"""First-run checks report observed prerequisites, never mint authority."""
from axr_integration.assistant_settings import valid_thread

def assessment(snapshot,assistant,protocol=False):
    status=snapshot.get('status',{});permissions=status.get('permissions',{})
    checks=[('service','本地服务',status.get('operational') is True),
            ('database','微信数据连接',permissions.get('database') is True),
            ('accessibility','设备控制',permissions.get('accessibility') is True),
            ('model','回复助理',status.get('inference',{}).get('ready') is True),
            ('thread','Codex 对话',valid_thread(assistant.get('thread_id',''))),
            ('scope','会话授权',status.get('owner_authorized') is True),
            ('protocol','MCP 连接',protocol is True)]
    return {'ready':all(ready for _,_,ready in checks),
            'checks':[{'id':key,'title':title,'ready':ready} for key,title,ready in checks]}

def protocol_check():
    import asyncio
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def check():
        async with asyncio.timeout(20):
            params=StdioServerParameters(command='/Library/Application Support/Stellaria AXR/AXR MCP.app/Contents/MacOS/axr-frontend',args=['--mcp'])
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize();tools=await session.list_tools();status=await session.call_tool('wechat_status',{})
                    return not status.is_error and 'wechat_send_message' in {tool.name for tool in tools.tools}
    return asyncio.run(check())
