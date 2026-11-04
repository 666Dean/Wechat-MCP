# SPDX-License-Identifier: MIT
"""Synthetic permits/Guard/SCM only; never call the real qualification entry."""
import copy,hashlib,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from axr.aet import AXRError,Action,Resource,canonical,digest
from axr.storage import Vault
from axr_applications import windows_qualification as q,windows_admission as admission
from test.test_security_authority import FixtureSigner,ProtectedStore


class PermitFixture(unittest.TestCase):
    def setUp(self):
        self.signer=FixtureSigner();self.key_id=hashlib.sha256(self.signer.public_key).hexdigest();self.keys={self.key_id:self.signer.public_key}
        self.expected={'configuration':'a1'*32,'build':'b2'*32,'owner_key':'c3'*32,'navigation':'d4'*32,'os_build':[10,0,99999],'platform':'windows-x64'}
        self.body={'version':2,'product':q.PRODUCT,'sequence':1,'subject':copy.deepcopy(self.expected),
            'created':time.time()-1,'expires':time.time()+300,'nonce':'e5'*32,
            'software_audit':{'complete':True,'record_sha256':'f6'*32},
            'plan':{'scenario':'read','target':'fixture-peer','parking':'fixture-owner','text':'','since':0}}
    def signed(self):
        body=copy.deepcopy(self.body)
        return {'body':body,'key_id':self.key_id,'signature':self.signer.sign(canonical(body)).hex()}


class Permits(PermitFixture):
    def test_permit_is_never_admission_evidence_and_requires_software_audit(self):
        self.assertFalse(q.verify(self.signed(),self.keys,self.expected)['runtime_qualified'])
        with self.assertRaisesRegex(AXRError,'material_invalid'):admission.verify(self.signed(),self.keys,self.expected)
        self.body['software_audit']['complete']=False
        with self.assertRaises(AXRError):q.verify(self.signed(),self.keys,self.expected)
    def test_tamper_key_subject_future_expiry_sequence_and_extra_fields_deny(self):
        original=copy.deepcopy(self.body)
        for change in ({'product':'wechat-codex-mcp/windows'},{'sequence':True},{'nonce':'bad'},{'expires':time.time()+601},
            {'created':time.time()+1},{'subject':{**self.expected,'platform':'darwin'}},{'device_verified':True}):
            self.body={**copy.deepcopy(original),**change}
            with self.subTest(change=change),self.assertRaises(AXRError):q.verify(self.signed(),self.keys,self.expected)
        self.body=original;envelope=self.signed();envelope['body']['plan']['scenario']='send'
        with self.assertRaises(AXRError):q.verify(envelope,self.keys,self.expected)
        envelope=self.signed();envelope['key_id']='00'*32
        with self.assertRaises(AXRError):q.verify(envelope,self.keys,self.expected)
    def test_no_groups_background_unlimited_tools_or_implicit_text(self):
        original=copy.deepcopy(self.body['plan'])
        for change in ({'scenario':'automatic'},{'target':'fixture@chatroom'},{'target':'gh_fixture'},{'parking':'fixture-peer'},
            {'text':'not allowed in read plan'},{'since':True},{'tools':['shell']},{'overwrite_drafts':True}):
            self.body['plan']={**original,**change}
            with self.subTest(change=change),self.assertRaises(AXRError):q.verify(self.signed(),self.keys,self.expected)
    def test_permanent_claim_precedes_work_and_never_restores_after_restart_or_equivocation(self):
        store=SimpleNamespace(secrets=ProtectedStore(),vault=Vault(b'v'*32));envelope=self.signed()
        q.claim(store,envelope)
        with self.assertRaisesRegex(AXRError,'consumed_no_retry'):q.claim(store,envelope)
        self.body['plan']['since']=1
        with self.assertRaisesRegex(AXRError,'consumed_no_retry'):q.claim(store,self.signed())
        self.body['sequence']=2;q.claim(store,self.signed())
        store.secrets.values['windows-qualification-head-v2']=b'corrupt'
        with self.assertRaises(AXRError):q.claim(store,self.signed())
    def test_session_still_uses_bound_files_dual_clocks_and_permanent_failure(self):
        # Exercise a valid signed plan larger than normal admission's 16 KiB
        # ceiling through the actual bounded session reader.
        self.body['plan'].update(scenario='send',text='x'*15500)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name).resolve();(root/'runtime').mkdir()
        config=root/'deployment.json';config.write_bytes(b'{"synthetic":true}')
        (root/'runtime/admission-trust.json').write_bytes(canonical({'version':2,'keys':{self.key_id:self.signer.public_key.hex()}}))
        material=root/'windows-qualification.json';material.write_bytes(canonical(self.signed()))
        self.assertGreater(material.stat().st_size,16000);self.assertLessEqual(material.stat().st_size,20000)
        with patch.object(admission,'installed_context',return_value=(self.keys,self.expected)),patch.object(
            admission.native,'windows_deployment_configuration',return_value=str(config),create=sys.platform!='win32'),patch.object(
            admission.native,'windows_installation_root',return_value=str(root),create=sys.platform!='win32'),patch.object(
            admission.native,'windows_data_root',return_value=str(root),create=sys.platform!='win32'):
            session=q.QualificationSession({});session.require();raw=material.read_bytes();material.unlink()
            with self.assertRaisesRegex(AXRError,'restart_required'):session.require()
            material.write_bytes(raw)
            with self.assertRaisesRegex(AXRError,'restart_required'):session.require()


