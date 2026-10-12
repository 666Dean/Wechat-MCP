# SPDX-License-Identifier: MIT
"""Owner-authenticated account inventory. Metadata only, no message bodies."""
import hashlib
import re
import time
from pathlib import Path
from axr.aet import AXRError,identifier
from .wcdb import CipherConnection,SCHEMAS
from .wcdb_keys import inventory,qualify_contacts
from .wcdb_owner import verified_cached


def paged(db,sql,parameters=(),maximum=16384):
    offset=0
    while True:
        rows=db.query(sql+' LIMIT 500 OFFSET ?',(*parameters,offset))
        if offset+len(rows)>maximum:raise AXRError('account_catalog_budget_exceeded')
        yield from rows
        if len(rows)<500:break
        offset+=500


def discover(store,policy):
    snapshot_until=int(time.time())
    roots={Path(s['path']).absolute().parent.parent for s in policy['database']['shards']}
    if len(roots)!=1:raise AXRError('qualified_single_account_root_required')
    root=roots.pop();rows=inventory(root);keys=verified_cached(store,root,rows)
    contact=keys.get('contact/contact.db')
    if not contact:raise AXRError('verified_contact_key_required')
    library=policy['database']['sqlcipher_library'];account=policy['account_id']
    qualify_contacts(rows['contact/contact.db']['path'],library,store.secrets.get(contact['key_reference']),
                     account,[account],account_root=root)
    db=CipherConnection(rows['contact/contact.db']['path'],library,store.secrets.get(contact['key_reference']).hex(),contact['cipher_profile'])
    try:
        labels={r['username']:r['remark'] or r['nick_name'] or r['username'] for r in
                paged(db,'SELECT username,nick_name,remark FROM contact ORDER BY username')}
    finally:db.close()
    bindings={};shards=[];unmapped=0;table_count=0;records=0;texts=0
    available=[rel for rel in rows if Path(rel).parent==Path('message') and Path(rel).stem.removeprefix('message_').isdigit()]
    missing=[rel for rel in available if rel not in keys]
    for rel in sorted(available):
        if rel not in keys:continue
        item=keys[rel];shard={'path':str(rows[rel]['path']),**item};shards.append(shard)
        db=CipherConnection(shard['path'],library,store.secrets.get(item['key_reference']).hex(),item['cipher_profile'])
        try:
            names=list(paged(db,'SELECT rowid,user_name FROM Name2Id ORDER BY rowid'))
            if sum(r['user_name']==account for r in names)!=1:raise AXRError('account_identity_not_present_in_shard')
            mapping={}
            for r in names:
                name=identifier(r['user_name']);table='Msg_'+hashlib.md5(name.encode()).hexdigest()
                if table in mapping and mapping[table]!=name:raise AXRError('conversation_hash_identity_collision')
                mapping[table]=name
            tables=list(paged(db,"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%' ORDER BY name",maximum=4096))
            for row in tables:
                table=row['name'];table_count+=1
                if not re.fullmatch('Msg_[0-9a-f]{32}',table) or table not in mapping:
                    unmapped+=1;continue
                columns={r['name'] for r in db.query('PRAGMA table_info("'+table+'")')}
                required=set(SCHEMAS['v4'].values())-{'Msg_','rowid'}
                if not required<=columns:raise AXRError('wcdb_schema_not_qualified')
                stats=db.query('SELECT count(*) AS records,sum(local_type=1) AS texts,min(create_time) AS first,max(create_time) AS last FROM "'+table+'" WHERE create_time<=?',(snapshot_until,))[0]
                name=mapping[table]
                kind='self' if name==account else 'group' if name.endswith('@chatroom') else 'public' if name.startswith('gh_') else 'private'
                b=bindings.setdefault(name,{'conversation_id':name,'display_name':labels.get(name,name),
                    'schema':'v4','data_class':'personal','kind':kind,'records':0,'text_records':0,'tables':0})
                b['records']+=stats['records'];b['text_records']+=stats['texts'] or 0;b['tables']+=1
                records+=stats['records'];texts+=stats['texts'] or 0
                if len(bindings)>4096:raise AXRError('account_catalog_budget_exceeded')
        finally:db.close()
    if not shards:raise AXRError('verified_message_shard_required')
    return {'conversations':sorted(bindings.values(),key=lambda b:(b['kind'],b['display_name'],b['conversation_id'])),
        'database':{'sqlcipher_library':library,'shards':shards},
        'coverage':{'message_shards_available':len(available),'message_shards_verified':len(shards),
            'missing_key_shards':len(missing),'message_tables':table_count,'unmapped_tables':unmapped,
            'records':records,'text_records':texts,'nontext_records':records-texts,
            'snapshot_until':snapshot_until,'atomic_snapshot':False,
            'catalog_complete':not missing and unmapped==0,'server_history_complete':False}}
