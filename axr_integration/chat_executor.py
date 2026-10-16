# SPDX-License-Identifier: MIT
"""Owner-authenticated finite original-app send plan; never an MCP issuer.

Experimental foreground workflow. Uses a main-window search, one non-replacing draft insertion,
exact local cached-draft transition and one submission. Unknown never retries.
"""
import json,time,uuid,os,subprocess
from pathlib import Path
from contextlib import ExitStack
from dataclasses import replace
from axr.aet import Action,Resource,Provenance,AXRError,digest
from axr.runtime import Runtime
from axr.journal import Journal
from axr.host import Supervisor
from adapters.wcdb import open_database,DatabaseAdapter
from adapters.wcdb_keys import inventory
from adapters.wcdb_owner import verified_cached
from adapters.macos.chat_state import CachedDraftWitness
def claim_attempt(path):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump({'attempted':True,'retry':False},stream);stream.flush();os.fsync(stream.fileno())
    directory=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(directory)
    finally:os.close(directory)


def execute_plan(store,state,helper,plan,*,principal=None,action_purpose='finite-owner-chat-plan',
                 sources=(),ttl=1200,session_check=lambda:None,journal=None,on_send_job=lambda jid:None,revoke_on_exit=True,binding_catalog=None,attribution=True,attempt_id=None):
 """Trusted owner-controller primitive. Not an issuer endpoint or MCP tool.

 Each native phase has its own exact AET and account lease; the final input
 receipt remains Unknown even when an independent WCDB observation succeeds.
 """
 STATE=Path(state).resolve(strict=True);HELPER=Path(helper).resolve(strict=True)
 helper_digest=digest(HELPER.read_bytes().hex())
 ids=list(dict.fromkeys(x for m in plan['messages'] for x in (m['conversation_id'],m['parking_conversation_id'])))
 role_for={identity:str(i) for i,identity in enumerate(ids)}
 TEXTS={role_for[m['conversation_id']]:m['text'] for m in plan['messages']}
 for identity in ids:TEXTS.setdefault(role_for[identity],'AXR-unused-parking-scope')
 with ExitStack() as cleanup:
  config=store.config();seal=digest(config);roots={Path(s['path']).resolve().parent.parent for s in config['database']['shards']}
  if len(roots)!=1:raise AXRError('single_account_required')
  prefix=config.get('attribution_prefix','【自动回复 · AI 助理】')
  if attribution and (not isinstance(prefix,str) or not prefix.strip() or any(not m['text'].startswith(prefix) for m in plan['messages'])):raise AXRError('explicit_owner_ai_attribution_required')
  root=roots.pop()
  if root.name!='db_storage' or any(Path(s['path']).resolve().parent!=root/'message' for s in config['database']['shards']):raise AXRError('account_layout_unqualified')
  rows=inventory(root);keys=verified_cached(store,root,rows)
  targets={role_for[c['conversation_id']]:c for c in (binding_catalog.values() if binding_catalog is not None else config['conversations']) if c['conversation_id'] in role_for}
  if set(targets)!=set(TEXTS):raise AXRError('exact_two_targets_required')
  dbs={};end=time.monotonic()+ttl;wall=time.time()+ttl;actor=principal or 'owner:chat-plan:'+uuid.uuid4().hex;purpose=action_purpose;appres=Resource('wechat',config['account_id'],'axr:application-ui');grants=[];last_nav={};stages={};witnesses={};probe_count=0;nav_counts={r:0 for r in targets};read_counts={r:0 for r in targets};send_attempts=set()
  for rel in ('general/general.db','session/session.db'):
   item=keys[rel];dbs[Path(rel).stem]=open_database(rows[rel]['path'],store.secrets.get(item['key_reference']).hex(),item['cipher_profile'],library=config['database'].get('sqlcipher_library'),engine=config['database'].get('engine','sqlcipher'))
   cleanup.callback(dbs[Path(rel).stem].close)
  directory=STATE/'chat-plans'/uuid.uuid4().hex;directory.mkdir(mode=0o700,parents=True)
  own_journal=journal is None
  journal=journal or Journal(directory/'journal.db',store.vault);supervisor=Supervisor(timeout=15)
  if own_journal:cleanup.callback(journal.close)
  cleanup.callback(supervisor.cancel)
  messages=DatabaseAdapter({**config['database'],'account_id':config['account_id'],'conversations':list(targets.values())},store.secrets)
  cleanup.callback(messages.close)
  def check_session():
   session_check()
   if time.monotonic()>end or time.time()>wall or digest(store.config())!=seal:raise AXRError('session_expired_or_policy_changed')
  def resource(role):return Resource('wechat',config['account_id'],targets[role]['conversation_id'])
  def binding():
   check_session()
   if digest(HELPER.read_bytes().hex())!=helper_digest:raise AXRError('native_helper_changed')
   reply=supervisor.invoke([str(HELPER)],{'mode':'binding'})['result']
   if 'error' in reply:raise AXRError(reply['error'])
   value=reply['binding']
   value.pop('assurance',None)
   proc=subprocess.run(['/usr/sbin/lsof','-p',str(value['pid']),'-Fn'],capture_output=True,text=True,timeout=5)
   opened={r[1:] for r in proc.stdout.splitlines() if r.startswith('n')}
   account_roots={Path(p).parent.parent.resolve() for p in opened if Path(p).name in ('contact.db','session.db') and Path(p).parent.name in ('contact','session') and Path(p).parent.parent.name=='db_storage'}
   if account_roots!={root} or not {str(root/'contact/contact.db'),str(root/'session/session.db')}<=opened:raise AXRError('runtime_account_witness_changed')
   return value
  def raw_draft(role):
   result=dbs['session'].query('SELECT CASE WHEN length(CAST(draft AS BLOB))<=65536 THEN draft ELSE NULL END AS draft,length(CAST(draft AS BLOB)) AS size FROM SessionTable WHERE username=? LIMIT 2',(targets[role]['conversation_id'],))
   if len(result)!=1 or result[0]['size'] is None or result[0]['size']>65536:raise AXRError('bounded_unique_session_draft_required')
   return result[0]['draft']
  def draft_info(role):
   value=raw_draft(role);raw=value.encode() if isinstance(value,str) else value or b''
   return {'role':role,'size':len(raw),'digest':digest(raw.hex()),'exact_test_draft':value==TEXTS[role]}
  def fresh_recent(role,start):
   label=targets[role]['display_name'];found=dbs['general'].query('SELECT username,query,last_click_time FROM SearchRecent WHERE query=? AND last_click_time>=? LIMIT 129',(label,int(start)-1))
   if len(found)>128:raise AXRError('search_record_budget')
   matches=[r for r in found if r['username']==targets[role]['conversation_id'] and r['query']==label and start-1<=r['last_click_time']<=time.time()+1]
   return len(found)==1 and len(matches)==1
  def inspect(role):
   nonlocal probe_count
   probe_count+=1
   if probe_count>40:raise AXRError('probe_budget')
   return draft_info(role)
  def local_handler(action,check,epoch):
   check();check_session();role=action.payload['role'];out=inspect(role);mode=action.payload.get('probe','snapshot')
   if mode=='observe':
    witnesses[role]=CachedDraftWitness.observe(dbs['session'],config['account_id'],targets[role]['conversation_id'],TEXTS[role],binding(),check)
    out={'role':role,'exact_cached_draft':True,'unique_stable_target':True}
   elif mode=='activate':
    if role not in witnesses:raise AXRError('cached_witness_required')
    out=witnesses[role].activate(dbs['general'],dbs['session'],config['account_id'],targets[role]['conversation_id'],TEXTS[role],targets[role]['display_name'],binding(),last_nav['start'],check)
   check()
   return {'epoch':epoch,'verified':True,'evidence_digest':digest(out),'output':out}
  def native_handler(action,check,epoch):
   check();check_session();role=action.payload['role'];mode=action.payload['mode'];current=binding()
   sealed=action.payload['visual_binding'];basic={k:v for k,v in sealed.items() if k not in ('recipient_assurance','recipient_witness')}
   if current!=basic:raise AXRError('main_window_binding_changed')
   req={'mode':mode,'operation':action.operation,'expected_text':action.payload['text'],'account':action.resource.account_id,'identity':action.resource.conversation_id,'visual_binding':sealed,'guard_context':check.commit_proof()}
   result=supervisor.invoke([str(HELPER)],req)['result'];check()
   native_results[action.execution_id]=result
   verified=(result.get('navigation_invoked') is True and result.get('query_echo_match') is True and result.get('main_window_verified') is True) if mode=='navigate' else result.get('draft_match') is True and result.get('send_invoked') is False
   if mode=='send':verified=False
   return {'epoch':epoch,'verified':verified,'evidence_digest':digest(result),'output':result}
  def read_handler(action,check,epoch):
   role=action.payload['role'];read_counts[role]+=1
   if read_counts[role]>14:raise AXRError('exact_readback_budget')
   check();check_session();payload={k:v for k,v in action.payload.items() if k!='role'}
   output=messages.search(action.resource.conversation_id,**payload);check()
   return {'epoch':epoch,'verified':True,'evidence_digest':digest(output),'output':output}
  runtime=Runtime(store.guard,journal,Path.home()/'.stellaria-axr/leases',{'status.read':local_handler,'application.navigate':native_handler,'application.draft':native_handler,'messages.read':native_handler,'messages.send':native_handler,'messages.search':read_handler});native_results={}
  def issue(action,uses=1,classes=('workspace-normal',)):
   if action.destination!='local':
    for source in action.sources:
     disclosure=replace(action,resource=source.resource,operation='disclosure.send',payload={'output_seal':action.seal},sources=(source,))
     check_session();grants.append(store.guard._issue_owner(principal=actor,resource=source.resource,operations=['disclosure.send'],purpose=purpose,expires_at=min(wall,time.time()+180),max_uses=1,classes=[source.data_class],destinations=[action.destination],intent=disclosure.seal))
   check_session();grants.append(store.guard._issue_owner(principal=actor,resource=action.resource,operations=[action.operation],purpose=purpose,expires_at=min(wall,time.time()+180),max_uses=uses,classes=list(classes),destinations=[action.destination],intent=action.seal))
  def perform(action,issue_now=True):
   if issue_now:issue(action,classes=('personal','workspace-normal'))
   proposal=runtime.propose(action)
   if action.operation=='messages.send':on_send_job(proposal['id'])
   receipt=runtime.execute(proposal['id'],actor)
   out=journal.result(proposal['id'],actor,store.guard.version) if receipt['state']=='Completed' else native_results.get(action.execution_id,{})
   return receipt,out
  def snapshot(role,probe="snapshot"):
   a=Action(actor,appres,'status.read',purpose,{'role':role,'probe':probe},sources=(Provenance(appres,'local-navigation','personal'),))
   # Source read permission is separate from permission for the metadata operation.
   receipt,out=perform(a)
   if receipt['state']!='Completed':raise AXRError('metadata_probe_failed_safe')
   return out
  def navigate(role):
   if nav_counts[role]>=8:raise AXRError('navigation_budget')
   nav_counts[role]+=1;start=time.time();b=binding();query=targets[role]['display_name']
   a=Action(actor,appres,'application.navigate',purpose,{'role':role,'mode':'navigate','text':query,'visual_binding':b,'navigation_binding':{'menu_path':['编辑','搜索'],'main_window_id':b['window_id'],'query':query}})
   receipt,out=perform(a);matched=False
   if receipt['state']=='Completed':matched=fresh_recent(role,start)
   last_nav.clear()
   if matched:last_nav.update(role=role,start=start,binding=b)
   return {'role':role,'input_receipt':receipt['state'],'stable_search_match':matched,'native':out}
  def stage(role):
   if role in stages:raise AXRError('stage_already_attempted_no_repeat')
   if last_nav.get('role')!=role or time.time()-last_nav['start']>60 or not fresh_recent(role,last_nav['start']):raise AXRError('fresh_target_navigation_required')
   snapshot(role)
   b=binding();a=Action(actor,resource(role),'application.draft',purpose,{'role':role,'mode':'stage_draft','text':TEXTS[role],'visual_binding':b})
   stages[role]={'attempted':True,'window':b,'timestamp':time.time(),'exact':False};receipt,out=perform(a)
   stages[role]['exact']=receipt['state']=='Completed' and out.get('draft_match') is True
   return {'role':role,'receipt':receipt['state'],'native':out,'no_send':True}
  def witness(role):
   if not stages.get(role,{}).get('exact'):raise AXRError('exact_staged_draft_required')
   return snapshot(role,'observe')
  def readback(role,since,after=None):
   a=Action(actor,resource(role),'messages.search',purpose,{'role':role,'query':TEXTS[role][:256],'sender':config['account_id'],'since':since,'until':since+600,'after':after,'limit':6},sources=(Provenance(resource(role),'exact-plan-readback','personal'),))
   receipt,out=perform(a)
   if receipt['state']!='Completed':raise AXRError('readback_failed_safe')
   return out
  def send(role):
   if role in send_attempts:raise AXRError('send_already_attempted_never_retry')
   if last_nav.get('role')!=role or time.time()-last_nav['start']>30 or not fresh_recent(role,last_nav['start']):raise AXRError('fresh_target_navigation_required')
   b=snapshot(role,'activate')
   since=int(stages[role]['timestamp'])-30;base=readback(role,since)
   if base['has_more'] or (base['messages'] and attempt_id is None):raise AXRError('baseline_not_empty_no_send')
   prior_ids={m.get('server_id') for m in base['messages']}
   a=Action(actor,resource(role),'messages.send',purpose,{'role':role,'mode':'send','text':TEXTS[role],'visual_binding':b},sources=tuple(sources) or (Provenance(resource(role),'owner-reviewed-local-plan','personal'),),destination='wechat:'+resource(role).key)
   marker=STATE/'chat-plans'/('attempt-'+digest([resource(role).key,TEXTS[role],attempt_id] if attempt_id is not None else [resource(role).key,TEXTS[role]])+'.json')
   claim_attempt(marker)
   send_attempts.add(role);receipt,out=perform(a);observed=[]
   if receipt['state']=='Unknown':
    for _ in range(12):
     page=readback(role,since,base['cursor']);observed=[m for m in page['messages'] if m['text']==TEXTS[role] and m['sender']==config['account_id'] and m['outgoing'] is True and type(m.get('server_id')) is int and m['server_id']>0 and m['server_id'] not in prior_ids and not m.get('text_truncated') and not m.get('truncated')]
     if observed:break
     time.sleep(.5)
   result={'send_job':receipt,'role':role,'input_receipt':receipt['state'],'native':out,'exact_database_records':len(observed),'delivery_confirmed':False,'retry':False,'audit_valid':journal.verify_audit()}
   report=directory/('result-'+role+'.json');report.write_text(json.dumps(result));report.chmod(0o600)
   return result
  try:
   check_session();grants.append(store.guard._issue_owner(principal=actor,resource=appres,operations=['messages.read'],purpose=purpose,expires_at=wall,max_uses=40,classes=list({'personal',*(p.data_class for p in sources)})))
   for role in targets:check_session();grants.append(store.guard._issue_owner(principal=actor,resource=resource(role),operations=['messages.read'],purpose=purpose,expires_at=wall,max_uses=14,classes=list({'personal',*(p.data_class for p in sources)})))
   results=[]
   def select(role):
    out=navigate(role)
    if (out.get('stable_search_match') is not True and out.get('native',{}).get('error')=='search_dialog_unconfirmed' and out['native'].get('navigation_invoked') is False and out['native'].get('send_invoked') is False):
     out=navigate(role)
    if out.get('stable_search_match') is not True:raise AXRError('target_navigation_unconfirmed_no_send')
   for item in plan['messages']:
    role=role_for[item['conversation_id']];parking=role_for[item['parking_conversation_id']]
    marker=STATE/'chat-plans'/('attempt-'+digest([resource(role).key,TEXTS[role],attempt_id] if attempt_id is not None else [resource(role).key,TEXTS[role]])+'.json')
    if marker.exists() or marker.is_symlink():raise AXRError('previous_attempt_never_retry')
    select(role);staged=stage(role)
    if staged['native'].get('draft_match') is not True:raise AXRError('input_not_exact_unsent_draft_preserved')
    select(parking);witness(role);select(role)
    result=send(role);results.append(result)

    if result['exact_database_records']!=1:break
   return results
  finally:
   if revoke_on_exit:
    for gid in grants:store.guard.revoke_owner(gid)
