# SPDX-License-Identifier: MIT
"""New authority application API with native Guard and synthetic message data."""
import json
from dataclasses import replace
import unittest
from axr.aet import AXRError, Resource, canonical
from axr_applications.wechat_mcp import WeChatMCPApplication
from test import test_security_authority as fixtures


def application_fixture():
    fixture = fixtures.AuthorityTests('test_owner_presence_task_access_handler_claim_and_unknown_no_retry')
    fixture.setUp()
    try:
        resource = Resource('wechat','fixture-self','fixture-peer')
        operations = ('messages.read','disclosure.send','reply.prepare')
        fixture.guard._issue_owner(principal='agent',resource=resource,operations=['messages.read','reply.prepare'],
            purpose=fixture.c.goal_digest,expires_at=fixture.c.expires,max_uses=30,
            destinations=['model:fixture'],classes=['personal'])
        fixture.c = replace(fixture.c,application='wechat',
            resources=(resource.key,),sources=(resource.key,),operations=operations,
            destinations=('local','model:fixture'),max_uses=20,policy_version=fixture.guard.version)
        fixture.k.identity = lambda peer:{'agent':peer.principal,'application':'wechat','identity_verified':True}
        fixture.k.integrity.persist()

        class Database:
            account = 'fixture-self'
            calls = 0
            has_more = False
            def search(self,cid,*,check,**parameters):
                check()
                self.calls += 1
                if cid != 'fixture-peer':raise AssertionError('unexpected fixture resource')
                return {'messages':[{'reference':'fixture-message','text':'synthetic message; password: fixture-secret',
                    'created':100,'sender':'fixture-peer','outgoing':False}],
                    'cursor':{'fixture-shard':[100,1]},'scanned':1,'has_more':self.has_more}
        database = Database()
        fixture.saved_settings = []
        application = WeChatMCPApplication(fixture.k,database,'fixture-self',['fixture-peer'],
            fixture.handler,destination='model:fixture',
            save_approval_setting=lambda required,generation:fixture.saved_settings.append((required,generation)))
        fixture.k.application = application.dispatch
        fixture.k.application_owner = application.owner_dispatch
        fixture.capability = fixture.authorize()
        fixture.application, fixture.database = application, database
        return fixture
    except BaseException:
        fixture.doCleanups()
        raise


