# SPDX-License-Identifier: MIT
"""Authority-owned bounded MCP reads, separate disclosure, and manual drafts.

No model-supplied action, destination, role, SQL or key crosses this API. The
kernel authenticates the client before dispatch; native operations use the
registered credential handler and the existing one-use commit protocol.
"""
import uuid
from dataclasses import asdict
from axr.aet import AXRError, Action, Provenance, Resource, canonical, digest, identifier
from axr_integration.content_safety import mask_credentials


METHODS = frozenset({'status', 'read_context', 'disclose_context', 'prepare_reply', 'submit_reply',
                     'reply_status', 'receipt', 'execute'})


def attach_windows_mcp(kernel, configuration):
    import os
    if os.name!='nt':raise AXRError('windows_mcp_registration_required')
    from . import _wechat_credentials
    from .wechat_database import NativeDatabase
    resource = Resource(**configuration['resources'][0])
    handler = kernel.handler_for('messages.read',resource)
    consumer = _wechat_credentials.WeChatConsumer(handler.witness, canonical(configuration).decode())
    database = NativeDatabase(consumer,configuration['account_id'])
    def save_setting(required,generation):
        policy = kernel.store.config()
        application = {**policy['application'],'manual_approval_required':required,
                       'approval_setting_generation':generation}
        kernel.store.seal_config({**policy,'application':application})
    application = WeChatMCPApplication(kernel,database,configuration['account_id'],
        [row['conversation_id'] for row in configuration['resources']],handler,
        destination=configuration.get('mcp_destination','model:codex-mcp'),
        manual_approval_required=configuration.get('manual_approval_required',True),
        approval_setting_generation=configuration.get('approval_setting_generation',0),
        save_approval_setting=save_setting)
    kernel.application = application.dispatch
    kernel.application_owner = application.owner_dispatch
    if configuration.get('reply_navigation'):
        from .wechat_controller import AuthorityReplyController
        application.replies=AuthorityReplyController(application,configuration['reply_navigation'])
        kernel.application_close=application.replies.close
        kernel.security.revoke_domain=application.replies.stop
    return application


