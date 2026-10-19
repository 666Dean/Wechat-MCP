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

def empty_saved_draft(value, size):
    """Recognize storage absence, never interpret nonempty user text as empty."""
    if value is None:return size is None
    if size==0 and value in ('',b''):return True
    return False

def saved_draft_metadata(row):
    """Owner-only structure diagnostics; never return text or unknown labels."""
    value=row.get('draft');out={'type':type(value).__name__,'bytes':row.get('size')}
    if not isinstance(value,(str,bytes)):return out
    try:text=value.decode('utf-8',errors='strict') if isinstance(value,bytes) else value
    except UnicodeError:return {**out,'encoding':'binary'}
    out.update(characters=len(text),control_characters=sum(ord(c)<32 for c in text),
               whitespace_characters=sum(c.isspace() for c in text),
               nul_characters=text.count('\0'),format='text')
    try:obj=json.loads(text)
    except (ValueError,RecursionError):obj=None
    if isinstance(obj,dict):
        known={'text','plainText','content','type','version','atuserlist'}
        out.update(format='json',fields={k if k in known else 'other':type(v).__name__ for k,v in obj.items()},
                   empty_string_values=sum(v=='' for v in obj.values()))
    elif text.lstrip().startswith('<') and '<!' not in text and '<?' not in text:
        from xml.etree import ElementTree as ET
        try:
            nodes=list(ET.fromstring(text).iter());known={'msg','draft','text','content','type','atuserlist','richtext','img','p','br'}
            out.update(format='xml',nodes=len(nodes),tags=sorted({n.tag if n.tag in known else 'other' for n in nodes}),
                       nonempty_text_nodes=sum(bool((n.text or '').strip()) for n in nodes),attributes=sum(len(n.attrib) for n in nodes))
        except ET.ParseError:out['format']='unrecognized_markup'
    return out

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
        if kind not in ('draft','unique_draft','recent','session_schema'):
            raise AXRError('wechat_native_navigation_operation')
        batches=self.use(identity, {'kind':kind,**parameters}, check)
        if len(batches)!=1:raise AXRError('wechat_native_navigation_shard_required')
        rows=batches[0]['rows']
        if kind=='draft':
            # SQL NULL with a NULL length means WeChat has no saved draft.
            # A budget-rejected large draft also returns NULL content, but its
            # nonzero length must remain blocked and must never be overwritten.
            rows=[{**row,'draft':''} if 'size' in row and empty_saved_draft(row.get('draft'),row['size']) else row for row in rows]
        return rows

    def activity(self, *, since, after, check, limit=128):
        batches=self.use(self.account,{'kind':'activity','since':since,'after':after,'limit':limit},check)
        if len(batches)!=1:raise AXRError('wechat_native_activity_shard_required')
        rows=batches[0]['rows'];previous=tuple(after)
        for row in rows:
            if (set(row)!={'conversation_id','updated','local_id'} or type(row['conversation_id']) is not str
                or type(row['updated']) is not int or type(row['local_id']) is not int
                or (row['updated'],row['conversation_id'])<=previous):raise AXRError('wechat_native_activity_schema')
            previous=(row['updated'],row['conversation_id'])
        selected=rows[:limit]
        return {'rows':selected,'after':[selected[-1]['updated'],selected[-1]['conversation_id']] if selected else after,
                'has_more':len(rows)>limit}

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
