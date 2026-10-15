# SPDX-License-Identifier: MIT
"""Local cached-draft transition witness, not a platform identity or send permission.

The authenticated caller supplies a read-only account-qualified connection and calls
this inside its account lease. No issuer, arbitrary SQL, GUI action, or MCP tool is
exposed here. A native sender must still compare the exact input immediately before
one submission, under an AXR proof sealing the returned binding.
"""
from dataclasses import dataclass
import time
from axr.aet import AXRError, digest


@dataclass(frozen=True)
class CachedDraftWitness:
    account: str
    recipient: str
    text_digest: str
    window_digest: str
    observed_wall: float
    observed_monotonic: float
    snapshot_digest: str

    @classmethod
    def observe(cls, connection, account, recipient, text, window, check, *, clock=time.time, monotonic=time.monotonic):
        check()
        if not isinstance(text,str) or not text or len(text.encode())>16000:
            raise AXRError('bounded_exact_draft_required')
        # Only return rows containing this complete proposed text; never export drafts.
        rows=connection.query('SELECT username,CASE WHEN length(CAST(draft AS BLOB))<=16000 THEN draft ELSE NULL END AS draft FROM SessionTable WHERE instr(draft,?)>0 LIMIT 3',(text,))
        check()
        if len(rows)!=1 or rows[0]['username']!=recipient or rows[0]['draft']!=text:
            raise AXRError('unique_exact_cached_draft_required')
        return cls(account,recipient,digest(text),digest(window),clock(),monotonic(),digest(rows))

    def activate(self, general, session, account, recipient, text, query, window, search_started, check,
                 *, clock=time.time, monotonic=time.monotonic):
        check();now=clock();elapsed=monotonic()-self.observed_monotonic
        if not 0<=elapsed<=60 or not 0<=now-self.observed_wall<=60:
            raise AXRError('cached_draft_witness_expired')
        if (account,recipient,digest(text),digest(window)) != (self.account,self.recipient,self.text_digest,self.window_digest):
            raise AXRError('cached_draft_scope_changed')
        if not self.observed_wall<=search_started<=now or now-search_started>30:
            raise AXRError('fresh_post_cache_navigation_required')
        rows=general.query('SELECT username,query,last_click_time FROM SearchRecent WHERE query=? AND last_click_time>=? LIMIT 3',
                           (query,int(search_started)-1))
        check()
        if (len(rows)!=1 or rows[0]['username']!=recipient or rows[0]['query']!=query or
            not search_started-1<=rows[0]['last_click_time']<=now+1):
            raise AXRError('unique_fresh_search_identity_required')
        rows2=session.query('SELECT CASE WHEN length(CAST(draft AS BLOB))<=16000 THEN draft ELSE NULL END AS draft FROM SessionTable WHERE username=? LIMIT 2',(recipient,))
        check()
        # WeChat consumes the saved draft when activating its conversation. Empty
        # cache is valid only after the exact cached snapshot and fresh selection.
        if len(rows2)!=1 or rows2[0]['draft'] not in ('',text):
            raise AXRError('activated_draft_changed')
        return {**window,'recipient_assurance':'cached_exact_draft_and_fresh_search',
                'recipient_witness':digest([self.snapshot_digest,self.text_digest,self.window_digest,rows,rows2,search_started])}
