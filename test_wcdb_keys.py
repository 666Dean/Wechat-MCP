# SPDX-License-Identifier: MIT
import hashlib
import ctypes as C
import hmac
import tempfile
import unittest
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
try:
    import axr
except ModuleNotFoundError as exc:
    if exc.name=='axr':raise unittest.SkipTest('AXR optional: install SDK for key qualification tests') from exc
    raise
from axr.aet import AXRError, digest
from adapters.wcdb_keys import inventory, private_database_path, provision_verified, qualify_contacts, verified_raw_key

VENDOR_SIGNATURE=b'Identifier=com.tencent.xinWeChat\nTeamIdentifier=5A4RE8SF68\nCDHash=fixture-identity\n'


def encrypted_page(key=b'k'*32, salt=b's'*16):
    page=salt+b'p'*(4032-16)
    mac_key=hashlib.pbkdf2_hmac('sha512',key,bytes(x^0x3a for x in salt),2,32)
    return page+hmac.new(mac_key,page[16:]+b'\x01\0\0\0',hashlib.sha512).digest()


class KeyTests(unittest.TestCase):
    def test_native_sqlcipher_password_import_reopens_readonly_with_normalized_key(self):
        from adapters.wcdb import CipherConnection
        library=os.environ.get('AXR_SQLCIPHER_LIBRARY')
        if not library:self.skipTest('native SQLCipher library not provided')
        password=bytes(range(32))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();path=root/'password.db'
            writer=object.__new__(CipherConnection)
            writer.lib=C.CDLL(library);writer.handle=C.c_void_p();writer._declare()
            self.assertEqual(writer.lib.sqlite3_open_v2(str(path).encode(),C.byref(writer.handle),6,None),0)
            try:
                writer.lib.sqlite3_key.argtypes=[C.c_void_p,C.c_char_p,C.c_int]
                writer.lib.sqlite3_key.restype=C.c_int
                self.assertEqual(writer.lib.sqlite3_key(writer.handle,password,len(password)),0)
                writer.query('PRAGMA cipher_compatibility=4')
                writer.query('CREATE TABLE fixture(text TEXT)')
                writer.query('INSERT INTO fixture VALUES(?)',('synthetic password fixture',))
            finally:writer.close()
            page=path.read_bytes()[:4096]
            class Secrets:
                def provision(self,ref,key):self.key=key
            secrets=Secrets()
            item=provision_verified(root,'password.db',password,secrets,page[:16].hex(),key_mode='password')
            self.assertNotEqual(secrets.key,password)
            reader=CipherConnection(path,library,secrets.key.hex(),item['cipher_profile'])
            try:
                self.assertEqual(reader.query('SELECT text FROM fixture')[0]['text'],'synthetic password fixture')
                with self.assertRaises(AXRError):reader.query('DELETE FROM fixture')
            finally:reader.close()

    def test_password_import_stores_only_verified_per_database_page_key(self):
        password=b'w'*32; salt=b's'*16
        effective=hashlib.pbkdf2_hmac('sha512',password,salt,256000,32)
        page=encrypted_page(effective,salt)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();path=root/'encrypted.db';path.write_bytes(page)
            class Secrets:
                calls=[]
                def provision(self,ref,key):self.calls.append((ref,key))
            secrets=Secrets()
            for key,mode in ((password,'raw'),(b'x'*32,'password')):
                with self.assertRaisesRegex(AXRError,'candidate_key_hmac_rejected'):
                    provision_verified(root,'encrypted.db',key,secrets,salt.hex(),key_mode=mode)
            self.assertEqual(secrets.calls,[])
            item=provision_verified(root,'encrypted.db',password,secrets,salt.hex(),key_mode='password')
            self.assertEqual(secrets.calls,[(item['key_reference'],effective)])
            self.assertEqual(item['cipher_profile'],'wcdb4-raw')
            self.assertTrue(verified_raw_key(secrets.calls[0][1],page))
            self.assertEqual(path.read_bytes(),page)
            with self.assertRaisesRegex(AXRError,'generation_changed'):
                provision_verified(root,'encrypted.db',password,secrets,('00'*16),key_mode='password')
            with self.assertRaisesRegex(AXRError,'unsupported_database_key_mode'):
                provision_verified(root,'encrypted.db',password,secrets,salt.hex(),key_mode='auto')
            self.assertEqual(len(secrets.calls),1)

    def test_cached_index_never_substitutes_account_or_key_reference(self):
        from adapters.wcdb_owner import verified_cached
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();path=root/'encrypted.db';path.write_bytes(encrypted_page())
            rows=inventory(root);ref='wcdb:'+digest([str(path),rows['encrypted.db']['salt']])
            class Secrets:
                namespace='fixture-owner'
                def get(self,key):
                    if key!=ref:raise AssertionError('must not request another key')
                    return b'k'*32
            class Store:
                directory=root;secrets=Secrets()
            value={'version':1,'account_root':str(root),'namespace':'fixture-owner',
                'keys':{'encrypted.db':{'salt':rows['encrypted.db']['salt'],'key_reference':ref,'cipher_profile':'wcdb4-raw'}}}
            index=root/'wcdb-local-index.json';index.write_text(json.dumps(value))
            self.assertEqual(set(verified_cached(Store(),root,rows)),{'encrypted.db'})
            value['keys']['encrypted.db']['path']='outside-owner-account.db'
            value['keys']['encrypted.db']['cipher_profile']='unqualified-profile';index.write_text(json.dumps(value))
            cached=verified_cached(Store(),root,rows)['encrypted.db']
            self.assertNotIn('path',cached);self.assertEqual(cached['cipher_profile'],'wcdb4-raw')
            value['keys']['encrypted.db']['key_reference']='another-owner-secret';index.write_text(json.dumps(value))
            with self.assertRaisesRegex(AXRError,'reference_mismatch'):verified_cached(Store(),root,rows)
            value['namespace']='another-owner';index.write_text(json.dumps(value))
            with self.assertRaisesRegex(AXRError,'owner_mismatch'):verified_cached(Store(),root,rows)
            value['namespace']='fixture-owner'
            for invalid in (None,[],True,{'encrypted.db':'invalid'},{'encrypted.db':{}},
                            {str(i):{} for i in range(129)}):
                value['keys']=invalid;index.write_text(json.dumps(value))
                with self.assertRaisesRegex(AXRError,'index_invalid'):verified_cached(Store(),root,rows)
            for invalid in ([],None,{'version':True}):
                index.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(AXRError,'index_invalid'):verified_cached(Store(),root,rows)

    def test_owner_tool_rejects_noninteractive_secret_provision(self):
        from adapters.wcdb_owner import main
        args=['owner','--state','fixture','--helper','fixture','--account-root','fixture','import-key','--database','fixture.db']
        with patch.object(sys,'argv',args),patch.object(sys.stdin,'isatty',return_value=False):
            with self.assertRaises(SystemExit) as exit_code:main()
            self.assertEqual(exit_code.exception.code,1)

    @unittest.skipUnless(sys.platform=='darwin','macOS startup observer fixture')
    def test_observer_preserves_kdf_and_only_private_fifo_records(self):
        observer=os.environ.get('AXR_TEST_KEY_OBSERVER');fixture=os.environ.get('AXR_TEST_KEY_FIXTURE')
        if not observer or not fixture:self.skipTest('native observer fixture paths not provided')
        self.assertTrue(Path(observer).is_file());self.assertTrue(Path(fixture).is_file())
        env={k:v for k,v in os.environ.items() if not k.startswith(('DYLD_','AXR_OWNER_'))}
        baseline=subprocess.check_output([fixture],env=env,timeout=10)
        with tempfile.TemporaryDirectory() as tmp:
            fifo=Path(tmp).resolve()/'keys.fifo';os.mkfifo(fifo,0o600)
            fd=os.open(fifo,os.O_RDONLY|os.O_NONBLOCK)
            try:
                hooked=dict(env,DYLD_INSERT_LIBRARIES=str(Path(observer).resolve()),AXR_OWNER_KEY_FIFO=str(fifo))
                self.assertEqual(subprocess.check_output([fixture],env=hooked,timeout=10),baseline)
                record=os.read(fd,4096);self.assertEqual(len(record),52);self.assertEqual(record[:4],b'AXK1')
                self.assertEqual(record[4:20],b'a'*16);self.assertEqual(record[20:],bytes.fromhex(baseline.decode().strip()))
                original=subprocess.check_output([fixture,'unmatched'],env=env,timeout=10)
                self.assertEqual(subprocess.check_output([fixture,'unmatched'],env=hooked,timeout=10),original)
                self.assertEqual(os.read(fd,4096),b'')
                fifo.chmod(0o644)
                self.assertEqual(subprocess.check_output([fixture],env=hooked,timeout=10),baseline)
                self.assertEqual(os.read(fd,4096),b'')
            finally:os.close(fd)

    @unittest.skipUnless(sys.platform=='darwin','macOS temporary application lifecycle')
    def test_capture_timeout_cleans_owned_copy_and_restores_clean_original(self):
        from adapters.wcdb_owner import observe_mac
        from types import SimpleNamespace
        launched=[]
        class Process:
            stopped=False
            def poll(self):return 0 if self.stopped else None
            def terminate(self):self.stopped=True
            def wait(self,timeout):return 0
        def launch(command,**options):
            if command[0]=='/Applications/WeChat.app/Contents/MacOS/WeChat':
                self.assertEqual(list(root.glob('wcdb-owner-*')),[])
            child=Process();launched.append((command,options,child));return child
        def run(command,**options):return SimpleNamespace(returncode=1 if command[0]=='pgrep' else 0)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();observer=root/'fixture.dylib';observer.write_bytes(b'fixture-not-loaded')
            store=SimpleNamespace(directory=root)
            rows={'contact/contact.db':{},'session/session.db':{},'message/message_0.db':{}}
            with patch('adapters.wcdb_owner.installed_signature',return_value=VENDOR_SIGNATURE),\
                 patch('adapters.wcdb_owner.subprocess.run',side_effect=run),\
                 patch('adapters.wcdb_owner.subprocess.Popen',side_effect=launch),\
                 patch.dict(os.environ,{'DYLD_INJECTED_TEST':'must-not-restore','AXR_OWNER_TEST':'must-not-restore'}):
                with self.assertRaisesRegex(AXRError,'incomplete_keys_preserved'):
                    observe_mac(store,root,rows,{},observer,timeout=0)
            self.assertEqual(len(launched),2);self.assertTrue(launched[0][2].stopped)
            self.assertFalse(launched[1][2].stopped)
            self.assertEqual(launched[1][0],['/Applications/WeChat.app/Contents/MacOS/WeChat'])
            self.assertFalse(any(k.startswith(('DYLD_','AXR_OWNER_')) for k in launched[1][1]['env']))
            self.assertEqual(list(root.glob('wcdb-owner-*')),[])

    @unittest.skipUnless(sys.platform=='darwin','macOS temporary application lifecycle')
    def test_capture_prelaunch_failures_restore_original_without_duplicate_or_bad_signature(self):
        from adapters.wcdb_owner import observe_mac
        from types import SimpleNamespace
        for failure in ('ditto','codesign','launch','interrupt'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();observer=root/'fixture.dylib';observer.write_bytes(b'fixture-not-loaded')
                store=SimpleNamespace(directory=root);launched=[]
                rows={'contact/contact.db':{},'session/session.db':{},'message/message_0.db':{}}
                def run(command,**options):
                    if command[0]==failure:raise subprocess.CalledProcessError(1,command)
                    if failure=='interrupt' and command[0]=='ditto':raise KeyboardInterrupt()
                    return SimpleNamespace(returncode=1 if command[0]=='pgrep' else 0)
                def launch(command,**options):
                    if command[0]!='/Applications/WeChat.app/Contents/MacOS/WeChat':
                        self.assertEqual(failure,'launch');raise OSError('fixture startup failed')
                    self.assertEqual(list(root.glob('wcdb-owner-*')),[])
                    launched.append((command,options));return SimpleNamespace()
                with patch('adapters.wcdb_owner.installed_signature',return_value=VENDOR_SIGNATURE),\
                     patch('adapters.wcdb_owner.subprocess.run',side_effect=run),\
                     patch('adapters.wcdb_owner.subprocess.Popen',side_effect=launch),\
                     patch.dict(os.environ,{'DYLD_INJECTED_TEST':'must-not-restore','AXR_OWNER_TEST':'must-not-restore'}):
                    expected=KeyboardInterrupt if failure=='interrupt' else (OSError if failure=='launch' else subprocess.CalledProcessError)
                    with self.assertRaises(expected):observe_mac(store,root,rows,{},observer)
                self.assertEqual(len(launched),1)
                self.assertFalse(any(k.startswith(('DYLD_','AXR_OWNER_')) for k in launched[0][1]['env']))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();observer=root/'missing.dylib';store=SimpleNamespace(directory=root)
            rows={'contact/contact.db':{},'session/session.db':{}}
            for case in ('restarted','signature-changed','already-running'):
                with self.subTest(case=case),\
                     patch('adapters.wcdb_owner.installed_signature',side_effect=[b'vendor',b'changed'] if case=='signature-changed' else [b'vendor',b'vendor']),\
                     patch('adapters.wcdb_owner.subprocess.run',side_effect=[SimpleNamespace(returncode=0)] if case=='already-running' else [SimpleNamespace(returncode=1),SimpleNamespace(returncode=0)]),\
                     patch('adapters.wcdb_owner.subprocess.Popen') as launch:
                    with self.assertRaisesRegex(AXRError,{'restarted':'observer_required','signature-changed':'signature_changed','already-running':'quit_installed'}[case]):
                        observe_mac(store,root,rows,{},observer)
                    launch.assert_not_called()

    @unittest.skipUnless(sys.platform=='darwin','macOS vendor copy qualification')
    def test_vendor_copy_must_match_before_adhoc_sign_or_launch(self):
        from adapters.wcdb_owner import observe_mac,signature_identity
        from types import SimpleNamespace
        original=b'Executable=/original\n'+VENDOR_SIGNATURE
        copy=b'Executable=/private-copy\n'+VENDOR_SIGNATURE
        self.assertEqual(signature_identity(original),signature_identity(copy))
        for invalid in (b'',VENDOR_SIGNATURE+b'CDHash=duplicate\n'):
            with self.assertRaises(AXRError):signature_identity(invalid)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();observer=root/'fixture.dylib';observer.write_bytes(b'fixture-not-loaded')
            store=SimpleNamespace(directory=root);rows={'contact/contact.db':{},'session/session.db':{}}
            commands=[];launched=[]
            def run(command,**options):
                commands.append(command);return SimpleNamespace(returncode=1 if command[0]=='pgrep' else 0)
            def launch(command,**options):
                launched.append(command);self.assertEqual(list(root.glob('wcdb-owner-*')),[])
            with patch('adapters.wcdb_owner.installed_signature',side_effect=[original,copy.replace(b'fixture-identity',b'changed'),original]),\
                 patch('adapters.wcdb_owner.subprocess.run',side_effect=run),\
                 patch('adapters.wcdb_owner.subprocess.Popen',side_effect=launch):
                with self.assertRaisesRegex(AXRError,'copy_signature_mismatch'):observe_mac(store,root,rows,{},observer)
            self.assertFalse(any(command[0]=='codesign' for command in commands))
            self.assertEqual(launched,[['/Applications/WeChat.app/Contents/MacOS/WeChat']])

    def test_wrong_key_tamper_and_generation_rejected_before_storage(self):
        page=encrypted_page()
        self.assertTrue(verified_raw_key(b'k'*32,page))
        self.assertFalse(verified_raw_key(b'x'*32,page))
        self.assertFalse(verified_raw_key(b'k'*32,page[:50]+b'x'+page[51:]))
        self.assertFalse(verified_raw_key(b'k'*32,page[:-1]))
        class Secrets:
            def __init__(self):self.saved={}
            def provision(self,ref,key):self.saved[ref]=key
        store=Secrets()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'encrypted.db').write_bytes(page)
            for key,salt in ((b'x'*32,page[:16].hex()),(b'k'*32,'00'*16)):
                with self.assertRaises(AXRError):provision_verified(root,'encrypted.db',key,store,salt)
                self.assertFalse(store.saved)
            result=provision_verified(root,'encrypted.db',b'k'*32,store,page[:16].hex())
            self.assertEqual(store.saved[result['key_reference']],b'k'*32)
            self.assertNotIn(b'k'*32,repr(result).encode())

    def test_inventory_is_bounded_and_rejects_escape_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'encrypted.db').write_bytes(encrypted_page())
            (root/'plain.db').write_bytes(b'SQLite format 3\0')
            self.assertEqual(set(inventory(root)),{'encrypted.db'})
            for maximum in (0,-1,True,129):
                with self.assertRaises(AXRError):inventory(root,maximum)
            class Store:
                def provision(self,*args):raise AssertionError('must not store')
            for rel in ('../encrypted.db',str(root/'encrypted.db'),'encrypted.txt'):
                with self.assertRaises(AXRError):provision_verified(root,rel,b'k'*32,Store(),'73'*16)
            if os.name=='nt':
                for rel in ('C:outside.db','\\outside.db','\\\\server\\share\\outside.db'):
                    with self.assertRaisesRegex(AXRError,'outside_account'):private_database_path(root,rel)
            (root/'message').mkdir();(root/'message'/'message_0.db').write_bytes(encrypted_page())
            self.assertIn('message/message_0.db',inventory(root))
            (root/'second.db').write_bytes(encrypted_page())
            with self.assertRaises(AXRError):inventory(root,1)
            try:(root/'linked.db').symlink_to(root/'encrypted.db')
            except OSError:self.skipTest('symlink creation unavailable')
            with self.assertRaises(AXRError):inventory(root)

    def test_contact_binding_rejects_duplicates_and_closes_on_failure(self):
        class DB:
            closed=False
            def __init__(self,*args,**kwargs):pass
            def query(self,sql,args=()):
                if sql=='BEGIN':return []
                if sql.startswith('PRAGMA'):return [{'name':x} for x in ('username','nick_name','remark','delete_flag')]
                if 'username IN (' in sql:return [{'username':name} for name in DB.account_matches]
                if sql.startswith('SELECT username FROM'):return [{'username':'fixture-owner'}]
                self.last_sql=sql
                self_outer.assertIn("username NOT LIKE '%@chatroom'",sql)
                self_outer.assertIn("delete_flag=0",sql)
                return [{'username':name,'nick_name':'fixture','remark':''} for name in DB.matches]
            def close(self):DB.closed=True
        self_outer=self
        with patch('adapters.wcdb_keys.open_database',DB):
            for matches in ([],['first','second'],['group@chatroom']):
                DB.matches=matches;DB.closed=False
                with self.assertRaises(AXRError):qualify_contacts('fixture','fixture',b'k'*32,'fixture-owner',['fixture'])
                self.assertTrue(DB.closed)
            DB.matches=['fixture-peer']
            bound=qualify_contacts('fixture','fixture',b'k'*32,'fixture-owner',['fixture'])
            self.assertEqual(bound[0]['conversation_id'],'fixture-peer')
            DB.account_matches=['fixture-owner']
            kwargs={'account_root':Path('fixture-owner_installation/db_storage')}
            self.assertEqual(len(qualify_contacts('fixture','fixture',b'k'*32,'fixture-owner',['fixture'],**kwargs)),1)
            for accounts in ([],['other-owner'],['fixture-owner','fixture-owner_installation']):
                DB.account_matches=accounts
                with self.assertRaisesRegex(AXRError,'directory_identity'):
                    qualify_contacts('fixture','fixture',b'k'*32,'fixture-owner',['fixture'],**kwargs)
            with self.assertRaises(AXRError):qualify_contacts('fixture','fixture',b'k'*32,'fixture-owner',['fixture','alias'])


if __name__=='__main__':unittest.main()
