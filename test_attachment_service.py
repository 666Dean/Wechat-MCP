# SPDX-License-Identifier: MIT
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
try:
    from axr.aet import AXRError
except ModuleNotFoundError:raise unittest.SkipTest('AXR optional')
from axr.guard import Guard
from axr.journal import Journal
from axr.storage import Vault
from axr.owner import approve
from axr_integration.service import Service


class AttachmentService(unittest.TestCase):
    def test_read_guard_encrypted_result_exact_disclosure_and_revocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();cache=root/'cache';cache.mkdir()
            body=b'Work agenda: discuss delivery date. password=fixture-secret'
            (cache/'cached-file.bin').write_bytes(body)
            meta={'filename':'agenda.txt','md5':hashlib.md5(body).hexdigest(),'size':len(body),'kind':'file','local_content_verified':False}
            class Store:
                directory=root;vault=Vault(b'v'*32)
                guard=Guard(root/'guard.db',b'g'*32);journal=Journal(root/'journal.db',vault)
                def config(self):return {'principal':'fixture-agent','purpose':'fixture','account_id':'fixture-account',
                    'agent_destination':'model:fixture','mode':'wcdb','conversations':[{'conversation_id':'fixture-chat','display_name':'fixture'}],
                    'attachments':{'enabled':True,'cache_roots':[str(cache)]}}
                def close(self):self.journal.close();self.guard.close()
            class Adapter:
                def status(self):return {'mode':'synthetic','send_available':False}
                def search(self,cid,**kwargs):return {'messages':[{'text':'附件：agenda.txt','attachment':meta,'reference':'fixture-source'}],
                    'coverage':'synthetic','has_more':False}
                def close(self):pass
            service=Service(root,store=Store(),adapter=Adapter(),leases=root/'leases')
            try:
                guard=service.guard;resource=service.resource('fixture-chat')
                guard._issue_owner(principal=service.principal,resource=resource,operations=['messages.read'],
                    purpose=service.purpose,expires_at=time.time()+120,max_uses=30,classes=['personal'])
                read=service.find_attachments('fixture-chat');self.assertEqual(read['state'],'Completed')
                ctx=read['result']['context_id'];parsed=service.read_attachment('fixture-chat',ctx,'fixture-source')
                self.assertEqual(parsed['state'],'AwaitingApproval')
                approve(service.store,parsed['id'],service.principal)
                done=service.execute(parsed['id']);self.assertEqual(done['state'],'Completed')
                self.assertNotIn('Work agenda',str(done));self.assertNotIn('fixture-secret',str(done))
                disclosed=service.disclose('fixture-chat',done['result']['context_id'])
                self.assertEqual(disclosed['state'],'AwaitingApproval')
                approve(service.store,disclosed['id'],service.principal)
                actual=service.execute(disclosed['id'])['result']['messages'][0]
                self.assertIn('Work agenda',actual['text']);self.assertNotIn('fixture-secret',actual['text'])
                self.assertTrue(actual['credentials_redacted']);self.assertEqual(actual['reference'],'fixture-source')
                with self.assertRaises(AXRError):service.read_attachment('fixture-chat',ctx,'forged-reference')
                guard.revoke_owner('fixture-revoke')
                with self.assertRaises(AXRError):service.read_attachment('fixture-chat',ctx,'fixture-source')
            finally:service.close()

    def test_file_metadata_reads_share_the_account_page_budget(self):
        import test_axr
        from unittest.mock import patch
        from axr.aet import digest
        fixture=test_axr.ServiceTests();fixture.setUp();s=fixture.service
        try:
            s.config.update(attachments={'enabled':True,'cache_roots':[str(Path(fixture.tmp.name).resolve())]},
                account_review={'enabled':True,'max_pages':1,'snapshot_until':int(time.time()),'deadline':time.time()+120})
            s.initial_policy_digest=digest(s.config)
            with patch.object(s.store,'config',return_value=s.config):
                self.assertEqual(s.read('friend')['state'],'Completed')
                with self.assertRaisesRegex(AXRError,'page_budget_exhausted'):s.find_attachments('friend')
        finally:fixture.tearDown()
