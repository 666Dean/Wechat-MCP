# SPDX-License-Identifier: MIT
"""Bounded, source-local, in-memory coalescing. Never restores unsent input."""
import time
from axr.aet import AXRError

class BurstBuffer:
    quiet_seconds=3.0
    max_wait=12.0
    ttl=900
    def __init__(self):self.pending={};self.context={}
    def clear(self):self.pending.clear();self.context.clear()
    def add(self,identity,rows,has_more,now=None):
        now=time.monotonic() if now is None else now
        self.context={k:v for k,v in self.context.items() if now-v['at']<self.ttl}
        previous=self.context.get(identity,{'rows':[]})['rows']
        seen={r['reference'] for r in previous};fresh=[r for r in rows if r['reference'] not in seen]
        incoming=[r for r in fresh if r.get('outgoing') is False]
        if incoming:
            if identity not in self.pending and len(self.pending)>=128:raise AXRError('wechat_burst_capacity')
            batch=self.pending.setdefault(identity,{'rows':[],'first':now,'last':now,'has_more':False})
            known={r['reference'] for r in batch['rows']}
            addition=[]
            for row in incoming:
                if row['reference'] not in known:addition.append(row);known.add(row['reference'])
            if len(batch['rows'])+len(addition)>96:raise AXRError('wechat_burst_capacity')
            batch['rows'].extend(addition)
            batch['last']=now
        if identity in self.pending:self.pending[identity]['has_more']=has_more
        self.context[identity]={'rows':(previous+fresh)[-12:],'at':now}
        if len(self.context)>128:
            oldest=min(self.context,key=lambda k:self.context[k]['at']);self.context.pop(oldest)
    def ready(self,now=None):
        now=time.monotonic() if now is None else now;result=[]
        for identity,b in list(self.pending.items()):
            if now-b['first']>=self.ttl:self.pending.pop(identity);continue
            if b['has_more'] or (now-b['last']<self.quiet_seconds and now-b['first']<self.max_wait):continue
            rows=b['rows'][:6];remaining=b['rows'][6:]
            refs={r['reference'] for r in b['rows']};first=rows[0]
            older=[r for r in self.context.get(identity,{'rows':[]})['rows']
                   if r['reference'] not in refs and (r.get('created',0),r.get('local_id',0))<(first.get('created',0),first.get('local_id',0))]
            context=[{**r,'context_only':True} for r in older[-(6-len(rows)):]] if len(rows)<6 else []
            result.append((identity,context+rows,rows))
            if remaining:b.update(rows=remaining,first=now,last=now)
            else:self.pending.pop(identity)
        return result