class AuthorityMCP(unittest.TestCase):
    def setUp(self):
        self.fixture = application_fixture()
        self.addCleanup(self.fixture.doCleanups)

    def call(self, method, *, capability=None, peer=None, **parameters):
        fixture = self.fixture
        return fixture.k.dispatch(peer or fixture.client, {'operation':'Application','payload':{
            'method':method,'parameters':parameters,'capability':capability or fixture.capability}})

    def read(self, **parameters):
        return self.call('read_context',conversation_id='fixture-peer',**parameters)

    def test_read_handle_separate_disclosure_manual_draft_and_own_receipt(self):
        read = self.read()
        self.assertNotIn('synthetic message',json.dumps(read))
        self.assertNotIn('fixture-secret',json.dumps(read))
        context = read['result']['context_id']
        proposed = self.call('disclose_context',conversation_id='fixture-peer',context_id=context)
        self.assertEqual(proposed['state'],'AwaitingApproval')
        self.assertNotIn('synthetic message',json.dumps(proposed))
        with self.assertRaises(AXRError):self.call('execute',job_id=proposed['id'])
        fixture = self.fixture
        review = fixture.call(fixture.owner,'Authorize',phase='review-application',job_id=proposed['id'])
        fixture.call(fixture.owner,'Authorize',phase='approve-application',job_id=proposed['id'],
            challenge_id=review['challenge']['nonce'],owner_signature=fixture.ownerkey.sign(canonical(review['challenge'])).hex())
        disclosed = self.call('execute',job_id=proposed['id'])
        self.assertIn('synthetic message',json.dumps(disclosed))
        self.assertNotIn('fixture-secret',json.dumps(disclosed))
        self.assertTrue(disclosed['result']['external_content_untrusted'])
        draft = self.call('prepare_reply',conversation_id='fixture-peer',text='synthetic reply',context_ids=[context])
        self.assertEqual(draft['result']['submission'],'human')
        self.assertFalse(draft['agent_sent'])
        self.assertNotIn('synthetic reply',json.dumps(draft))
        receipt = self.call('receipt',execution_id=draft['execution_id'])
        self.assertEqual(receipt['state'],'Completed')
        self.assertFalse(receipt['retry'])
        self.assertEqual(self.fixture.database.calls,1)

    def test_limits_and_unregistered_model_fields_cannot_touch_database(self):
        for limit in (0,7,True):
            with self.subTest(limit=limit),self.assertRaises(AXRError):self.read(limit=limit)
        for parameters in ({'role':'owner'},{'sql':'SELECT anything'},{'destination':'model:other'}):
            with self.subTest(parameters=parameters),self.assertRaises(AXRError):self.read(**parameters)
        with self.assertRaises(AXRError):self.call('messages.send',conversation_id='fixture-peer')
        with self.assertRaises(AXRError):self.call('read_context',conversation_id='other-peer')
        self.assertEqual(self.fixture.database.calls,0)

    def test_read_permission_does_not_allow_disclosure(self):
        fixture = self.fixture
        fixture.c = replace(fixture.c,id='read-only-task',operations=('messages.read',))
        fixture.capability = fixture.authorize()
        read = self.read()
        with self.assertRaises(AXRError):
            self.call('disclose_context',conversation_id='fixture-peer',context_id=read['result']['context_id'])
        self.assertEqual(fixture.database.calls,1)

    def test_capability_is_bound_to_os_peer_and_owner_methods_are_not_application_calls(self):
        fixture = self.fixture
        with self.assertRaises(AXRError):
            self.call('read_context',peer=replace(fixture.client,principal='other-agent'),conversation_id='fixture-peer')
        with self.assertRaises(AXRError):self.call('status',peer=fixture.owner)
        with self.assertRaises(AXRError):self.call('Authorize')
        self.assertEqual(fixture.database.calls,0)

    def test_revocation_and_expired_context_stop_before_native_read_or_disclosure(self):
        fixture = self.fixture
        read = self.read()
        fixture.j.db.execute('UPDATE contexts SET expires=0')
        with self.assertRaises(AXRError):
            self.call('disclose_context',conversation_id='fixture-peer',context_id=read['result']['context_id'])
        fixture.call(fixture.owner,'Revoke',scope=fixture.c.id)
        with self.assertRaises(AXRError):self.read()
        self.assertEqual(fixture.database.calls,1)

    def test_cursor_scope_and_filters_are_sealed_locally(self):
        fixture = self.fixture
        fixture.database.has_more = True
        cursor = self.read()['result']['cursor']
        self.assertIsInstance(cursor,str)
        with self.assertRaisesRegex(AXRError,'cursor_filter_mismatch'):self.read(cursor=cursor,since=1)
        with self.assertRaises(AXRError):self.read(cursor='forged-handle')
        self.assertEqual(fixture.database.calls,1)

    def test_old_epoch_can_read_own_receipt_but_cannot_execute_again(self):
        read = self.read()
        self.fixture.k.epoch = 'new-fixture-epoch'
        self.assertEqual(self.call('receipt',execution_id=read['execution_id'])['state'],'Completed')
        with self.assertRaises(AXRError):self.read()
        self.assertEqual(self.fixture.database.calls,1)

    def test_context_capacity_blocks_before_creating_more_pending_jobs(self):
        fixture = self.fixture
        read = self.read()
        resource = Resource('wechat','fixture-self','fixture-peer')
        for index in range(49):
            fixture.application.remember(fixture.client,fixture.c.body(),resource,{'kind':'fixture','index':index})
        before = fixture.j.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        with self.assertRaisesRegex(AXRError,'wechat_context_capacity'):
            self.call('disclose_context',conversation_id='fixture-peer',context_id=read['result']['context_id'])
        self.assertEqual(fixture.j.db.execute('SELECT count(*) FROM jobs').fetchone()[0],before)

    def test_draft_keeps_prior_disclosure_taint_even_when_context_ids_omit_it(self):
        fixture = self.fixture
        read = self.read()
        fixture.j.taint_disclosure(fixture.client.principal,Resource('wechat','fixture-self','other-peer'),'personal')
        fixture.k.integrity.persist()
        with self.assertRaises(AXRError):
            self.call('prepare_reply',conversation_id='fixture-peer',text='reply',context_ids=[read['result']['context_id']])

    def setting(self, required):
        fixture = self.fixture
        review = fixture.call(fixture.owner,'Authorize',phase='review-approval-setting',manual_approval_required=required)
        return fixture.call(fixture.owner,'Authorize',phase='approve-approval-setting',manual_approval_required=required,
            challenge_id=review['challenge']['nonce'],owner_signature=fixture.ownerkey.sign(canonical(review['challenge'])).hex())

    def test_approval_switch_is_default_on_owner_signed_and_independent_of_task_scope(self):
        self.assertTrue(self.call('status')['manual_approval_required'])
        fixture = self.fixture
        with self.assertRaises(AXRError):
            fixture.call(fixture.client,'Authorize',phase='review-approval-setting',manual_approval_required=False)
        with self.assertRaises(AXRError):self.call('set_approval',manual_approval_required=False)
        self.setting(False)
        self.assertFalse(self.call('status')['manual_approval_required'])
        self.assertEqual(fixture.saved_settings,[(False,1)])
        read = self.read()
        disclosed = self.call('disclose_context',conversation_id='fixture-peer',context_id=read['result']['context_id'])
        self.assertEqual(disclosed['state'],'Completed')
        self.assertTrue(disclosed['result']['body_disclosed'])
        self.assertNotIn('fixture-secret',json.dumps(disclosed))
        self.setting(True)
        proposed = self.call('disclose_context',conversation_id='fixture-peer',context_id=read['result']['context_id'])
        self.assertEqual(proposed['state'],'AwaitingApproval')

    def test_disabling_approval_does_not_grant_unapproved_operations(self):
        self.setting(False)
        fixture = self.fixture
        fixture.c = replace(fixture.c,id='read-only-task',operations=('messages.read',))
        fixture.capability = fixture.authorize()
        read = self.read()
        with self.assertRaises(AXRError):
            self.call('disclose_context',conversation_id='fixture-peer',context_id=read['result']['context_id'])

    def test_approval_switch_rejects_unsigned_stale_and_non_boolean_updates(self):
        fixture = self.fixture
        for invalid in (0,'false',None):
            with self.subTest(invalid=invalid),self.assertRaises(AXRError):
                fixture.call(fixture.owner,'Authorize',phase='review-approval-setting',manual_approval_required=invalid)
        review = fixture.call(fixture.owner,'Authorize',phase='review-approval-setting',manual_approval_required=False)
        with self.assertRaises(AXRError):
            fixture.call(fixture.owner,'Authorize',phase='approve-approval-setting',manual_approval_required=False,
                challenge_id=review['challenge']['nonce'],owner_signature='00')
        stale = fixture.call(fixture.owner,'Authorize',phase='review-approval-setting',manual_approval_required=False)
        self.setting(False)
        self.setting(True)
        with self.assertRaises(AXRError):
            fixture.call(fixture.owner,'Authorize',phase='approve-approval-setting',manual_approval_required=False,
                challenge_id=stale['challenge']['nonce'],owner_signature=fixture.ownerkey.sign(canonical(stale['challenge'])).hex())
        self.assertTrue(self.call('status')['manual_approval_required'])
