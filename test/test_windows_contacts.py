# SPDX-License-Identifier: MIT
"""Directory/request/owner signature chain using native Guard and fixture I/O."""
import sys,time,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from axr.aet import AXRError,canonical
from axr.ipc import PeerContext
from axr_applications import windows_owner
from test import test_windows_service as fixtures

@unittest.skipUnless(sys.platform=='win32','Windows managed contact requests')
class ContactRequests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WindowsService();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.s=self.f.service;self.c=self.s.contacts;self.owner=self.f.owner;self.client=self.f.client
        self.rows=[*self.s.catalog.values(),{'conversation_id':'fixture-new','display_name':'New fixture contact','data_class':'personal'}]
        self.s.database.catalog=Mock(side_effect=lambda check:list(self.rows))
        database=patch('axr_applications.windows_contacts.make_database',return_value=self.s.database);database.start();self.addCleanup(database.stop)
        alive=patch.object(self.c,'client_alive',return_value=True);self.alive=alive.start();self.addCleanup(alive.stop)
    def request(self,target='fixture-new',reason='Read the fixture discussion'):
        return self.f.call('wechat_request_authorization',target=target,reason=reason)['request_id']
    def review(self,key):return self.c.review(self.owner,key)['challenge']
    def sign(self,challenge):return self.f.signer.sign(canonical(challenge)).hex()
    def approve(self,key):
        challenge=self.review(key)
        return self.c.approve(self.owner,challenge['nonce'],self.sign(challenge))
    def test_request_and_owner_refresh_create_no_scope_or_task_grant(self):
        before=self.s.kernel.db.execute('SELECT count(*) FROM security_contracts').fetchone()[0]
        key=self.request();self.c.refresh(self.owner)
        self.assertIsNone(self.s.scope);self.assertIn('fixture-new',self.s.catalog)
        self.assertFalse(self.f.call('wechat_authorization_status',request_id=key)['authority_granted'])
        self.assertEqual(self.s.kernel.db.execute('SELECT count(*) FROM security_contracts').fetchone()[0],before)
        with self.assertRaisesRegex(AXRError,'scope_stopped'):self.f.call('wechat_read_messages',conversation_id='fixture-new')
    def test_hardware_signature_gate_then_exact_target_read_scope_and_revocation(self):
        key=self.request();result=self.approve(key)
        self.assertTrue(result['authorization_signed']);self.assertEqual(self.s.scope['targets'],['fixture-new'])
        self.assertFalse(self.s.scope['automatic']);self.assertEqual(self.s.scope['reply_targets'],[])
        status=self.f.call('wechat_authorization_status',request_id=key)
        self.assertTrue(status['authority_granted']);self.assertNotIn('messages.send',status['operations'])
        self.assertNotIn('reason',status);self.assertNotIn('client_witness',status)
        page=self.f.call('wechat_read_messages',conversation_id='fixture-new')
        self.assertEqual(page['state'],'AwaitingDisclosureApproval');self.assertNotIn('page',page)
        self.s.stop();self.assertFalse(self.f.call('wechat_authorization_status',request_id=key)['authority_granted'])
    def test_active_scope_replacement_preserves_expiry_and_remaining_quota(self):
        self.f.activate(targets=['fixture-peer'],automatic=True,max_replies=5)
        self.s.reply_count=2;old=self.s.scope.copy();oldcap=self.s.capability
        deadline=self.s.scope_clock[1]+self.s.scope_clock[2]
        key=self.request();challenge=self.review(key)
        self.assertLessEqual(challenge['scope']['expires'],old['expires']);self.assertEqual(challenge['scope']['max_replies'],3)
        self.c.approve(self.owner,challenge['nonce'],self.sign(challenge))
        self.assertEqual(self.s.scope['targets'],['fixture-peer','fixture-new']);self.assertEqual(self.s.scope['max_replies'],3)
        self.assertNotIn('fixture-new',self.s.scope['reply_targets']) # No qualified navigation profile for this contact.
        self.assertLessEqual(self.s.scope_clock[1]+self.s.scope_clock[2],deadline)
        row,_=self.s.kernel.security._contract(oldcap['body']['contract']['id']);self.assertTrue(row['revoked'])
    def test_new_read_only_contact_produces_draft_inside_existing_automatic_scope(self):
        self.f.activate(targets=['fixture-peer'],automatic=True)
        self.approve(self.request());self.f.config['manual_approval_required']=False
        job={'id':'new-contact-inbound','conversation_id':'fixture-new','state':'Executing','operation':'reply.prepare','expires':time.time()+60}
        with patch.object(self.s,'infer',return_value='Synthetic local draft'):
            self.s.process_incoming(job['id'],job,[{'text':'Synthetic input'}])
        self.assertEqual(self.s.jobs[job['id']]['state'],'Draft')
        with self.assertRaisesRegex(AXRError,'send_target_not_authorized'):
            self.f.call('wechat_send_message',conversation_id='fixture-new',text='Cannot submit',request_id='blocked')
    def test_bad_signature_and_generic_activation_cannot_bypass_contact_review(self):
        key=self.request();challenge=self.review(key)
        with self.assertRaisesRegex(AXRError,'signature_required'):self.c.approve(self.owner,challenge['nonce'],'00'*64)
        with self.assertRaisesRegex(AXRError,'authorization_review_required'):
            self.s.activate(self.owner,challenge['nonce'],self.sign(challenge))
        self.assertIsNone(self.s.scope)
    def test_stop_or_quota_change_after_review_invalidates_signature(self):
        self.f.activate(targets=['fixture-peer'])
        key=self.request();challenge=self.review(key);self.s.reply_count+=1
        with self.assertRaisesRegex(AXRError,'review_changed'):self.c.approve(self.owner,challenge['nonce'],self.sign(challenge))
        challenge=self.review(key);self.s.stop()
        with self.assertRaisesRegex(AXRError,'review_changed'):self.c.approve(self.owner,challenge['nonce'],self.sign(challenge))
        self.assertIsNone(self.s.scope)
    def test_dead_client_changed_directory_and_ambiguous_labels_do_not_grant(self):
        key=self.request();challenge=self.review(key);self.alive.return_value=False
        with self.assertRaisesRegex(AXRError,'review_changed'):self.c.approve(self.owner,challenge['nonce'],self.sign(challenge))
        self.alive.return_value=True;challenge=self.review(key);self.s.catalog['fixture-new']['display_name']='Changed fixture label'
        with self.assertRaisesRegex(AXRError,'review_changed'):self.c.approve(self.owner,challenge['nonce'],self.sign(challenge))
        self.rows.append({'conversation_id':'fixture-other','display_name':'New fixture contact','data_class':'personal'})
        ambiguous=self.request('New fixture contact')
        with self.assertRaisesRegex(AXRError,'unique_private'):self.review(ambiguous)
        self.assertIsNone(self.s.scope)
    def test_other_client_cannot_read_request_status_or_owner_methods(self):
        key=self.request();other=PeerContext('client',self.client.principal,'unrelated-witness',999,'1')
        with self.assertRaisesRegex(AXRError,'not_owned'):self.c.status(other,key)
        with self.assertRaises(AXRError):self.c.refresh(self.client)
        with self.assertRaises(AXRError):self.c.deny(self.client,key)
    def test_expiry_rejection_and_capacity_never_self_grant(self):
        key=self.request();self.c.deny(self.owner,key)
        self.assertEqual(self.f.call('wechat_authorization_status',request_id=key)['state'],'Rejected')
        with self.assertRaisesRegex(AXRError,'not_pending'):self.review(key)
        self.c.requests[key]['expires']=time.time()-1
        with self.assertRaisesRegex(AXRError,'expired'):self.c.status(self.client,key)
        for _ in range(20):self.request()
        with self.assertRaisesRegex(AXRError,'capacity'):self.request()
        self.assertIsNone(self.s.scope)
    def test_native_owner_review_cancel_never_opens_signing_key(self):
        key=self.request();channel=self.f.channel();signer=Mock()
        with self.assertRaisesRegex(AXRError,'cancelled'):
            windows_owner.service_control({'endpoint':'fixture','server':{}},{'operation':'control','method':'approve_authorization',
                'arguments':{'request_id':key}},lambda value:None,connect=lambda *args:channel,
                owner_key=signer,clock=time.time,confirm=lambda *args:False)
        signer.assert_not_called();self.assertIsNone(self.s.scope);self.assertTrue(channel.closed)
    def test_real_rsa_signature_through_fixed_owner_protocol_approves_only_reviewed_contact(self):
        from cryptography.hazmat.primitives.asymmetric import rsa,padding
        from cryptography.hazmat.primitives import hashes,serialization
        rsa_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        signer=SimpleNamespace(sign=lambda data:rsa_key.sign(data,padding.PKCS1v15(),hashes.SHA256()))
        self.s.kernel.owner_public_key=rsa_key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        key=self.request();channel=self.f.channel();outputs=[]
        result=windows_owner.service_control({'endpoint':'fixture','server':{}},{'operation':'control','method':'approve_authorization',
            'arguments':{'request_id':key}},outputs.append,connect=lambda *args:channel,
            owner_key=lambda:signer,clock=time.time,confirm=lambda *args:True)
        self.assertTrue(result['authorization_signed']);self.assertEqual(self.s.scope['targets'],['fixture-new'])
        self.assertEqual(outputs,[result]);self.assertTrue(channel.closed)
    def test_stop_during_replacement_cannot_reinstate_the_old_scope(self):
        self.f.activate(targets=['fixture-peer']);key=self.request();challenge=self.review(key);stop=self.s.stop
        def concurrent_stop():
            result=stop();stop();return result
        with patch.object(self.s,'stop',side_effect=concurrent_stop):
            with self.assertRaisesRegex(AXRError,'review_changed'):self.c.approve(self.owner,challenge['nonce'],self.sign(challenge))
        self.assertIsNone(self.s.scope);self.assertFalse(self.c.status(self.client,key)['authority_granted'])
    def test_cached_directory_and_requests_do_not_restore_permissions_after_restart(self):
        from axr_applications.windows_contacts import ContactAuthorization
        key=self.request();self.c.refresh(self.owner);self.s.stop()
        recovered=ContactAuthorization(self.s)
        self.assertIsNone(self.s.scope);self.assertEqual(recovered.pending(),[])
        self.assertEqual(recovered.status(self.client,key)['state'],'Unknown')
        self.assertFalse(recovered.status(self.client,key)['authority_granted'])
    def test_clock_rollback_after_owner_review_cannot_renew_scope_duration(self):
        self.f.activate(targets=['fixture-peer']);key=self.request();challenge=self.review(key)
        wall=self.c.reviews[challenge['nonce']]['wall']
        with patch('axr_applications.windows_contacts.time.time',return_value=wall-1):
            with self.assertRaisesRegex(AXRError,'review_changed'):self.c.approve(self.owner,challenge['nonce'],self.sign(challenge))
        self.assertNotIn('fixture-new',self.s.scope['targets'])
