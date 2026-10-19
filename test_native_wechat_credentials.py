# SPDX-License-Identifier: MIT
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from dataclasses import asdict
from axr.aet import Resource, canonical
from axr import _axr_native as native

class NativeWeChatCredentialsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('WECHAT_TEST_NATIVE_CONSUMER')
        library=os.environ.get('AXR_SQLCIPHER_LIBRARY')
        if not path or not library:raise unittest.SkipTest('native WCDB test build/library required')
        spec=importlib.util.spec_from_file_location('axr_applications._wechat_credentials',path)
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)
        if not hasattr(cls.module,'fixture_consumer'):raise unittest.SkipTest('formal build has no fixture key constructor')
        cls.library=library
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.account='wxid_owner_fixture';self.peer='wxid_peer_fixture'
        self.resource=Resource('wechat',self.account,self.peer)
        self.path=Path(self.temp.name)/'encrypted.db';self.key=b'\x37'*32
        self.api=C.CDLL(self.library);handle=C.c_void_p()
        self.api.sqlite3_open_v2.argtypes=[C.c_char_p,C.POINTER(C.c_void_p),C.c_int,C.c_void_p]
        self.api.sqlite3_exec.argtypes=[C.c_void_p,C.c_char_p,C.c_void_p,C.c_void_p,C.c_void_p]
        self.api.sqlite3_key.argtypes=[C.c_void_p,C.c_void_p,C.c_int]
        self.api.sqlite3_close_v2.argtypes=[C.c_void_p]
        self.assertEqual(self.api.sqlite3_open_v2(os.fsencode(self.path),C.byref(handle),6,None),0)
        raw_key=("x'"+self.key.hex()+"'").encode()
        self.assertEqual(self.api.sqlite3_key(handle,raw_key,len(raw_key)),0)
        table='Msg_'+hashlib.md5(self.peer.encode()).hexdigest()
        sql=f'''CREATE TABLE Name2Id(user_name TEXT);INSERT INTO Name2Id VALUES('{self.account}'),('{self.peer}');
CREATE TABLE {table}(server_id INTEGER,create_time INTEGER,local_type INTEGER,message_content BLOB,real_sender_id INTEGER,WCDB_CT_message_content INTEGER);
INSERT INTO {table} VALUES(41,100,1,'hello native',2,0),(42,101,1,'owner reply',1,0);
CREATE TABLE SessionTable(username TEXT,draft TEXT);INSERT INTO SessionTable VALUES('{self.peer}','exact fixture draft');
CREATE TABLE SearchRecent(username TEXT,query TEXT,last_click_time INTEGER);INSERT INTO SearchRecent VALUES('{self.peer}','Fixture peer',100);'''
        sql+=f"CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT,delete_flag INTEGER);INSERT INTO contact VALUES('{self.account}','Fixture owner','',0),('{self.peer}','Fixture peer','',0);"
        self.assertEqual(self.api.sqlite3_exec(handle,sql.encode(),None,None,None),0)
        self.api.sqlite3_close_v2(handle)
        self.config={'account_id':self.account,'sqlcipher_library':self.library,
          'credential_namespace':'Fixture.NeverUsed','resources':[asdict(self.resource)],
          'shards':[{'id':'fixture-message','path':str(self.path),'role':'message','cipher_profile':'sqlcipher4','key_reference':'fixture-key'},
                    {'id':'fixture-session','path':str(self.path),'role':'session','cipher_profile':'sqlcipher4','key_reference':'fixture-key'},
                    {'id':'fixture-general','path':str(self.path),'role':'general','cipher_profile':'sqlcipher4','key_reference':'fixture-key'}]}
        self.config['shards'].append({'id':'fixture-contact','path':str(self.path),'role':'contact','cipher_profile':'sqlcipher4','key_reference':'fixture-key'})
        self.consumer=self.module.fixture_consumer('fixture-handler',canonical(self.config).decode(),{'fixture-key':self.key})
    def use(self,request,resource=None,check=lambda:None):
        return json.loads(native.CredentialConsumer.use(self.consumer,canonical(asdict(resource or self.resource)).decode(),'database.query',canonical(request).decode(),check))
    def test_encrypted_page_and_native_facade(self):
        from axr_applications.wechat_database import NativeDatabase
        db=NativeDatabase(self.consumer,self.account)
        page=db.search(self.peer,check=lambda:None,limit=1)
        self.assertEqual(page['messages'][0]['text'],'hello native');self.assertFalse(page['messages'][0]['outgoing']);self.assertTrue(page['has_more'])
        page2=db.search(self.peer,check=lambda:None,after=page['cursor'],limit=1)
        self.assertEqual(page2['messages'][0]['text'],'owner reply');self.assertTrue(page2['messages'][0]['outgoing'])
        self.assertFalse(page2['has_more']);self.assertNotIn('secret',str(page2));self.assertFalse(hasattr(self.consumer,'get_key'))
    def test_target_message_state_is_fixed_metadata_without_body_or_caller_sql(self):
        rows=self.use({'kind':'message_state'})
        row=rows[0]['rows'][0]
        self.assertEqual({k:v for k,v in row.items() if k not in ('latest_metadata','target_schemas','journal_mode','name_index_schema','target_name_index','send_index_schema','full_scan','source_path_fingerprint','source_identity','auxiliary_schemas')},{'table_present':1,'records':2,'latest_created':101,'latest_local_id':2})
        self.assertEqual(row['target_name_index'],[{'name_id':2}])
        self.assertEqual([s['name'] for s in row['target_schemas']],['Msg_'+hashlib.md5(self.peer.encode()).hexdigest()])
        self.assertIn({'name':'message_content','type':'BLOB'},row['target_schemas'][0]['columns'])
        self.assertEqual(row['latest_metadata'][0]['sender_is_self'],1)
        self.assertEqual(row['latest_metadata'][1]['sender_is_peer'],1)
        self.assertNotIn('hello native',str(rows))
        with self.assertRaisesRegex(RuntimeError,'request_invalid'):self.use({'kind':'message_state','table':'contact'})
    def test_session_state_selects_only_exact_target_metadata(self):
        handle=C.c_void_p();self.assertEqual(self.api.sqlite3_open_v2(os.fsencode(self.path),C.byref(handle),2,None),0)
        try:
            key=("x'"+self.key.hex()+"'").encode();self.assertEqual(self.api.sqlite3_key(handle,key,len(key)),0)
            sql="ALTER TABLE SessionTable ADD COLUMN last_timestamp INTEGER DEFAULT 102; ALTER TABLE SessionTable ADD COLUMN last_msg_locald_id INTEGER DEFAULT 3; ALTER TABLE SessionTable ADD COLUMN last_msg_type INTEGER DEFAULT 1; ALTER TABLE SessionTable ADD COLUMN last_msg_sub_type INTEGER DEFAULT 0;"
            self.assertEqual(self.api.sqlite3_exec(handle,sql.encode(),None,None,None),0)
        finally:self.api.sqlite3_close_v2(handle)
        self.assertEqual(self.use({'kind':'session_state'})[0]['rows'],[{'updated':102,'local_id':3,'type':1,'subtype':0}])
        with self.assertRaisesRegex(RuntimeError,'request_invalid'):self.use({'kind':'session_state','username':'someone_else'})
    def test_message_group_index_metadata_is_bound_to_exact_name_index(self):
        handle=C.c_void_p();self.assertEqual(self.api.sqlite3_open_v2(os.fsencode(self.path),C.byref(handle),2,None),0)
        try:
            key=("x'"+self.key.hex()+"'").encode();self.assertEqual(self.api.sqlite3_key(handle,key,len(key)),0)
            sql="CREATE TABLE MessageGroupTimeInfo(chatname_id INTEGER,group_id TEXT,create_time INTEGER,initial_sort_seq INTEGER,birth_time INTEGER); INSERT INTO MessageGroupTimeInfo VALUES(2,'fixture-peer-group',104,1000,103),(1,'other-source-group',105,2000,104);"
            self.assertEqual(self.api.sqlite3_exec(handle,sql.encode(),None,None,None),0)
        finally:self.api.sqlite3_close_v2(handle)
        result=self.use({'kind':'message_state'})[0]['rows'][0]
        self.assertEqual(result['group_index_size'],[{'records':2}])
        rows=result['target_groups']
        self.assertEqual(rows,[{'group_id':'fixture-peer-group','create_time':104,'initial_sort_seq':1000,'birth_time':103}])
        self.assertNotIn('other-source-group',str(rows))
    def test_database_error_decisions_remain_bounded_and_callback_revoke_is_preserved(self):
        from axr_applications.wechat_database import NativeDatabase
        from axr.aet import AXRError
        db=NativeDatabase(self.consumer,self.account)
        for error,expected in [(RuntimeError('wcdb_native_read_failed'),'wcdb_native_read_failed'),
                (RuntimeError('private arbitrary content'),'wechat_native_database_failed'),
                (AXRError('wechat_scope_stopped_or_expired'),'wechat_scope_stopped_or_expired')]:
            with self.subTest(expected=expected):
                def check():raise error
                with self.assertRaisesRegex(AXRError,'^'+expected+'$'):db.search(self.peer,check=check)
    def test_compressed_text_affinity_crosses_the_native_boundary_as_bytes(self):
        import zstandard
        from axr_applications.wechat_database import NativeDatabase
        content=zstandard.ZstdCompressor().compress('中文 compressed fixture'.encode()).hex()
        handle=C.c_void_p();self.assertEqual(self.api.sqlite3_open_v2(os.fsencode(self.path),C.byref(handle),2,None),0)
        try:
            key=("x'"+self.key.hex()+"'").encode();self.assertEqual(self.api.sqlite3_key(handle,key,len(key)),0)
            table='Msg_'+hashlib.md5(self.peer.encode()).hexdigest()
            sql=f"INSERT INTO {table} VALUES(43,102,1,CAST(X'{content}' AS TEXT),1,4)"
            self.assertEqual(self.api.sqlite3_exec(handle,sql.encode(),None,None,None),0)
        finally:self.api.sqlite3_close_v2(handle)
        page=NativeDatabase(self.consumer,self.account).search(self.peer,since=102,check=lambda:None)
        self.assertEqual(page['messages'][0]['text'],'中文 compressed fixture')
    @unittest.skipUnless(__import__('sys').platform=='darwin','macOS encrypted snapshot diagnostic')
    def test_encrypted_snapshot_reads_committed_wal_and_cleans_private_copy(self):
        before=set(Path('/private/tmp').glob('axr-encrypted-wcdb-*'))
        handle=C.c_void_p();self.assertEqual(self.api.sqlite3_open_v2(os.fsencode(self.path),C.byref(handle),2,None),0)
        try:
            key=("x'"+self.key.hex()+"'").encode();self.assertEqual(self.api.sqlite3_key(handle,key,len(key)),0)
            table='Msg_'+hashlib.md5(self.peer.encode()).hexdigest()
            sql=f"PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; INSERT INTO {table} VALUES(44,103,1,'WAL fixture',1,0)"
            self.assertEqual(self.api.sqlite3_exec(handle,sql.encode(),None,None,None),0)
            result=self.use({'kind':'message_state','isolated_snapshot':True})
            self.assertEqual(result[0]['rows'][0]['records'],3)
            self.assertEqual(result[0]['rows'][0]['latest_created'],103)
            self.assertEqual(set(Path('/private/tmp').glob('axr-encrypted-wcdb-*')),before)
        finally:self.api.sqlite3_close_v2(handle)
    def test_owner_selected_file_validates_encrypted_database_without_key_export(self):
        if not hasattr(self.module,'fixture_verify_owner_file'):self.skipTest('macOS fixture importer required')
        source=Path(self.temp.name).resolve()/'owner-selected.txt';source.write_text(self.key.hex())
        config={**self.config,'shards':[{**s,'salt':self.path.read_bytes()[:16].hex()} for s in self.config['shards']]}
        reference={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        result=json.loads(self.module.fixture_verify_owner_file(canonical(config).decode(),canonical(reference).decode()))
        self.assertEqual(result['verified_credentials'],4);self.assertFalse(result['raw_keys_exported'])
        self.assertNotIn(self.key.hex(),str(result))
        source.write_text('00'*32)
        with self.assertRaisesRegex(RuntimeError,'file_changed'):
            self.module.fixture_verify_owner_file(canonical(config).decode(),canonical(reference).decode())
        reference['sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        with self.assertRaises(RuntimeError):self.module.fixture_verify_owner_file(canonical(config).decode(),canonical(reference).decode())
    def test_owner_selected_salt_map_and_redirect_rejection(self):
        if not hasattr(self.module,'fixture_verify_owner_file'):self.skipTest('macOS fixture importer required')
        salt=self.path.read_bytes()[:16].hex();source=Path(self.temp.name).resolve()/'owner-selected.json'
        source.write_text(json.dumps({'keys':{salt:self.key.hex()}}))
        config={**self.config,'shards':[{**s,'salt':salt} for s in self.config['shards']]}
        reference={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        result=json.loads(self.module.fixture_verify_owner_file(canonical(config).decode(),canonical(reference).decode()))
        self.assertEqual(result['verified_credentials'],4)
        link=source.with_name('redirect.json');link.symlink_to(source);reference['path']=str(link)
        with self.assertRaisesRegex(RuntimeError,'path_invalid'):
            self.module.fixture_verify_owner_file(canonical(config).decode(),canonical(reference).decode())
    def test_scope_and_sql_export_denied(self):
        with self.assertRaises(RuntimeError):self.use({'kind':'messages'},Resource('wechat',self.account,'wxid_other'))
        for kind in ('sql','export','key','shell'):
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):self.use({'kind':kind,'sql':'DROP TABLE Name2Id'})
    def test_checks_before_and_after_native_operation(self):
        calls=[];self.use({'kind':'draft'},check=lambda:calls.append(True));self.assertEqual(len(calls),2)
        def stop():raise RuntimeError('revoked')
        with self.assertRaisesRegex(RuntimeError,'revoked'):self.use({'kind':'messages'},check=stop)
    def test_navigation_exact_witness(self):
        rows=self.use({'kind':'unique_draft','text':'exact fixture draft'})[0]['rows'];self.assertEqual(len(rows),1)
        with self.assertRaisesRegex(RuntimeError,'unique_draft'):self.use({'kind':'unique_draft','text':'partial'})
    def test_fixed_session_schema_has_no_values_and_rejects_parameters(self):
        rows=self.use({'kind':'session_schema'})[0]['rows']
        self.assertEqual(rows,[{'name':'username','type':'TEXT'},{'name':'draft','type':'TEXT'}])
        with self.assertRaisesRegex(RuntimeError,'request_invalid'):self.use({'kind':'session_schema','table':'contact'})
    def test_empty_null_draft_is_distinct_from_a_budget_rejected_draft(self):
        from axr_applications.wechat_database import NativeDatabase
        handle=C.c_void_p();self.assertEqual(self.api.sqlite3_open_v2(os.fsencode(self.path),C.byref(handle),6,None),0)
        raw_key=("x'"+self.key.hex()+"'").encode();self.assertEqual(self.api.sqlite3_key(handle,raw_key,len(raw_key)),0)
        try:
            self.assertEqual(self.api.sqlite3_exec(handle,b'UPDATE SessionTable SET draft=NULL',None,None,None),0)
            db=NativeDatabase(self.consumer,self.account)
            self.assertEqual(db.navigation(self.peer,'draft',lambda:None),[{'draft':'','size':None}])
            self.assertEqual(self.api.sqlite3_exec(handle,b"UPDATE SessionTable SET draft=replace(hex(zeroblob(10000)),'0','x')",None,None,None),0)
            row=db.navigation(self.peer,'draft',lambda:None)[0]
            self.assertIsNone(row['draft']);self.assertEqual(row['size'],20000)
        finally:self.api.sqlite3_close_v2(handle)
    def test_wrong_key_is_failure_not_empty(self):
        bad=self.module.fixture_consumer('fixture-handler',canonical(self.config).decode(),{'fixture-key':b'\0'*32})
        with self.assertRaises(RuntimeError):native.CredentialConsumer.use(bad,canonical(asdict(self.resource)).decode(),'database.query','{"kind":"messages"}',lambda:None)
    def test_foreign_sender_denied(self):
        # A private table containing an unrecognized stable sender must fail.
        self.config['account_id']='wxid_missing';self.config['resources']=[asdict(Resource('wechat','wxid_missing',self.peer))]
        other=self.module.fixture_consumer('fixture-handler',canonical(self.config).decode(),{'fixture-key':self.key})
        with self.assertRaisesRegex(RuntimeError,'self_identity'):native.CredentialConsumer.use(other,canonical(self.config['resources'][0]).decode(),'database.query','{"kind":"messages"}',lambda:None)
    def test_native_catalog_paging_and_budget(self):
        rows=self.use({'kind':'catalog','offset':0,'limit':1})
        self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]['rows']),1)
        self.assertEqual(rows[0]['rows'][0]['username'],self.account)
        with self.assertRaisesRegex(RuntimeError,'catalog_budget'):self.use({'kind':'catalog','offset':-1})
    def test_activity_is_bounded_local_metadata_for_the_account_resource(self):
        handle=C.c_void_p();self.assertEqual(self.api.sqlite3_open_v2(os.fsencode(self.path),C.byref(handle),2,None),0)
        raw_key=("x'"+self.key.hex()+"'").encode();self.assertEqual(self.api.sqlite3_key(handle,raw_key,len(raw_key)),0)
        try:
            sql=f"ALTER TABLE SessionTable ADD COLUMN last_timestamp INTEGER; ALTER TABLE SessionTable ADD COLUMN last_msg_locald_id INTEGER; UPDATE SessionTable SET last_timestamp=101,last_msg_locald_id=7; INSERT INTO SessionTable VALUES('{self.account}','private owner draft',101,8),('unenrolled','private foreign draft',102,9);"
            self.assertEqual(self.api.sqlite3_exec(handle,sql.encode(),None,None,None),0)
        finally:self.api.sqlite3_close_v2(handle)
        owner=Resource('wechat',self.account,self.account)
        self.config['resources'].append(asdict(owner))
        self.consumer=self.module.fixture_consumer('fixture-handler',canonical(self.config).decode(),{'fixture-key':self.key})
        from axr_applications.wechat_database import NativeDatabase
        db=NativeDatabase(self.consumer,self.account)
        page=db.activity(since=100,after=[0,''],check=lambda:None,limit=1)
        self.assertTrue(page['has_more']);self.assertEqual(set(page['rows'][0]),{'conversation_id','updated','local_id'})
        second=db.activity(since=100,after=page['after'],check=lambda:None,limit=1)
        self.assertFalse(second['has_more']);self.assertNotIn('private',str(page)+str(second))
        self.assertEqual({page['rows'][0]['conversation_id'],second['rows'][0]['conversation_id']},{self.account,self.peer})
        request={'kind':'activity','since':100,'after':[0,''],'limit':1}
        with self.assertRaisesRegex(RuntimeError,'account_resource'):self.use(request)
        for change,code in (({'since':-1},'activity_range'),({'limit':129},'activity_range'),
                ({'after':[0,5]},'activity_range'),({'sql':'SELECT draft'},'request_invalid'),
                ({'identities':['unenrolled']},'request_invalid')):
            with self.subTest(change=change),self.assertRaisesRegex(RuntimeError,code):self.use({**request,**change},owner)
