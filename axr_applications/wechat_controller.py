# SPDX-License-Identifier: MIT
"""Authority-owned asynchronous reply jobs, with reviewed plans and exact grants.

The request channel returns before a native child authenticates back to the
authority. No UI wait holds the authority lock. Installed configuration selects
the helper, selectors, parking conversation and labels; a model selects none.
"""
from dataclasses import asdict, replace
from pathlib import Path
import json
import os
import re
import threading
import time
from axr.aet import AXRError, Action, Provenance, Resource, canonical, digest, identifier
from axr.host import Lease
from .wechat_execution import AuthorityNavigation
from .wechat_reply import ReplyExecutor, ReplyPlan


class AuthorityReplyController:
    def __init__(self, application, configuration, *, executor=None, bridge_factory=AuthorityNavigation):
        self.app, self.kernel = application, application.kernel
        self.guard, self.journal = application.guard, application.journal
        if not self.kernel.development_fixture and (executor is not None or bridge_factory is not AuthorityNavigation):
            raise AXRError('reply_fixture_dependency_forbidden')
        self.configuration = json.loads(canonical(configuration))
        fields={'helper','helper_sha256','endpoint','profiles','attribution_prefix'}
        if not fields<=set(configuration) or set(configuration)-fields-{'attribution_required'}:
            raise AXRError('reply_controller_configuration_invalid')
        if type(configuration.get('attribution_required',True)) is not bool:
            raise AXRError('reply_controller_configuration_invalid')
        if (not isinstance(configuration['helper_sha256'],str) or
                re.fullmatch('[0-9a-f]{64}',configuration['helper_sha256']) is None):
            raise AXRError('reply_controller_helper_pin_required')
        profiles = configuration['profiles']
        if type(profiles) is not dict or not 2 <= len(profiles) <= 4096:
            raise AXRError('reply_controller_profiles_required')
        for cid, profile in profiles.items():
            if (cid not in application.resources or type(profile) is not dict or
                    set(profile) != {'label','visual_binding'} or not isinstance(profile['label'],str) or
                    not profile['label'].strip() or len(profile['label'].encode()) > 4000 or
                    type(profile['visual_binding']) is not dict or not profile['visual_binding']):
                raise AXRError('reply_controller_profile_invalid')
            if cid.endswith('@chatroom') or cid.startswith('gh_') or cid in ('filehelper','axr:application-ui'):
                raise AXRError('reply_private_conversation_required')
            if not self.kernel.development_fixture:
                visual=profile['visual_binding']
                paths={'path','header_path','account_path','identity_path','send_path','search_path','search_result_path'}
                if (set(visual)!=paths|{'executable_hash','expected_title','expected_identity','search_result_title'} or
                        visual['expected_identity']!=cid or
                        not isinstance(visual['executable_hash'],str) or
                        re.fullmatch('[0-9a-f]{64}',visual['executable_hash']) is None or
                        any(not isinstance(visual[key],str) or not visual[key] or len(visual[key].encode())>4000
                            for key in ('expected_title','search_result_title')) or
                        any(type(visual[key]) is not list or len(visual[key])>16 or
                            any(type(index) is not int or not 0<=index<500 for index in visual[key]) for key in paths)):
                    raise AXRError('reply_controller_selector_profile_invalid')
        prefix = configuration['attribution_prefix']
        if not isinstance(prefix,str) or not prefix.strip() or len(prefix.encode()) > 1000:
            raise AXRError('reply_controller_attribution_required')
        self.profile_digest = digest(self.configuration)
        self.executor = executor or ReplyExecutor(application.database, self.kernel.store.directory/'reply-attempts')
        self.bridge_factory = bridge_factory
        self.active = {};self.closed = False
        self.application_resource = Resource('wechat', application.account, 'axr:application-ui')

    def propose(self, peer, capability, task, resource, parameters):
        if set(parameters) != {'conversation_id','draft_id'}:raise AXRError('wechat_authority_parameters_invalid')
        cid = resource.conversation_id
        profiles = self.configuration['profiles']
        if cid not in profiles:raise AXRError('reply_target_not_configured')
        draft_id = identifier(parameters['draft_id'])
        draft = self.app.context(peer,task,resource,draft_id,'manual-draft')
        if self.configuration.get('attribution_required',True) and not draft['text'].startswith(self.configuration['attribution_prefix']):
            raise AXRError('reply_explicit_ai_attribution_required')
        parking = next(other for other in profiles if other != cid)
        plan = ReplyPlan(self.app.account,cid,parking,profiles[cid]['label'],profiles[parking]['label'],
                         draft['text'],draft_id).validate()
        action = Action(peer.principal,resource,'messages.send',task['goal_digest'],
            {'reply_plan':asdict(plan),'profile_digest':self.profile_digest},
            sources=tuple(Provenance(Resource(**source['resource']),source['reference'],source['data_class'])
                          for source in draft['sources']),destination='wechat:'+resource.key)
        required={'messages.read','status.read','application.navigate','application.draft','messages.send'}
        needed={resource.key,self.app.resources[parking].key,self.application_resource.key}
        if (not required<=set(task['operations']) or not needed<=set(task['resources']) or
                not {resource.key,self.app.resources[parking].key}<=set(task['sources']) or
                'personal' not in task['classes'] or
                not {'local',action.destination}<=set(task['destinations'])):
            raise AXRError('reply_task_scope_incomplete')
        # Check the signed task before creating an approval request. A missing
        # exact Guard grant may be reviewed; a task/sandbox failure may not.
        try:self.kernel.access(peer,capability,action)
        except AXRError as error:
            if str(error) != 'authority_missing_expired_revoked_or_exhausted':raise
        self.app.ensure_context_capacity(peer)
        job = self.journal.propose(action,ttl=180)
        self.journal.transition(job,peer.principal,'PolicyChecked')
        self.journal.transition(job,peer.principal,'AwaitingApproval')
        handle = self.app.remember(peer,task,resource,{'kind':'pending-send','job_id':job})
        self.kernel.integrity.persist()
        if not self.app.manual_approval_required:
            from axr.owner import approve
            approve(self.kernel.store,job,peer.principal)
            self.journal.transition(job,peer.principal,'Ready');self.kernel.integrity.persist()
            return self.schedule(peer,capability,task,handle)
        return {'id':handle,'state':'AwaitingApproval','execution_id':action.execution_id,
                'agent_sent':False,'retry':False}

    def status(self, peer, task, handle):
        context, job, action = self.app.pending(handle)
        if (context['kind'] != 'pending-send' or context['contract'] != task['id'] or
                action.principal != peer.principal):raise AXRError('wechat_pending_job_scope_changed')
        result = {'id':handle,'state':job['state'],'execution_id':action.execution_id,
                  'retry':False,'delivery_confirmed':False}
        if job['state'] in ('Unknown','FailedSafe'):
            try:result['observation'] = self.journal.result(job['id'],peer.principal,self.guard.version)
            except AXRError:pass
        return result

    def schedule(self, peer, capability, task, handle):
        pending, job, action = self.app.pending(handle)
        if (pending['kind'] != 'pending-send' or pending['contract'] != task['id'] or
                action.principal != peer.principal):raise AXRError('wechat_pending_job_scope_changed')
        if job['state'] in ('Executing','Unknown','FailedSafe','Expired'):
            return self.status(peer,task,handle)
        if job['state'] != 'Ready':raise AXRError('wechat_exact_owner_approval_required')
        if self.closed or self.active:raise AXRError('reply_executor_busy_or_closed')
        if action.payload['profile_digest'] != self.profile_digest:raise AXRError('reply_controller_configuration_changed')
        self.kernel.access(peer,capability,action)
        stop = threading.Event()
        self.kernel.security.commit(action)
        grant, version = self.guard.consume(action)
        self.journal.transition(job['id'],peer.principal,'Prepared',grant_id=grant,
                                policy_version=version,epoch=self.kernel.epoch)
        self.journal.transition(job['id'],peer.principal,'Executing')
        self.kernel.integrity.persist()
        job = self.journal.get(job['id'],peer.principal)
        worker = threading.Thread(target=self._run,args=(peer,capability,task,job,action,stop),daemon=True)
        self.active[job['id']] = {'stop':stop,'thread':worker,'contract':task['id']}
        try:worker.start()
        except BaseException:
            self.active.pop(job['id'],None)
            self.journal.transition(job['id'],peer.principal,'FailedSafe');self.kernel.integrity.persist()
            raise
        return self.status(peer,task,handle)

    def _run(self, peer, capability, task, job, reviewed, stop):
        kernel = self.kernel;grants = [job['grant_id']];epoch, version = job['epoch'], job['policy_version']
        start_wall, start_mono = kernel.clock(), time.monotonic()
        proof_actions = []
        result = {'state':'Unknown','database_record_observed':False,'retry':False,'delivery_confirmed':False}
        def check():
            with kernel.lock:
                if stop.is_set() or self.closed or kernel.closed:raise AXRError('reply_controller_stopped')
                kernel._check_integrity()
                if (kernel.epoch != epoch or self.guard.version != version or
                        digest(self.configuration) != self.profile_digest or
                        job['expires'] <= kernel.clock() or task['expires'] <= kernel.clock() or
                        not 0 <= kernel.clock()-start_wall <= 180 or
                        not 0 <= time.monotonic()-start_mono <= 180):
                    raise AXRError('reply_controller_scope_expired_or_changed')
                if (not kernel.development_fixture and
                        digest(kernel.store.config()['application'].get('reply_navigation')) != self.profile_digest):
                    raise AXRError('reply_controller_configuration_changed')
                kernel._task(peer,capability)
                row, _ = kernel.security._contract(task['id'])
                if row['revoked']:raise AXRError('reply_controller_contract_revoked')
                # The parent plan was reserved exactly once. Revoking that
                # precise approval must also stop later derived phases, even
                # when scoped revocation leaves the global version unchanged.
                self.guard.revalidate(reviewed,job['grant_id'],version)
                current = self.journal.get(job['id'],peer.principal)
                if current['state'] != 'Executing' or self.journal.action(current).seal != reviewed.seal:
                    raise AXRError('reply_controller_plan_changed')
        def authorize(action):
            check()
            # Native contract/sandbox checks run before issuance. Only a missing
            # exact AET may be filled from this owner-reviewed fixed plan.
            try:kernel.access(peer,capability,action)
            except AXRError as error:
                if str(error) != 'authority_missing_expired_revoked_or_exhausted':raise
            common = dict(principal=peer.principal,purpose=action.purpose,
                expires_at=min(job['expires'],task['expires'],kernel.clock()+120),max_uses=1,
                workflow=action.workflow)
            try:
                for source in action.sources:
                    source_read = replace(action,resource=source.resource,operation='messages.read',
                                          payload={},sources=(),destination='local')
                    grants.append(self.guard._issue_owner(**common,resource=source.resource,
                        operations=['messages.read'],classes=[source.data_class],intent=source_read.seal))
                    if action.destination != 'local':
                        disclosure = replace(action,resource=source.resource,operation='disclosure.send',
                            payload={'output_seal':action.seal},sources=(source,))
                        grants.append(self.guard._issue_owner(**common,resource=source.resource,
                            operations=['disclosure.send'],destinations=[action.destination],
                            classes=[source.data_class],intent=disclosure.seal))
                grants.append(self.guard._issue_owner(**common,resource=action.resource,
                    operations=[action.operation],destinations=[action.destination],
                    classes=sorted({source.data_class for source in action.sources}) or ['workspace-normal'],
                    intent=action.seal))
            finally:kernel.integrity.persist()
            kernel.access(peer,capability,action)
        def enroll(actual):
            with kernel.lock:
                check()
                registry = kernel.wechat_registry
                registry.enroll(actual,'handler','wechat:navigation',lambda:registry.user)
                kernel.wechat_handlers['native'] = registry.accept(actual)
        def prepare(action,actual):
            with kernel.lock:
                check();authorize(action)
                proof = kernel.prepare_commit(peer,capability,action)
                proof_actions.append(action)
                return proof
        def release(actual):
            with kernel.lock:
                registry=kernel.wechat_registry
                registry.retire(actual)
                current=kernel.wechat_handlers.get('native')
                if current and (current.pid,current.birth)==(actual['pid'],actual['birth']):
                    kernel.wechat_handlers.pop('native',None)
        def receipt(execution):
            with kernel.lock:return kernel.receipt(peer,capability,execution)
        def local(resource,kind,parameters,operation,active):
            with kernel.lock:
                active()
                action = Action(peer.principal,resource,'messages.read',reviewed.purpose,
                                {'kind':kind,**parameters},
                                sources=(Provenance(resource,'reply-local:'+kind,'personal'),))
                authorize(action)
                return self.app.execute(peer,capability,action,operation)['result']
        try:
            check()
            config = self.configuration
            bridge = self.bridge_factory(config['helper'],config['helper_sha256'],config['endpoint'],
                kernel.store.directory/'native-attempts',enroll_handler=enroll,prepare=prepare,
                receipt=receipt,release_handler=release,
                **({'owner_user':kernel.wechat_registry.user} if os.name=='nt' and self.bridge_factory is AuthorityNavigation else {}))
            def native(action,active):return bridge.invoke(action,check=active)
            def binding(cid,active):
                visual = config['profiles'][cid]['visual_binding']
                action = Action(peer.principal,self.application_resource,'status.read',reviewed.purpose,
                    {'mode':'binding','text':'AXR main-window metadata','visual_binding':visual})
                result = native(action,active)
                if (result.get('receipt',{}).get('state') != 'Completed' or
                        (result.get('native') or {}).get('main_window_verified') is not True):
                    raise AXRError('reply_main_window_binding_unconfirmed')
                return result['native']['binding']
            plan = ReplyPlan(**reviewed.payload['reply_plan'])
            with Lease(Path.home()/'.stellaria-axr'/'leases',['wechat',plan.account]):
                result = self.executor.submit(plan,principal=peer.principal,purpose=reviewed.purpose,
                    sources=reviewed.sources,binding=binding,native=native,local=local,check=check)
        except Exception as error:
            code = str(error)
            result = {'state':'Unknown','database_record_observed':False,'retry':False,'delivery_confirmed':False,
                      'error':code if isinstance(error,AXRError) and code.replace('_','').isalnum() and len(code)<=100
                              else 'reply_failed_safe'}
        finally:
            with kernel.lock:
                try:
                    # Keep terminal native state immutable; resolve only still
                    # Prepared/Executing children whose response was lost.
                    for action in proof_actions:
                        row = kernel.db.execute('SELECT nonce,state,payload FROM authority_commits WHERE execution_id=?',
                                                (action.execution_id,)).fetchone()
                        if row and row['state'] in ('Prepared','Executing'):
                            stored=kernel._commit_row(row)
                            kernel._save_commit(row['nonce'],'Unknown' if row['state']=='Executing' else 'FailedSafe',
                                                stored['body'],stored['origin'])
                    for grant in grants:self.guard.revoke_scoped(grant)
                    self.journal.save_result(job['id'],peer.principal,result,version)
                    self.journal.transition(job['id'],peer.principal,'Unknown')
                    kernel.integrity.persist()
                finally:self.active.pop(job['id'],None)

    def stop(self, scope='kernel'):
        # Called by trusted security containment/owner revocation before waiting
        # for workers. A client/model cannot invoke this as an owner endpoint.
        for item in list(self.active.values()):
            if scope in ('kernel',item['contract']):item['stop'].set()

    def close(self):
        self.closed = True;self.stop()
        for item in list(self.active.values()):item['thread'].join(timeout=5)
