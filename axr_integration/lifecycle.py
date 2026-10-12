# SPDX-License-Identifier: MIT
"""MCP discovery must not claim a journal or start a second executor.

The operational Service remains exclusive. Only an actual operational tool
activates it; a busy executor is a tool error, not an MCP handshake failure.
"""
import threading
from contextlib import closing
from axr.aet import AXRError
from axr.policy import OwnerStore
from .policy import validate_controls
from .service import Service


class DeferredService:
    def __init__(self,state,*,manual_replies=False,factory=Service):
        if type(manual_replies) is not bool:raise AXRError('manual_reply_control_requires_boolean')
        self.state=state;self.manual_replies=manual_replies;self.factory=factory
        self._delegate=None;self._listener_requested=False;self._lock=threading.RLock();self._busy=False

    def _active(self):
        with self._lock:
            if self._delegate is None:
                try:delegate=self.factory(self.state,manual_replies=self.manual_replies)
                except AXRError as error:
                    self._busy=str(error)=='account_or_journal_busy'
                    raise
                try:
                    if self._listener_requested:delegate.start_listener()
                except BaseException:
                    delegate.close();raise
                self._delegate=delegate
                self._busy=False
            return self._delegate

    def __getattr__(self,name):
        if name.startswith('_'):raise AttributeError(name)
        return getattr(self._active(),name)

    def start_listener(self):
        # MCP initialize/list_tools must stay independent of owner authority.
        with self._lock:
            self._listener_requested=True
            if self._delegate is not None:self._delegate.start_listener()

    def status(self):
        with self._lock:
            if self._delegate is not None:
                return {**self._delegate.status(),'initialization':{'state':'active','operational':True}}
            try:
                # No recovery, purge, adapter, listener or journal lease here.
                with closing(OwnerStore(self.state)) as store:
                    config=validate_controls(store.config())
                    return {'axr':True,'protocol':1,
                        'platform':{'mode':config['mode'],'coverage':'owner_configuration_only',
                                    'send_available':False,'key_extraction':False},
                        'policy_version':store.guard.version,
                        'listener':{k:config.get('listener',{}).get(k,False) for k in ('listen','wake_agent','auto_execute')},
                        'metrics':store.journal.metrics(),'audit_valid':store.journal.verify_audit(),
                        'approval':'local_owner_os_authentication','unknown_retry':False,
                        'reply_submission':'human' if self.manual_replies else 'approved_adapter',
                        'initialization':{'state':'busy' if self._busy else 'idle','operational':False,
                                          'reason':'account_or_journal_busy' if self._busy else None},'restart_required':False}
            except Exception:
                # Setup/Keychain errors must not prevent unrelated Codex chats.
                return {'axr':True,'protocol':1,'reply_submission':'human' if self.manual_replies else 'approved_adapter',
                        'initialization':{'state':'owner_state_unavailable','operational':False},
                        'body_disclosed':False,'send_available':False,'unknown_retry':False}

    def close(self):
        with self._lock:
            if self._delegate is not None:
                self._delegate.close();self._delegate=None