class RestrictedKernel(unittest.TestCase):
    def setUp(self):
        import test_wechat_service_v2 as fixtures
        self.f=fixtures.ServiceTests()
        with patch.object(fixtures,'WeChatKernel',q.QualificationKernel):self.f.setUp()
        self.addCleanup(self.f.doCleanups);self.k=self.f.kernel;self.k.windows_admission=Mock()
        self.plan={'scenario':'read','target':'fixture-peer','parking':'fixture-owner','text':'','since':0}
        self.k.qualification_plan=self.plan;self.k.qualification_application=self.f.config
        self.k.qualification_application['reply_navigation']={'profiles':{i:{'label':i} for i in ('fixture-peer','fixture-owner')}}
        self.f.activate(disclose=False)
    def test_single_page_read_uses_real_guard_and_returns_only_aggregate_facts(self):
        result=q.execute(self.f.service,self.plan)
        self.assertEqual(result['records'],1);self.assertFalse(result['body_disclosed'])
        self.assertNotIn('synthetic-secret',str(result));self.assertTrue(self.k.integrity.verify())
    def test_public_api_owner_api_and_new_task_channels_are_absent(self):
        for peer in (self.f.owner,self.f.client,self.f.peer):
            for operation in ('WeChat','WeChatOwner','Application','Authorize'):
                with self.subTest(operation=operation),self.assertRaisesRegex(AXRError,'no_public_api'):
                    self.k.dispatch(peer,{'operation':operation,'payload':{}})
    def test_wrong_source_read_bound_destination_send_and_disclosure_deny(self):
        for cid,operation,payload,destination in (('fixture-owner','messages.search',{'since':0,'cursor':None,'limit':6},'local'),
            ('fixture-peer','messages.search',{'since':1,'cursor':None,'limit':6},'local'),
            ('fixture-peer','messages.search',{'since':0,'cursor':None,'limit':7},'local'),
            ('fixture-peer','disclosure.send',{},'model:codex-mcp'),('fixture-peer','messages.send',{'text':'unexpected'},'local')):
            action=Action(q.PRINCIPAL,Resource('wechat','fixture-owner',cid),operation,'synthetic',payload,destination=destination)
            with self.subTest(operation=operation),self.assertRaisesRegex(AXRError,'outside_plan'):self.k.qualify_action(action)
    def test_source_allows_only_fixed_provider_and_send_requires_exact_target_text_destination(self):
        from axr_applications.codex_source import CodexSourceProvider
        r=Resource('wechat','fixture-owner','fixture-peer');self.plan['scenario']='source'
        self.k.qualify_action(Action(q.PRINCIPAL,r,'disclosure.send','synthetic',{},destination=CodexSourceProvider.destination))
        self.plan.update(scenario='send',text='Synthetic reply')
        self.k.qualify_action(Action(q.PRINCIPAL,r,'messages.send','synthetic',{'text':'Synthetic reply'},destination='wechat:'+r.key))
        with self.assertRaisesRegex(AXRError,'outside_plan'):
            self.k.qualify_action(Action(q.PRINCIPAL,r,'messages.send','synthetic',{'text':'changed'},destination='wechat:'+r.key))
    def test_expiry_blocks_native_claim_even_for_an_already_prepared_exact_action(self):
        action=self.f.service.action('fixture-peer','messages.search',{'since':0,'cursor':None,'limit':6})
        proof=self.f.service.prepare(action);self.k.windows_admission.require.side_effect=AXRError('synthetic_expiry')
        with self.assertRaisesRegex(AXRError,'restart_required'):self.k.claim_commit(self.f.peer,proof)
        self.assertEqual(self.k.db.execute('SELECT state FROM authority_commits').fetchone()[0],'Prepared')


