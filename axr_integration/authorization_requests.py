# SPDX-License-Identifier: MIT
"""Agent proposals, local owner decisions. Proposal creation never grants access."""
import time,uuid
from axr.aet import AXRError

def catalog(service):
    from adapters.wcdb_catalog import discover
    result=discover(service.store,service.config,statistics=False)
    excluded={'filehelper','weixin','newsapp','fmessage','tmessage','floatbottle','medianote','qqmail','qmessage','feedsapp','voiceinputapp','blogapp','brandsessionholder','notification_messages'}
    bindings=[b for b in result['conversations'] if b.get('kind') in ('private','self') and b['conversation_id'] not in excluded and '@' not in b['conversation_id'] and not b['conversation_id'].startswith('gh_')]
    if len(bindings)<2:raise AXRError('qualified_private_catalog_required')
    return bindings

def add_bindings(service,bindings):
    for binding in bindings:
        service.bindings[binding['conversation_id']]=binding
        service.adapter.bindings[binding['conversation_id']]=binding

def init(service):
    service.journal.db.execute('CREATE TABLE IF NOT EXISTS authorization_requests(id TEXT PRIMARY KEY,principal TEXT,state TEXT,expires REAL,payload BLOB)')

def request(service,target,reason):
    if not isinstance(target,str) or not target.strip() or len(target.encode())>512 or not isinstance(reason,str) or len(reason.encode())>2000:
        raise AXRError('authorization_request_invalid')
    init(service);rows=service.journal.db.execute("SELECT count(*) FROM authorization_requests WHERE principal=? AND state='AwaitingOwner' AND expires>?",(service.principal,time.time())).fetchone()[0]
    if rows>=20:raise AXRError('authorization_request_capacity')
    key=str(uuid.uuid4());value={'id':key,'target':target,'reason':reason,'operations':['messages.read','reply.prepare','messages.send'],
        'destination':service.destination,'scope':'private_reply','authority_granted':False}
    service.journal.db.execute('INSERT INTO authorization_requests VALUES(?,?,?,?,?)',
        (key,service.principal,'AwaitingOwner',time.time()+600,service.store.vault.seal(value,key+':authorization')))
    return {'request_id':key,'state':'AwaitingOwner','authority_granted':False,'next_step':'Ask owner to review in Desktop pending authorizations, then query status; never self-grant.'}

def list_requests(service):
    init(service)
    rows=service.journal.db.execute('SELECT * FROM authorization_requests WHERE principal=? AND expires>? ORDER BY rowid DESC LIMIT 20',(service.principal,time.time())).fetchall()
    return [{**service.store.vault.open(r['payload'],r['id']+':authorization'),'state':r['state'],'expires':r['expires']} for r in rows]

def status(service,key):
    value=next((v for v in list_requests(service) if v['id']==key),None)
    if value is None:raise AXRError('authorization_request_missing_or_expired')
    return {'request_id':key,'state':value['state'],'authority_granted':value['state']=='Approved'}
