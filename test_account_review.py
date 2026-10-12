# SPDX-License-Identifier: MIT
import hashlib
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from axr.aet import AXRError,digest
from adapters import wcdb_catalog
import test_manual_reply


class CatalogTests(unittest.TestCase):
    def test_real_catalog_sql_maps_private_group_public_and_reports_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'account'/ 'db_storage';(root/'contact').mkdir(parents=True);(root/'message').mkdir()
            contact=root/'contact/contact.db';shard=root/'message/message_0.db'
            db=sqlite3.connect(contact)
            db.execute('CREATE TABLE contact(username,nick_name,remark,delete_flag)')
            db.execute('INSERT INTO contact VALUES(?,?,?,0)',('peer','fixture peer',''));db.commit();db.close()
            db=sqlite3.connect(shard);db.execute('CREATE TABLE Name2Id(user_name)')
            for name in ('account','peer','fixture@chatroom','gh_fixture'):
                db.execute('INSERT INTO Name2Id VALUES(?)',(name,))
            for name in ('peer','fixture@chatroom','gh_fixture'):
                table='Msg_'+hashlib.md5(name.encode()).hexdigest()
                db.execute('CREATE TABLE "'+table+'" (server_id,create_time,local_type,message_content,real_sender_id)')
                db.execute('INSERT INTO "'+table+'" VALUES(1,100,1,?,2)',('private fixture must never appear in catalog',))
                db.execute('INSERT INTO "'+table+'" VALUES(2,101,3,NULL,2)')
            db.execute('CREATE TABLE Msg_unknown(value)');db.commit();db.close()
            class DB:
                def __init__(self,path,*args):self.db=sqlite3.connect(path);self.db.row_factory=sqlite3.Row
                def query(self,sql,args=()):return [dict(r) for r in self.db.execute(sql,args)]
                def close(self):self.db.close()
            rows={'contact/contact.db':{'path':contact},'message/message_0.db':{'path':shard}}
            keys={rel:{'key_reference':'fixture','cipher_profile':'fixture'} for rel in rows}
            policy={'account_id':'account','database':{'shards':[{'path':str(shard)}],'sqlcipher_library':'fixture'}}
            store=SimpleNamespace(secrets=SimpleNamespace(get=lambda ref:b'0'*32))
            with patch.object(wcdb_catalog,'inventory',return_value=rows),patch.object(wcdb_catalog,'verified_cached',return_value=keys), \
                 patch.object(wcdb_catalog,'qualify_contacts') as identity,patch.object(wcdb_catalog,'CipherConnection',DB):
                result=wcdb_catalog.discover(store,policy)
            self.assertEqual({b['kind'] for b in result['conversations']},{'private','group','public'})
            self.assertEqual(result['coverage']['text_records'],3)
            self.assertEqual(result['coverage']['nontext_records'],3)
            self.assertEqual(result['coverage']['unmapped_tables'],1)
            self.assertFalse(result['coverage']['catalog_complete'])
            self.assertNotIn('private fixture must',str(result));identity.assert_called_once()


class ReviewSecurityTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_manual_reply.ManualReplyWorkflow();self.fixture.setUp();self.s=self.fixture.s
        self.s.config['account_review']={'enabled':True,'snapshot_until':int(time.time()),'deadline':time.time()+60,'max_pages':2}
        self.s.initial_policy_digest=digest(self.s.config)
    def tearDown(self):self.fixture.tearDown()
    def test_all_read_entrypoints_share_persistent_review_budget_and_snapshot(self):
        s=self.s
        with self.assertRaisesRegex(AXRError,'snapshot'):s.read('friend',until=2**63-2,limit=6)
        s.request_task('friend');s.read('friend',limit=6)
        with self.assertRaisesRegex(AXRError,'page_budget'):s.read('friend',limit=6)
        with self.assertRaisesRegex(AXRError,'page_budget'):s.request_task('friend')
    def test_catalog_pagination_and_strict_budget_controls(self):
        from axr_integration.policy import validate_controls
        self.assertEqual(self.s.conversations(0,1)['total'],1)
        for offset,limit in ((-1,1),(0,101),(True,1)):
            with self.assertRaises(AXRError):self.s.conversations(offset,limit)
        with self.assertRaises(AXRError):validate_controls({'account_review':{'enabled':'false'}})
    def test_review_note_needs_exact_disclosure_and_is_encrypted(self):
        from axr.owner import approve
        s=self.s;task=s.request_task('friend')
        with self.assertRaisesRegex(AXRError,'not_disclosed'):s.acknowledge_review(task['task_id'],'fixture summary')
        approve(s.store,task['disclosure_job'],s.principal);s.task_context(task['task_id'])
        result=s.acknowledge_review(task['task_id'],'fixture summary')
        self.assertEqual(result['state'],'Reviewed');self.assertEqual(s.poll_tasks()['tasks'],[])
        payload=s.journal.db.execute('select payload from review_notes').fetchone()[0]
        self.assertNotIn(b'fixture summary',bytes(payload));self.assertFalse(result['agent_sent'])

    def test_owner_opt_in_all_incoming_still_filters_outgoing(self):
        s=self.s;s.config['listener']['all_incoming']=True;s.initial_policy_digest=digest(s.config)
        for outgoing,expected in ((True,0),(False,1)):
            with patch.object(s.adapter,'search',return_value={'messages':[{'reference':str(outgoing),'text':'no keyword',
                'created':time.time(),'outgoing':outgoing}],'has_more':False,'cursor':None,'coverage':'fixture'}):s.tick()
            self.assertEqual(len(s.poll_tasks()['tasks']),expected)
        from axr_integration.policy import validate_controls
        with self.assertRaises(AXRError):validate_controls({'listener':{'all_incoming':'true'}})
        with self.assertRaises(AXRError):s.admission.evaluate(self.fixture.fixture.resource,[],{'all_incoming':'false'},lambda:None)

    def test_owner_review_stop_restores_previous_bindings_without_authority(self):
        import copy
        from axr_integration import owner_review
        s=self.s;original=copy.deepcopy(s.config);state=[copy.deepcopy(original)]
        store=SimpleNamespace(config=lambda:copy.deepcopy(state[0]),seal_config=lambda p:state.__setitem__(0,copy.deepcopy(p)),guard=s.guard,journal=s.journal)
        catalog={'database':{'fixture':True},'conversations':[{'conversation_id':'new','display_name':'new','data_class':'personal'}],
            'coverage':{'snapshot_until':int(time.time())}}
        version=s.guard.version
        with patch.object(owner_review,'discover',return_value=catalog),patch.object(owner_review.time,'sleep',side_effect=KeyboardInterrupt):
            owner_review.session(store,60,2)
        self.assertEqual(state[0]['conversations'],original['conversations'])
        self.assertFalse(state[0]['listener']['listen']);self.assertGreater(s.guard.version,version)

    def test_review_to_reply_phase_only_uses_pinned_owner_contacts(self):
        import copy
        from axr_integration import owner_review,owner_codex
        s=self.s;state=[copy.deepcopy(s.config)];original=copy.deepcopy(state[0]);events=[]
        store=SimpleNamespace(config=lambda:copy.deepcopy(state[0]),seal_config=lambda p:state.__setitem__(0,copy.deepcopy(p)),guard=s.guard,journal=s.journal)
        marker=Path(self.fixture.fixture.tmp.name)/'phase'
        catalog={'database':{'fixture':True},'conversations':[{'conversation_id':'catalog','display_name':'catalog','data_class':'personal'}],
                 'coverage':{'snapshot_until':int(time.time())}}
        def sleep(seconds):
            events.append(copy.deepcopy(state[0]))
            if len(events)==1:marker.write_text('reply')
            else:raise KeyboardInterrupt
        target={'conversation_id':'selected','display_name':'selected','data_class':'personal'}
        with patch.object(owner_review,'discover',return_value=catalog),patch.object(owner_review.time,'sleep',side_effect=sleep), \
             patch.object(owner_codex,'qualify_existing_contacts',return_value=[target]) as qualify:
            owner_review.session(store,120,2,draft_contacts=['selected'],phase_file=marker)
        self.assertNotEqual(events[0]['principal'],events[1]['principal'])
        self.assertTrue(events[1]['listener']['all_incoming'])
        self.assertEqual(events[1]['conversations'],[target]);self.assertNotIn('account_review',events[1])
        self.assertEqual(state[0]['conversations'],original['conversations'])
        self.assertEqual(qualify.call_args.args[2],['selected'])


if __name__=='__main__':unittest.main()
