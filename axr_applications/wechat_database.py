# SPDX-License-Identifier: MIT
"""Fixed native WCDB consumer facade. No Python key or SQL entry point.

The host supplies the already sealed resource/commit check. This facade is not
an MCP tool and cannot create permissions. Each page contains one stable source.
"""
import json
from dataclasses import asdict
from axr.aet import AXRError, Resource, canonical, digest
from axr import _axr_native as native
from adapters.wcdb import decode_text

class NativeDatabase:
    def __init__(self, consumer, account):
        if not isinstance(consumer, native.CredentialConsumer):
            raise AXRError('wechat_native_consumer_required')
        self.consumer = consumer
        self.account = account

    def use(self, identity, request, check):
        resource = Resource('wechat', self.account, identity)
        result = native.CredentialConsumer.use(self.consumer, canonical(asdict(resource)).decode(),
                    'database.query', canonical(request).decode(), check)
        value = json.loads(result)
        for shard in value:
            for row in shard['rows']:
                for key, cell in list(row.items()):
                    if type(cell) is dict and set(cell) == {'blob_hex'}:
                        row[key] = bytes.fromhex(cell['blob_hex'])
        return value

    def search(self, identity, *, check, since=0, until=2**63-1, after=None, limit=6):
        if type(limit) is not int or not 1 <= limit <= 100 or since < 0 or until < since:
            raise AXRError('wechat_native_search_range')
        # Cursors are per owner-enrolled shard, never caller paths or SQL.
        batches = self.use(identity, {'kind':'messages','since':since,'until':until,
                'limit':limit,'after':[-1,-1]}, check) if not after else None
        if after:
            # The consumer accepts a per-shard cursor map, rather than dropping
            # other shards' positions when the earliest page is merged.
            batches = self.use(identity, {'kind':'messages','since':since,'until':until,
                    'limit':limit,'cursors':after}, check)
        rows=[]
        for shard in batches:
            for row in shard['rows']:
                text = decode_text(row['body'], row['compression']) if row['type'] == 1 else None
                rows.append({**row,'text':text,'shard':shard['shard'],
                    'outgoing':row['sender']==self.account if text is not None else None,
                    'reference':digest([self.account,identity,shard['shard'],row['local_id'],row['created']])})
        rows.sort(key=lambda r:(r['created'],r['local_id'],r['shard']))
        cursor=dict(after or {})
        for row in rows[:limit]:cursor[row['shard']]=[row['created'],row['local_id']]
        return {'messages':[{k:v for k,v in row.items() if k not in ('body','compression','direction')}
                for row in rows[:limit] if row['text'] is not None],
                'cursor':cursor,'has_more':len(rows)>limit,'scanned':len(rows[:limit]),
                'complete_history':False,'delivery_confirmed':False}

    def navigation(self, identity, kind, check, **parameters):
        if kind not in ('draft','unique_draft','recent'):
            raise AXRError('wechat_native_navigation_operation')
        batches=self.use(identity, {'kind':kind,**parameters}, check)
        if len(batches)!=1:raise AXRError('wechat_native_navigation_shard_required')
        return batches[0]['rows']

def actor_records(page):
    """Trusted source snapshot for an incoming actor; no raw credential fields.

    Local owner reads and model disclosure are distinct operations. Construct
    this snapshot before sealing disclosure so a model cannot relabel sources.
    """
    from axr_integration.content_safety import mask_credentials
    rows=page.get('messages')
    if type(rows) is not list or len(rows)>6:raise AXRError('wechat_actor_page_budget')
    records=[]
    for row in rows:
        if row.get('outgoing') is not False or not isinstance(row.get('text'),str):continue
        safe,_=mask_credentials(row['text'])
        if len(safe.encode())>4000:raise AXRError('wechat_actor_text_requires_bounded_page')
        records.append({'reference':row['reference'],'text':safe,'data_class':'personal'})
    if len(canonical(records))>24000:raise AXRError('wechat_actor_page_budget')
    return records