class ExactDisclosure(unittest.TestCase):
    def test_source_does_not_bypass_independent_content_approval_or_expose_output(self):
        plan={'scenario':'source','target':'fixture-peer','parking':'fixture-owner','text':'','since':0}
        page={'messages':[{'reference':'synthetic','outgoing':False,'text':'Synthetic source'}],'has_more':False}
        service=SimpleNamespace(check=Mock(),read=Mock(return_value=page),approval_required=lambda:True,infer=Mock(return_value='Synthetic model reply'))
        with self.assertRaisesRegex(AXRError,'exact_owner_approval_required'):q.execute(service,plan)
        service.infer.assert_not_called()
        review=Mock(side_effect=AXRError('synthetic_cancelled'))
        with self.assertRaisesRegex(AXRError,'cancelled'):q.execute(service,plan,review)
        service.infer.assert_not_called();review.side_effect=None
        result=q.execute(service,plan,review)
        self.assertTrue(result['body_disclosed']);self.assertNotIn('Synthetic model reply',str(result))
        self.assertEqual(review.call_args.args[0][0]['text'],'Synthetic source');service.infer.assert_called_once()


class Bootstrap(unittest.TestCase):
    def test_normal_service_gate_failure_never_falls_back_to_qualification(self):
        from axr import authority_main
        registration=Mock();registration.release_gate.return_value.require.side_effect=AXRError('security_release_not_qualified')
        config={'version':2,'application_module':'axr_applications.wechat','deployment':{}}
        with patch.object(authority_main.native,'security_release',True),patch.object(authority_main,'AuthoritySecretStore'),patch.object(
            authority_main,'Vault',return_value=SimpleNamespace(open=lambda *a:config)),patch.object(authority_main.importlib,'import_module',return_value=registration):
            with self.assertRaisesRegex(AXRError,'not_qualified'):authority_main.main()
        registration.create_authority.assert_not_called();registration.qualify_once.assert_not_called()
    @unittest.skipUnless(sys.platform=='win32','Windows fixed qualification bootstrap')
    def test_separate_bootstrap_uses_only_registered_hook_and_does_not_create_normal_server(self):
        from axr import authority_qualify
        registration=Mock();config={'version':2,'application_module':'axr_applications.wechat','deployment':{'synthetic':True}}
        with patch.object(authority_qualify.native,'security_release',True),patch.object(authority_qualify,'AuthoritySecretStore'),patch.object(
            authority_qualify,'Vault',return_value=SimpleNamespace(open=lambda *a:config)),patch.object(authority_qualify.importlib,'import_module',return_value=registration):
            authority_qualify.main()
        registration.qualify_once.assert_called_once_with(config['deployment']);registration.create_authority.assert_not_called()


@unittest.skipUnless(sys.platform=='win32','Windows full synthetic send transaction')
class ExactSend(unittest.TestCase):
    def test_owner_plan_reaches_existing_transaction_and_unknown_never_sends_again(self):
        import axr_applications,test_wechat_service_v2 as fixtures
        from test.test_authority_reply import ReplyTransaction
        from axr_applications.wechat_windows_service import WindowsWeChatService
        f=fixtures.ServiceTests()
        with patch.object(fixtures,'WeChatKernel',q.QualificationKernel):f.setUp()
        self.addCleanup(f.doCleanups);k=f.kernel;k.windows_admission=Mock()
        plan={'scenario':'send','target':'fixture-peer','parking':'fixture-owner','text':'Synthetic reply','since':0}
        config={**f.config,'manual_approval_required':True,'reply_navigation':{'profiles':{cid:{'label':label,'visual_binding':{'expected_identity':cid}}
            for cid,label in [('fixture-peer','Fixture peer'),('fixture-owner','Fixture owner')]}}}
        k.qualification_plan=plan;k.qualification_application=config;k.store.config=lambda:{'application':config}
        with patch.object(axr_applications,'_wechat_credentials',SimpleNamespace(WeChatConsumer=lambda *a:None),create=True),patch(
            'axr_applications.wechat_service.NativeDatabase',fixtures.Database):service=WindowsWeChatService(k,SimpleNamespace(user='synthetic-owner'),config,'synthetic-pipe')
        self.addCleanup(service.close)
        transaction=ReplyTransaction();transaction.setUp();self.addCleanup(transaction.doCleanups)
        transaction.plan=type(transaction.plan)('fixture-owner','fixture-peer','fixture-owner','Fixture peer','Fixture owner','Synthetic reply','synthetic-task')
        transaction.cache={'fixture-peer':'','fixture-owner':''};transaction.active='fixture-owner'
        service.database=transaction.database;service.executor=transaction.executor
        q.activate_scope(service,plan,time.time()+300)
        def invoke(action,check):
            proof=service.prepare(action);k.claim_commit(f.peer,proof)
            result=({'receipt':{'state':'Completed'},'native':{'main_window_verified':True,'binding':{'pid':12,'window_id':1}}}
                if action.payload['mode']=='binding' else transaction.native(action,check))
            k.observe(f.peer,proof,verified=result['receipt']['state']=='Completed',evidence_digest=digest(result));return result
        with patch.object(service,'send_wait_reason',return_value=None),patch.object(service.navigation,'invoke',side_effect=invoke):
            result=q.execute(service,plan)
            self.assertTrue(result['database_record_observed']);self.assertEqual(result['native_state'],'Unknown')
            with self.assertRaisesRegex(AXRError,'previous_attempt'):q.execute(service,plan)
        self.assertEqual(transaction.sent,1);self.assertTrue(k.integrity.verify())


