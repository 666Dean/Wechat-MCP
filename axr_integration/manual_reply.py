# SPDX-License-Identifier: MIT
"""Local human draft review. No adapter calls, submission or plaintext files."""
from axr.aet import AXRError, Action


def review_draft(store, job_id):
    policy=store.config();principal=policy['principal']
    row=store.journal.get(job_id,principal)
    if row['state']!='Completed' or row['expires']<=store.journal.clock():
        raise AXRError('completed_unexpired_draft_required')
    action=store.journal.action(row)
    if action.operation!='reply.prepare':raise AXRError('reply_draft_required')
    store.guard.revalidate(action,row['grant_id'],row['policy_version'])
    result=store.journal.result(job_id,principal,store.guard.version)
    context=store.journal.context(result['draft_id'],principal,action.resource,store.guard.version)
    if Action.from_dict(context['draft']).seal!=action.seal:
        raise AXRError('manual_draft_intent_mismatch')
    binding=next((b for b in policy['conversations'] if b['conversation_id']==action.resource.conversation_id),None)
    if binding is None or action.resource.account_id!=policy['account_id']:
        raise AXRError('manual_draft_target_changed')
    return {'job_id':job_id,'conversation_id':action.resource.conversation_id,
            'display_name':binding['display_name'],'text':action.payload['text'],
            'attribution':action.payload['attribution'],'sources':len(action.sources),
            'expires':min(row['expires'],store.journal.clock()+300),
            'submission':'human','sent':False}


def list_drafts(store):
    principal=store.config()['principal']
    rows=store.journal.db.execute('SELECT id FROM jobs WHERE principal=? AND state=? AND expires>? ORDER BY created DESC LIMIT 100',
                                 (principal,'Completed',store.journal.clock())).fetchall()
    drafts=[]
    for row in rows:
        try:value=review_draft(store,row['id'])
        except AXRError:continue
        drafts.append({k:value[k] for k in ('job_id','conversation_id','display_name','expires')})
        if len(drafts)==50:break
    return drafts
