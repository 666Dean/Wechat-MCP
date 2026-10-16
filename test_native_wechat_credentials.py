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
        self.assertEqual(self.api.sqlite3_exec(handle,sql.encode(),None,None,None),0)
        self.api.sqlite3_close_v2(handle)
        self.config={'account_id':self.account,'sqlcipher_library':self.library,
          'credential_namespace':'Fixture.NeverUsed','resources':[asdict(self.resource)],
          'shards':[{'id':'fixture-message','path':str(self.path),'role':'message','cipher_profile':'sqlcipher4','key_reference':'fixture-key'},
                    {'id':'fixture-session','path':str(self.path),'role':'session','cipher_profile':'sqlcipher4','key_reference':'fixture-key'},
                    {'id':'fixture-general','path':str(self.path),'role':'general','cipher_profile':'sqlcipher4','key_reference':'fixture-key'}]}
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
    def test_wrong_key_is_failure_not_empty(self):
        bad=self.module.fixture_consumer('fixture-handler',canonical(self.config).decode(),{'fixture-key':b'\0'*32})
        with self.assertRaises(RuntimeError):native.CredentialConsumer.use(bad,canonical(asdict(self.resource)).decode(),'database.query','{"kind":"messages"}',lambda:None)
    def test_foreign_sender_denied(self):
        # A private table containing an unrecognized stable sender must fail.
        self.config['account_id']='wxid_missing';self.config['resources']=[asdict(Resource('wechat','wxid_missing',self.peer))]
        other=self.module.fixture_consumer('fixture-handler',canonical(self.config).decode(),{'fixture-key':self.key})
        with self.assertRaisesRegex(RuntimeError,'self_identity'):native.CredentialConsumer.use(other,canonical(self.config['resources'][0]).decode(),'database.query','{"kind":"messages"}',lambda:None)