@unittest.skipUnless(sys.platform=='win32','Windows native reject before owner/UI lookup')
class NativeChallenge(unittest.TestCase):
    def test_new_fixed_kinds_validate_then_refuse_ordinary_python_before_any_owner_action(self):
        from axr import _axr_native as native
        base={'version':2,'kind':'wechat-owner-qualification','configuration_digest':'a1'*32,'nonce':'b2'*32,
            'expires':time.time()+60,'expected_public_key':'ab'*294,'build_digest':'c3'*32,'qualification_digest':'d4'*32}
        for challenge in (base,{**base,'kind':'wechat-owner-qualification-disclosure','records':[
            {'reference':'synthetic','text':'Synthetic source','data_class':'personal'}],'content_digest':'e5'*32}):
            with self.assertRaisesRegex(RuntimeError,'windows_owner_setup_authority_host_required'):
                native.exchange_windows_owner_setup('S-1-5-21-1-2-3-4',canonical(challenge).decode())
        with self.assertRaisesRegex(RuntimeError,'challenge_invalid'):
            native.exchange_windows_owner_setup('S-1-5-21-1-2-3-4',canonical({k:v for k,v in base.items() if k!='qualification_digest'}).decode())


@unittest.skipUnless(sys.platform=='win32','Windows synthetic one-shot lifecycle')
class Lifecycle(PermitFixture):
    def setUp(self):
        super().setUp()
        import threading,contextlib
        from axr_applications import wechat,windows_enrollment,wechat_windows_service
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve();(self.root/'runtime').mkdir()
        self.config={'state':str(self.root/'state'),'endpoint':'synthetic-pipe','owner_user':'synthetic-owner','application':{}}
        self.key='ab'*294;self.anchor={'state':self.config['state'],'endpoint':self.config['endpoint'],'owner_public_key':self.key}
        self.store=SimpleNamespace(secrets=ProtectedStore(),vault=Vault(b'v'*32),config=lambda:{'application':{}},close=Mock())
        self.kernel=Mock();self.registry=SimpleNamespace(user='synthetic-owner');self.closed=threading.Event();self.server=Mock(listener=None)
        self.server.serve.side_effect=lambda:(setattr(self.server,'listener',object()),self.closed.wait(5))
        self.server.close.side_effect=self.closed.set
        self.exchange=Mock(side_effect=self.owner_review);self.session=Mock()
        self.service=SimpleNamespace(close=Mock(),derive_contract=Mock(),generation=0,scope=None)
        outer=self
        class Service:
            def __new__(cls,*args):return outer.service
        for p in (patch.object(q.native,'windows_installation_root',return_value=str(self.root)),patch.object(q.native,'windows_data_root',return_value=str(self.root)),
            patch.object(q.native,'HardwareSigningKey',return_value=object()),patch.object(q.admission,'installed_context'),
            patch('axr.deployment_configuration.read',return_value={'deployment':self.config}),patch.object(wechat,'_configuration',side_effect=lambda x:x),
            patch.object(q,'installed_permit',side_effect=lambda *a:self.envelope),patch.object(q,'QualificationSession',return_value=self.session),
            patch.object(wechat,'OwnerStore',return_value=self.store),patch.object(wechat,'_windows_kernel',return_value=(self.kernel,self.registry)),
            patch.object(windows_enrollment,'exchange',self.exchange),patch.object(wechat_windows_service,'WindowsWeChatService',Service),
            patch('axr.authority_server.AuthorityServer',return_value=self.server),patch.object(q,'execute',return_value={'records':1,'body_disclosed':False})):
            p.start();self.addCleanup(p.stop)
        self.envelope=self.signed()
        self.session.material_digest=digest(self.envelope)
    def owner_review(self,config,challenge,runtime):
        self.assertIn('windows-qualification-head-v2',self.store.secrets.values)
        self.assertEqual(challenge['qualification_digest'],digest(self.envelope))
        self.assertEqual(challenge['kind'],'wechat-owner-qualification')
        return {'public_key':self.key},{'user':'synthetic-owner'}
    def test_claim_precedes_owner_approval_and_all_paths_close_without_starting_scheduler(self):
        result=q.run(self.anchor)
        self.assertEqual(result['state'],'Recorded');self.assertFalse(result['runtime_qualified'])
        self.service.close.assert_called_once();self.kernel.close.assert_called_once();self.server.close.assert_called_once()
        self.assertFalse(self.service.scope['automatic']);self.assertFalse(self.service.scope['disclose'])
        self.assertLessEqual(self.service.scope['max_replies'],1)
        self.assertEqual(__import__('json').loads((self.root/'windows-qualification-result.json').read_bytes())['state'],'Recorded')
    def test_cancel_consumes_permit_and_never_constructs_service_or_retries_owner(self):
        self.exchange.side_effect=AXRError('synthetic_owner_cancelled')
        self.assertEqual(q.run(self.anchor)['state'],'Unknown');self.service.derive_contract.assert_not_called()
        self.assertEqual(q.run(self.anchor)['error'],'windows_qualification_consumed_no_retry');self.assertEqual(self.exchange.call_count,1)


