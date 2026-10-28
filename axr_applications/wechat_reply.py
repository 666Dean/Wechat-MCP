# SPDX-License-Identifier: MIT
"""Fixed reply transaction shared by the independent authority's controllers.

This module cannot issue permissions. The installed controller supplies exact
native/local executors, each of which checks the current TaskContract and Guard.
A database observation is separate from the native input receipt, forever.
"""
from dataclasses import asdict, dataclass
from pathlib import Path
import threading
import time
from axr.aet import AXRError, Action, Resource, digest
from .attempts import claim_attempt
from .wechat_chat_state import NativeCachedDraftWitness


@dataclass(frozen=True)
class ReplyPlan:
    account: str
    recipient: str
    parking: str
    label: str
    parking_label: str
    text: str
    attempt: str

    def validate(self):
        from axr.aet import identifier
        for value in (self.account, self.recipient, self.parking, self.attempt):identifier(value)
        if self.recipient == self.parking:raise AXRError('reply_distinct_parking_required')
        for value in (self.label, self.parking_label):
            if not isinstance(value, str) or not value.strip() or len(value.encode()) > 4000:
                raise AXRError('reply_bounded_search_label_required')
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text.encode()) > 4000:
            raise AXRError('reply_bounded_text_required')
        return self


class ReplyExecutor:
    def __init__(self, database, attempts, *, clock=time.time, monotonic=time.monotonic,
                 pause=time.sleep, observation_rounds=12):
        if type(observation_rounds) is not int or not 1 <= observation_rounds <= 20:
            raise AXRError('reply_observation_budget')
        self.database, self.attempts = database, Path(attempts)
        self.clock, self.monotonic, self.pause = clock, monotonic, pause
        self.rounds = observation_rounds
        self.lock = threading.Lock()

    def submit(self, plan, *, principal, purpose, sources, binding, native, local, check, overwrite_drafts=False):
        """Trusted dependencies only; never pass callables from a model packet.

        ``binding(cid, check)`` returns the pinned main-window metadata, ``native``
        executes one sealed Action, and ``local`` executes a bounded database
        operation under its own read permission. Neither may auto-approve it.
        """
        plan.validate()
        if type(overwrite_drafts) is not bool:raise AXRError('reply_draft_policy_invalid')
        if self.database.account != plan.account:raise AXRError('reply_account_changed')
        if not self.lock.acquire(False):raise AXRError('reply_executor_busy')
        try:
            return self._submit(plan, principal, purpose, tuple(sources), binding, native, local, check, overwrite_drafts)
        finally:self.lock.release()

    def _submit(self, plan, principal, purpose, sources, binding, native, local, check, overwrite_drafts):
        self.attempts.mkdir(mode=0o700, parents=True, exist_ok=True)
        marker = self.attempts / ('reply-' + digest([plan.account, plan.recipient, plan.attempt]) + '.json')
        if marker.exists() or marker.is_symlink():raise AXRError('previous_attempt_never_retry')
        started, began = self.clock(), self.monotonic()
        resource = Resource('wechat', plan.account, plan.recipient)
        application = Resource('wechat', plan.account, 'axr:application-ui')
        def valid():
            check()
            if not 0 <= self.clock()-started <= 180 or not 0 <= self.monotonic()-began <= 180:
                raise AXRError('reply_transaction_expired_or_clock_rollback')
        def window(cid):
            valid();value = binding(cid, valid);valid()
            if type(value) is not dict or not value:raise AXRError('reply_window_binding_required')
            return value
        def metadata(cid, kind, **parameters):
            valid()
            return local(Resource('wechat', plan.account, cid), kind, parameters,
                lambda active: self.database.navigation(cid, kind, active, **parameters), valid)
        def search(after=None):
            parameters = {'since':max(0, int(started)-30), 'until':int(started)+600,
                          'limit':6, 'after':after}
            valid()
            return local(resource, 'messages', parameters,
                lambda active: self.database.search(plan.recipient, check=active, **parameters), valid)
        def perform(mode, target, text, visual):
            valid()
            operations = {'navigate':'application.navigate', 'stage_draft':'application.draft',
                          'read_draft':'status.read', 'send':'messages.send'}
            if mode=='stage_draft':visual={**visual,'draft_policy':'replace' if overwrite_drafts else 'preserve'}
            action = Action(principal, target, operations[mode], purpose,
                {'mode':mode, 'text':text, 'visual_binding':visual},
                sources=sources if mode == 'send' else (),
                destination='wechat:'+resource.key if mode == 'send' else 'local')
            result = native(action, valid)
            valid()
            if type(result) is not dict:raise AXRError('reply_native_result_invalid')
            return result
        def selected(cid, label):
            current = window(cid);at = self.clock()
            result = perform('navigate', application, label, current)
            data = result.get('native') or {}
            if (result.get('receipt', {}).get('state') != 'Completed' or
                    data.get('navigation_invoked') is not True or
                    (data.get('query_echo_match') is not True and data.get('query_input_submitted') is not True) or
                    data.get('main_window_verified') is not True):
                raise AXRError('reply_navigation_unconfirmed')
            rows = metadata(cid, 'recent', query=label, since=int(at)-1)
            now = self.clock()
            if (len(rows) != 1 or rows[0].get('username') != cid or rows[0].get('query') != label or
                    type(rows[0].get('last_click_time')) not in (int, float) or
                    not at-1 <= rows[0]['last_click_time'] <= now+1):
                raise AXRError('reply_unique_fresh_navigation_required')
            return at, current
        valid()
        # Unknown/truncated drafts remain blocked even with explicit replacement.
        draft = metadata(plan.recipient, 'draft')
        if (len(draft)!=1 or type(draft[0].get('draft')) is not str or type(draft[0].get('size')) is not int
            or not 0<=draft[0]['size']<=16000 or draft[0]['size']!=len(draft[0]['draft'].encode())
            or (not overwrite_drafts and (draft[0]['draft']!='' or draft[0]['size']!=0))):
            raise AXRError('reply_existing_or_unknown_draft_preserved')
        _, staged_window = selected(plan.recipient, plan.label)
        result = perform('stage_draft', resource, plan.text, staged_window)
        if (result.get('receipt', {}).get('state') != 'Completed' or
                (result.get('native') or {}).get('draft_match') is not True or
                (result.get('native') or {}).get('send_invoked') is not False):
            raise AXRError('reply_staged_draft_unconfirmed')
        selected(plan.parking, plan.parking_label)
        # The same native read boundary protects the entire cached observation.
        snapshot = local(resource, 'cached-observe', {'text_digest':digest(plan.text)},
            lambda active: asdict(NativeCachedDraftWitness.observe(self.database, plan.account,
                plan.recipient, plan.text, staged_window, active,
                clock=self.clock, monotonic=self.monotonic)), valid)
        witness = NativeCachedDraftWitness(**snapshot)
        at, active_window = selected(plan.recipient, plan.label)
        sealed = local(resource, 'cached-activate', {'text_digest':digest(plan.text), 'search_started':at},
            lambda active: witness.activate(self.database, plan.account, plan.recipient, plan.text,
                plan.label, active_window, at, active, clock=self.clock, monotonic=self.monotonic), valid)
        comparison = perform('read_draft', resource, plan.text, sealed)
        if (comparison.get('receipt', {}).get('state') != 'Completed' or
                (comparison.get('native') or {}).get('draft_match') is not True or
                (comparison.get('native') or {}).get('send_invoked') is not False):
            raise AXRError('reply_exact_input_comparison_failed')
        baseline = search()
        if baseline.get('has_more') is not False:raise AXRError('reply_readback_baseline_incomplete')
        prior = {row.get('server_id') for row in baseline['messages']}
        valid()
        # Permanent before even one byte of the send request can be submitted.
        claim_attempt(marker)
        result = None
        try:result = perform('send', resource, plan.text, sealed)
        except Exception:
            # Cancellation/revocation still stops observation through valid().
            # A lost input response never authorizes a second invocation.
            pass
        cursor = baseline['cursor'];observed = {}
        try:
            for index in range(self.rounds):
                page = search(cursor)
                next_cursor = page['cursor']
                if page['has_more'] and next_cursor == cursor:raise AXRError('reply_readback_cursor_stalled')
                cursor = next_cursor
                for row in page['messages']:
                    if (row.get('text') == plan.text and row.get('sender') == plan.account and
                            row.get('outgoing') is True and type(row.get('server_id')) is int and
                            row['server_id'] > 0 and row['server_id'] not in prior and
                            not row.get('text_truncated') and not row.get('truncated')):
                        observed[row['reference']] = row['server_id']
                if observed and not page['has_more']:break
                if not page['has_more'] and index+1 < self.rounds:self.pause(.5)
                valid()
        except Exception:
            return {'state':'Unknown', 'native_state':'Unknown', 'database_record_observed':False,
                    'observation_complete':False, 'retry':False, 'delivery_confirmed':False}
        # Do not reinterpret the input receipt, even when one row is observed.
        return {'state':'Observed' if len(observed) == 1 else 'Unknown', 'native_state':'Unknown',
            'database_record_observed':len(observed) == 1, 'exact_database_records':len(observed),
            'observation_complete':True, 'send_invoked':(result or {}).get('native', {}).get('send_invoked')
                if isinstance((result or {}).get('native'), dict) else None,
            'retry':False, 'delivery_confirmed':False}
