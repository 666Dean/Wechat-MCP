# SPDX-License-Identifier: MIT
"""Offline Windows selector metadata. Never discover or operate a live UI."""
import json,re
from pathlib import Path
from axr.aet import AXRError,canonical,digest
from axr.rooted import RootedDirectory
from .wechat_targets import private_recipient

PATHS=frozenset(('path','header_path','account_path','identity_path','send_path','search_path','search_result_path'))
VISUAL=PATHS|{'executable_hash','expected_title','expected_identity','search_result_title'}
MAXIMUM=30000

def decode_json(raw):
    def unique(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError()
            result[key]=value
        return result
    try:
        value=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        if type(value) is not dict:raise ValueError()
        return value
    except (ValueError,TypeError):raise AXRError('windows_navigation_json_invalid') from None

def read_json(path,maximum=MAXIMUM):
    path=Path(path).absolute();directory=RootedDirectory(path.parent)
    try:return decode_json(directory.read(path.name,maximum))
    finally:directory.close()

def sha(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None

def text(value,maximum):
    return (type(value) is str and bool(value.strip()) and len(value.encode())<=maximum
        and all(ord(c)>=32 and ord(c)!=127 for c in value))

def validate(navigation,*,account,helper,endpoint,helper_sha=None,identities=None):
    try:
        fields={'helper','helper_sha256','endpoint','profiles','attribution_prefix'}
        if (not private_recipient(account) or not text(account,512) or
            type(navigation) is not dict or not fields<=set(navigation) or set(navigation)-fields-{'attribution_required'} or
            navigation['helper']!=str(helper) or navigation['endpoint']!=endpoint or not sha(navigation['helper_sha256']) or
            helper_sha is not None and navigation['helper_sha256']!=helper_sha or
            type(navigation.get('attribution_required',True)) is not bool or not text(navigation['attribution_prefix'],1000)):
            raise ValueError()
        profiles=navigation['profiles']
        if type(profiles) is not dict or not 2<=len(profiles)<=4096:raise ValueError()
        pins=set()
        for cid,profile in profiles.items():
            if (not private_recipient(cid) or cid=='axr:application-ui' or not text(cid,512) or
                type(profile) is not dict or set(profile)!={'label','visual_binding'} or
                not text(profile['label'],4000) or identities is not None and cid not in identities):raise ValueError()
            visual=profile['visual_binding']
            if (type(visual) is not dict or set(visual)!=VISUAL or visual['expected_identity']!=cid or
                not sha(visual['executable_hash']) or any(not text(visual[k],4000) for k in ('expected_title','search_result_title')) or
                any(type(visual[k]) is not list or not 1<=len(visual[k])<=16 or
                    any(type(i) is not int or not 0<=i<500 for i in visual[k]) for k in PATHS)):
                raise ValueError()
            # Account and identity controls must not alias any input/action.
            if (visual['account_path']==visual['identity_path'] or
                any(visual[a]==visual[b] for a in ('account_path','identity_path','header_path')
                    for b in ('path','search_path','search_result_path','send_path')) or
                len({tuple(visual[k]) for k in ('path','search_path','search_result_path','send_path')})!=4):raise ValueError()
            pins.add(visual['executable_hash'])
        if len(pins)!=1 or len(canonical(navigation))>MAXIMUM:raise ValueError()
    except (ValueError,KeyError,TypeError,UnicodeError):raise AXRError('windows_navigation_configuration_invalid') from None
    return json.loads(canonical(navigation))

def prepare(document,*,account,helper,helper_sha,endpoint):
    """A caller cannot import its own helper, pipe, resource list or authority."""
    try:
        if (type(document) is not dict or set(document)!={'version','account_id','profiles','attribution_prefix','attribution_required'} or
            type(document['version']) is not int or document['version']!=2 or document['account_id']!=account):raise ValueError()
        navigation={k:document[k] for k in ('profiles','attribution_prefix','attribution_required')}
        navigation.update(helper=str(helper),helper_sha256=helper_sha,endpoint=endpoint)
        return validate(navigation,account=account,helper=helper,helper_sha=helper_sha,endpoint=endpoint)
    except (KeyError,ValueError,TypeError):raise AXRError('windows_navigation_import_invalid') from None

def review(navigation):
    return {'profile_count':len(navigation['profiles']),'configuration_digest':digest(navigation),
        'executable_sha256':next(iter(navigation['profiles'].values()))['visual_binding']['executable_hash'],
        'device_verified':False,'authorization_granted':False}

def build_update(original,current,*,bundled_path,identities):
    """Permit only selectors and the existing limited CLI update to be reviewed."""
    from .wechat import provider_build_update
    old={k:v for k,v in original.items() if k!='reply_navigation'}
    new={k:v for k,v in current.items() if k!='reply_navigation'}
    if 'admission_trust_sha256' not in old and sha(new.get('admission_trust_sha256')):
        new={k:v for k,v in new.items() if k!='admission_trust_sha256'}
    if not provider_build_update(old,new,bundled_path=bundled_path):return False
    navigation=current.get('reply_navigation')
    if navigation is None:return 'reply_navigation' not in original
    try:validate(navigation,account=current['account_id'],helper=current['navigation_helper'],
        endpoint=navigation['endpoint'],identities=identities)
    except (AXRError,KeyError,TypeError):return False
    return True