@unittest.skipUnless(sys.platform=='win32','Windows synthetic stage and SCM')
class Staging(PermitFixture):
    def setUp(self):
        super().setUp()
        from scripts import run_windows_qualification as stage
        self.stage=stage;tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.path=self.root/'deployment.json';self.owner='S-1-5-21-1-2-3-4';self.raw=canonical({'deployment':{'owner_user':self.owner}});self.path.write_bytes(self.raw)
        self.service=Mock();self.service.status.return_value={'state':'Stopped'}
        for p in (patch.object(stage,'administrator'),patch.object(stage,'protect'),patch.object(stage,'metadata_lease',return_value=__import__('contextlib').nullcontext()),
            patch.object(stage,'ServiceController',return_value=self.service),patch.object(stage,'review_context',return_value=(self.keys,self.expected)),
            patch.object(stage.native,'windows_deployment_configuration',return_value=str(self.path)),patch.object(stage.native,'windows_data_root',return_value=str(self.root))):
            p.start();self.addCleanup(p.stop)
    def run_plan(self,envelope):return self.stage.run(envelope,self.owner,hashlib.sha256(self.raw).hexdigest())
    def test_fixed_maintenance_entry_never_starts_normal_serve_and_ignores_stale_results(self):
        envelope=self.signed();result={'state':'Unknown','permit_digest':digest(envelope),'retry':False,'runtime_qualified':False,'authorization_restored':False}
        (self.root/'windows-qualification-result.json').write_bytes(canonical(result))
        self.assertEqual(self.run_plan(envelope),result);self.service.run.assert_called_once_with('qualify',timeout=600)
        result['permit_digest']='00'*32;(self.root/'windows-qualification-result.json').write_bytes(canonical(result))
        with self.assertRaisesRegex(AXRError,'unknown_no_retry'):self.run_plan(envelope)
    def test_running_service_bad_signature_and_changed_config_cannot_stage(self):
        envelope=self.signed();self.service.status.return_value={'state':'Running'}
        with self.assertRaisesRegex(AXRError,'must_be_stopped'):self.run_plan(envelope)
        self.service.status.return_value={'state':'Stopped'};envelope['signature']='00'*70
        with self.assertRaises(AXRError):self.run_plan(envelope)
        with self.assertRaisesRegex(AXRError,'configuration_changed'):self.stage.run(self.signed(),self.owner,'00'*32)
        self.assertFalse((self.root/'windows-qualification.json').exists());self.service.run.assert_not_called()
