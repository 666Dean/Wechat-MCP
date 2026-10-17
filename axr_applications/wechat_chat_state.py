# SPDX-License-Identifier: MIT
"""Mac cached-draft protocol adapted to the opaque native WCDB consumer.

No SQL or key enters this facade. These are local evidence checks inside the
trusted controller, not model tools, target selection, or send authorization.
"""
import time
from axr.aet import AXRError, digest
from adapters.macos.chat_state import CachedDraftWitness


class NativeCachedDraftWitness(CachedDraftWitness):
    @classmethod
    def observe(cls, database, account, recipient, text, window, check,
                *, clock=time.time, monotonic=time.monotonic):
        check()
        if database.account!=account:raise AXRError('cached_draft_account_mismatch')
        if not isinstance(text,str) or not text or len(text.encode())>16000:
            raise AXRError('bounded_exact_draft_required')
        rows=database.navigation(recipient,'unique_draft',check,text=text)
        check()
        if len(rows)!=1 or rows[0]['username']!=recipient or rows[0]['draft']!=text:
            raise AXRError('unique_exact_cached_draft_required')
        return cls(account,recipient,digest(text),digest(window),clock(),monotonic(),digest(rows))

    def activate(self, database, account, recipient, text, query, window, search_started, check,
                 *, clock=time.time, monotonic=time.monotonic):
        check();now=clock();elapsed=monotonic()-self.observed_monotonic
        if not 0<=elapsed<=60 or not 0<=now-self.observed_wall<=60:
            raise AXRError('cached_draft_witness_expired')
        if (account,recipient,digest(text),digest(window))!=(self.account,self.recipient,self.text_digest,self.window_digest):
            raise AXRError('cached_draft_scope_changed')
        if database.account!=account:raise AXRError('cached_draft_account_mismatch')
        if not self.observed_wall<=search_started<=now or now-search_started>30:
            raise AXRError('fresh_post_cache_navigation_required')
        if not isinstance(query,str) or not query or len(query.encode())>4000:
            raise AXRError('bounded_search_query_required')
        rows=database.navigation(recipient,'recent',check,query=query,since=int(search_started)-1)
        check()
        if (len(rows)!=1 or rows[0]['username']!=recipient or rows[0]['query']!=query or
                not search_started-1<=rows[0]['last_click_time']<=now+1):
            raise AXRError('unique_fresh_search_identity_required')
        drafts=database.navigation(recipient,'draft',check)
        check()
        if (len(drafts)!=1 or type(drafts[0].get('size')) is not int or not 0<=drafts[0]['size']<=16000 or
                drafts[0]['draft'] not in ('',text)):
            raise AXRError('activated_draft_changed')
        return {**window,'recipient_assurance':'cached_exact_draft_and_fresh_search',
            'recipient_witness':digest([self.snapshot_digest,self.text_digest,self.window_digest,rows,drafts,search_started])}