class WeChatMCPApplication:
    def __init__(self, kernel, database, account, conversations, handler, *, destination,
                 manual_approval_required=True, approval_setting_generation=0, save_approval_setting=None):
        self.kernel, self.database, self.handler = kernel, database, handler
        self.account, self.destination = identifier(account), identifier(destination)
        if (type(manual_approval_required) is not bool or type(approval_setting_generation) is not int or
                approval_setting_generation<0):raise AXRError('wechat_approval_setting_invalid')
        self.manual_approval_required = manual_approval_required
        self.approval_setting_generation = approval_setting_generation
        self.save_approval_setting = save_approval_setting
        self.resources = {identifier(cid):Resource('wechat', account, cid) for cid in conversations}
        if not self.resources or handler.role != 'handler' or database.account != account:
            raise AXRError('wechat_authority_registration_invalid')
        if not kernel.development_fixture:
            from .wechat_database import NativeDatabase
            if not isinstance(database, NativeDatabase):
                raise AXRError('wechat_native_consumer_required')
        self.journal, self.guard = kernel.store.journal, kernel.security.guard
        self.replies = None

    def dispatch(self, peer, packet):
        if peer.role != 'client':raise AXRError('authority_client_channel_required')
        if type(packet) is not dict or set(packet) != {'method','parameters','capability'}:
            raise AXRError('wechat_authority_request_invalid')
        method, parameters = packet['method'], packet['parameters']
        if method not in METHODS or type(parameters) is not dict:
            raise AXRError('wechat_authority_method_not_registered')
        if method == 'status':
            if parameters:raise AXRError('wechat_authority_parameters_invalid')
            state = self.kernel.security.status()['state']
            return {'backend':'independent-authority', 'authority_connected':True,
                'trust_state':state, 'send_available':False, 'body_disclosed':False,
                'unknown_retry':False, 'manual_replies':True,
                'reply_controller_available':self.replies is not None,
                'manual_approval_required':self.manual_approval_required}
        capability = packet['capability']
        if method == 'receipt':
            if set(parameters) != {'execution_id'}:raise AXRError('wechat_authority_parameters_invalid')
            return self.kernel.receipt(peer, capability, identifier(parameters['execution_id']))
        task = self.kernel._task(peer, capability)
        if method == 'reply_status':
            if set(parameters)!={'job_id'}:raise AXRError('wechat_authority_parameters_invalid')
            if self.replies is None:raise AXRError('wechat_reply_controller_unavailable')
            return self.replies.status(peer,task,parameters['job_id'])
        if method == 'execute':
            if set(parameters) != {'job_id'}:raise AXRError('wechat_authority_parameters_invalid')
            return self.execute_pending(peer,capability,task,parameters['job_id'])
        try:
            cid = parameters['conversation_id']
            resource = self.resources[cid]
        except (KeyError, TypeError):
            raise AXRError('wechat_conversation_not_authorized') from None
        if method == 'read_context':
            return self.read(peer, capability, task, resource, parameters)
        if method == 'disclose_context':
            return self.disclose(peer, capability, task, resource, parameters)
        if method == 'submit_reply':
            if self.replies is None:raise AXRError('wechat_reply_controller_unavailable')
            return self.replies.propose(peer,capability,task,resource,parameters)
        return self.prepare(peer, capability, task, resource, parameters)

    def execute(self, peer, capability, action, operation):
        proof = self.kernel.prepare_commit(peer, capability, action)
        # The handler is fixed by registration, not by client JSON.
        if (proof['body']['helper'], proof['body']['helper_pid'], proof['body']['helper_birth']) != (
                self.handler.witness, self.handler.pid, self.handler.birth):
            raise AXRError('wechat_credential_handler_mismatch')
        self.kernel.claim_commit(self.handler, proof)
        def check():
            self.kernel.preflight_commit(self.handler, proof)
        try:
            check()
            value = operation(check)
            check()
            receipt = self.kernel.observe(self.handler, proof, verified=True,
                                           evidence_digest=digest(value))
            if receipt['state'] != 'Completed':raise AXRError('wechat_authority_outcome_unknown')
            return {'state':'Completed', 'execution_id':action.execution_id, 'result':value,
                    'retry':False, 'agent_sent':False, 'delivery_confirmed':False}
        except Exception:
            try:self.kernel.observe(self.handler, proof, verified=False, evidence_digest=digest('failed-safe'))
            except Exception:pass
            raise

    def ensure_context_capacity(self, peer, additional=1):
        self.journal.db.execute('DELETE FROM contexts WHERE expires<=?', (self.journal.clock(),))
        count = self.journal.db.execute('SELECT count(*) FROM contexts WHERE principal=?', (peer.principal,)).fetchone()[0]
        if count+additional > 50:raise AXRError('wechat_context_capacity')

    def remember(self, peer, task, resource, data):
        self.ensure_context_capacity(peer)
        return self.journal.remember(peer.principal, resource,
            {**data, 'contract':task['id']}, self.guard.version, ttl=300)

    def context(self, peer, task, resource, handle, kind):
        data = self.journal.context(identifier(handle), peer.principal, resource, self.guard.version)
        if data.get('kind') != kind or data.get('contract') != task['id']:
            raise AXRError('wechat_context_task_or_kind_mismatch')
        return data

    def read(self, peer, capability, task, resource, parameters):
        if set(parameters)-{'conversation_id','since','until','cursor','limit'}:
            raise AXRError('wechat_authority_parameters_invalid')
        since, until, limit = (parameters.get('since',0), parameters.get('until',2**63-1), parameters.get('limit',6))
        if (any(type(value) is not int for value in (since,until,limit)) or
                not 0 <= since <= until <= 2**63-1 or not 1 <= limit <= 6):
            raise AXRError('wechat_native_search_range')
        after = None
        if parameters.get('cursor') is not None:
            cursor = self.context(peer, task, resource, parameters['cursor'], 'cursor')
            if cursor['filters'] != [since,until]:raise AXRError('cursor_filter_mismatch')
            after = cursor['after']
        action = Action(peer.principal, resource, 'messages.read', task['goal_digest'],
                        {'since':since, 'until':until, 'limit':limit, 'after':after})
        def read(check):
            page = self.database.search(resource.conversation_id, check=check,
                since=since, until=until, after=after, limit=limit)
            messages = page['messages']
            if (len(messages)>6 or len(canonical(messages))>24000 or
                    any(not isinstance(row.get('text'),str) or len(row['text'].encode())>4000 for row in messages)):
                raise AXRError('wechat_mcp_context_budget')
            check()
            self.ensure_context_capacity(peer,2 if page['has_more'] else 1)
            context = self.remember(peer,task,resource,{'kind':'messages','messages':messages})
            cursor = self.remember(peer,task,resource,{'kind':'cursor', 'after':page['cursor'],
                'filters':[since,until]}) if page['has_more'] else None
            return {'context_id':context, 'cursor':cursor, 'count':len(messages),
                'scanned':page['scanned'], 'has_more':page['has_more'],
                'complete_history':False, 'body_disclosed':False}
        return self.execute(peer, capability, action, read)

    def disclose(self, peer, capability, task, resource, parameters):
        if set(parameters) != {'conversation_id','context_id'}:
            raise AXRError('wechat_authority_parameters_invalid')
        context = self.context(peer, task, resource, parameters['context_id'], 'messages')
        sources = tuple(Provenance(resource, row['reference'], 'personal') for row in context['messages'])
        action = Action(peer.principal, resource, 'disclosure.send', task['goal_digest'],
            {'context_id':parameters['context_id'], 'content_digest':digest(context)},
            sources=sources, destination=self.destination)
        # Task scope is checked now, but it never substitutes for exact-content
        # owner approval of the subsequent disclosure action.
        try:self.kernel.access(peer,capability,action)
        except AXRError as error:
            # This code is reached only after native TaskContract checks pass.
            # Missing exact Guard consent becomes an owner-review proposal.
            if str(error)!='authority_missing_expired_revoked_or_exhausted':raise
        self.ensure_context_capacity(peer)
        job = self.journal.propose(action,ttl=300)
        self.journal.transition(job,peer.principal,'PolicyChecked')
        self.journal.transition(job,peer.principal,'AwaitingApproval')
        handle = self.remember(peer,task,resource,{'kind':'pending-disclosure','job_id':job})
        self.kernel.integrity.persist()
        if not self.manual_approval_required:
            from axr.owner import approve
            approve(self.kernel.store,job,peer.principal)
            self.journal.transition(job,peer.principal,'Ready')
            self.kernel.integrity.persist()
            return self.execute_pending(peer,capability,task,handle)
        return {'id':handle,'state':'AwaitingApproval','execution_id':action.execution_id,
                'body_disclosed':False,'retry':False}

    def pending(self, handle):
        row = self.journal.db.execute('SELECT * FROM contexts WHERE id=?',(identifier(handle),)).fetchone()
        if row is None or row['expires']<=self.journal.clock() or row['policy_version']!=self.guard.version:
            raise AXRError('context_expired_revoked_or_out_of_scope')
        context = self.journal.vault.open(row['payload'],handle)
        kinds={'pending-disclosure':'disclosure.send','pending-send':'messages.send'}
        if context.get('kind') not in kinds:raise AXRError('wechat_pending_job_required')
        job = self.journal.get(context['job_id'],row['principal'])
        action = self.journal.action(job)
        if action.resource.key!=row['resource'] or action.principal!=row['principal'] or action.operation!=kinds[context['kind']]:
            raise AXRError('wechat_pending_job_scope_changed')
        return context,job,action

    def owner_dispatch(self, peer, packet):
        self.kernel._owner(peer)
        phase = packet.get('phase')
        if phase in ('review-approval-setting','approve-approval-setting'):
            return self.owner_approval_setting(peer,packet)
        allowed = {'phase','job_id'} if phase=='review-application' else {'phase','job_id','challenge_id','owner_signature'}
        if phase not in ('review-application','approve-application') or set(packet)!=allowed:
            raise AXRError('wechat_owner_review_invalid')
        context,job,action = self.pending(packet['job_id'])
        row,task = self.kernel.security._contract(context['contract'])
        now = self.kernel.clock()
        if (task['owner']!=peer.principal or task['agent']!=action.principal or row['revoked'] or
                task['expires']<=now or job['state']!='AwaitingApproval' or job['expires']<=now):
            raise AXRError('wechat_owner_review_expired_or_changed')
        if phase=='review-application':
            self.kernel.challenges = {key:value for key,value in self.kernel.challenges.items() if value['expires']>now}
            if len(self.kernel.challenges)>=16:raise AXRError('owner_challenge_capacity')
            nonce = uuid.uuid4().hex
            challenge = {'version':2,'kind':'wechat-application-review','root_id':self.kernel.root_id,
                'epoch':self.kernel.epoch,'nonce':nonce,'peer':peer.witness,'owner':peer.principal,
                'job_id':packet['job_id'],'seal':action.seal,'contract':task['id'],
                'expires':min(now+60,task['expires'],job['expires'])}
            self.kernel.challenges[nonce] = challenge
            review={'action':asdict(action)}
            if action.operation=='disclosure.send':
                preview = self.journal.context(action.payload['context_id'],action.principal,action.resource,self.guard.version)
                review['messages']=[{'reference':message['reference'],'text':mask_credentials(message['text'])[0]}
                                    for message in preview['messages']]
            return {'challenge':challenge,'review':review}
        challenge = self.kernel.challenges.pop(packet['challenge_id'],None)
        if (not challenge or challenge.get('kind')!='wechat-application-review' or challenge['peer']!=peer.witness or
                challenge['owner']!=peer.principal or challenge['job_id']!=packet['job_id'] or
                challenge['contract']!=task['id'] or challenge['seal']!=action.seal or challenge['expires']<=now):
            raise AXRError('wechat_owner_review_expired_or_changed')
        from axr import _axr_native as native
        try:valid = native.verify_root_signature(self.kernel.owner_public_key,canonical(challenge),bytes.fromhex(packet['owner_signature']))
        except Exception:valid = False
        if not valid:raise AXRError('owner_presence_signature_required')
        from axr.owner import approve
        approve(self.kernel.store,job['id'],action.principal)
        self.journal.transition(job['id'],action.principal,'Ready')
        self.kernel.integrity.persist()
        return {'approved':True,'job_id':packet['job_id'],'body_disclosed':False}

    def owner_approval_setting(self, peer, packet):
        phase,required = packet.get('phase'),packet.get('manual_approval_required')
        fields = {'phase','manual_approval_required'}
        if phase=='approve-approval-setting':fields |= {'challenge_id','owner_signature'}
        if set(packet)!=fields or type(required) is not bool:
            raise AXRError('wechat_approval_setting_invalid')
        now = self.kernel.clock()
        if phase=='review-approval-setting':
            self.kernel.challenges = {key:value for key,value in self.kernel.challenges.items() if value['expires']>now}
            if len(self.kernel.challenges)>=16:raise AXRError('owner_challenge_capacity')
            nonce = uuid.uuid4().hex
            challenge = {'version':2,'kind':'wechat-approval-setting','root_id':self.kernel.root_id,
                'epoch':self.kernel.epoch,'nonce':nonce,'peer':peer.witness,'owner':peer.principal,
                'required':required,'generation':self.approval_setting_generation,'expires':now+60}
            self.kernel.challenges[nonce] = challenge
            return {'challenge':challenge,'review':{'manual_approval_required':required,
                'existing_task_scope_unchanged':True,'agent_sent':False}}
        challenge = self.kernel.challenges.pop(packet['challenge_id'],None)
        if (not challenge or challenge.get('kind')!='wechat-approval-setting' or challenge['peer']!=peer.witness or
                challenge['owner']!=peer.principal or challenge['required'] is not required or
                challenge['generation']!=self.approval_setting_generation or challenge['expires']<=now):
            raise AXRError('wechat_owner_review_expired_or_changed')
        from axr import _axr_native as native
        try:valid = native.verify_root_signature(self.kernel.owner_public_key,canonical(challenge),bytes.fromhex(packet['owner_signature']))
        except Exception:valid = False
        if not valid:raise AXRError('owner_presence_signature_required')
        if not callable(self.save_approval_setting):raise AXRError('wechat_approval_setting_store_unavailable')
        generation = self.approval_setting_generation+1
        self.save_approval_setting(required,generation)
        self.manual_approval_required,self.approval_setting_generation = required,generation
        self.kernel.integrity.persist()
        return {'manual_approval_required':required,'generation':generation,'existing_task_scope_unchanged':True}

    def execute_pending(self, peer, capability, task, handle):
        pending,job,action = self.pending(handle)
        if pending['contract']!=task['id'] or action.principal!=peer.principal:
            raise AXRError('wechat_pending_job_scope_changed')
        if pending['kind']=='pending-send':
            if self.replies is None:raise AXRError('wechat_reply_controller_unavailable')
            return self.replies.schedule(peer,capability,task,handle)
        if job['state'] in ('Completed','Unknown','FailedSafe','Expired'):
            return self.journal.receipt(job['id'],peer.principal)
        if job['state']!='Ready':raise AXRError('wechat_exact_owner_approval_required')
        self.kernel.access(peer,capability,action)
        self.guard.check(action)
        self.journal.transition(job['id'],peer.principal,'Prepared')
        self.journal.transition(job['id'],peer.principal,'Executing')
        def disclose(check):
            check()
            context = self.context(peer,task,action.resource,action.payload['context_id'],'messages')
            if digest(context)!=action.payload['content_digest']:raise AXRError('wechat_disclosure_context_changed')
            messages = [{key:message[key] for key in ('reference','created','sender','outgoing')}
                        | {'text':mask_credentials(message['text'])[0], 'data_class':'personal'}
                        for message in context['messages']]
            self.journal.taint_disclosure(peer.principal,action.resource,'personal')
            return {'messages':messages,'body_disclosed':True,'source':asdict(action.resource),
                    'external_content_untrusted':True}
        try:
            result = self.execute(peer,capability,action,disclose)
            self.journal.transition(job['id'],peer.principal,'Verifying')
            self.journal.transition(job['id'],peer.principal,'Completed')
            self.kernel.integrity.persist()
            return result
        except Exception:
            self.journal.transition(job['id'],peer.principal,'Unknown')
            self.kernel.integrity.persist()
            raise

    def prepare(self, peer, capability, task, resource, parameters):
        if set(parameters) != {'conversation_id','text','context_ids'}:
            raise AXRError('wechat_authority_parameters_invalid')
        text, handles = parameters['text'], parameters['context_ids']
        if (not isinstance(text,str) or not text.strip() or len(text.encode())>4000 or
                type(handles) is not list or not 1 <= len(handles) <= 6):
            raise AXRError('wechat_draft_parameters_invalid')
        sources = list(self.journal.disclosure_taint(peer.principal))
        for handle in handles:
            context = self.context(peer,task,resource,handle,'messages')
            sources.extend(Provenance(resource,row['reference'],'personal') for row in context['messages'])
        action = Action(peer.principal,resource,'reply.prepare',task['goal_digest'],
            {'text':text,'context_ids':handles},sources=tuple(sources))
        def prepare(check):
            check()
            handle = self.remember(peer,task,resource,{'kind':'manual-draft','text':text,
                'sources':[asdict(source) for source in sources]})
            return {'draft_id':handle,'submission':'human','agent_sent':False}
        return self.execute(peer,capability,action,prepare)
