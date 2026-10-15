# SPDX-License-Identifier: MIT
"""Strict finite local message plans. This parser grants no authority."""
import json
import os
import stat
from pathlib import Path
from axr.aet import AXRError, identifier


def load_plan(path):
    path=Path(path)
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>65536 or (os.name!='nt' and info.st_mode&0o077):
        raise AXRError('private_regular_bounded_plan_required')
    with path.open('rb') as stream:
        if os.fstat(stream.fileno()).st_ino!=info.st_ino:raise AXRError('plan_file_changed')
        raw=stream.read(65537)
    try:plan=json.loads(raw)
    except (ValueError,UnicodeError) as exc:raise AXRError('invalid_chat_plan') from exc
    if not isinstance(plan,dict) or set(plan)!={'version','messages'} or type(plan['version']) is not int or plan['version']!=1:
        raise AXRError('invalid_chat_plan')
    messages=plan['messages']
    if not isinstance(messages,list) or not 1<=len(messages)<=2:raise AXRError('one_or_two_messages_required')
    targets=set();seen=set()
    for item in messages:
        if not isinstance(item,dict) or set(item)!={'conversation_id','parking_conversation_id','text'}:raise AXRError('invalid_chat_plan_message')
        target=identifier(item['conversation_id']);parking=identifier(item['parking_conversation_id'])
        if target==parking or target in seen or any(x.endswith('@chatroom') or x=='filehelper' or x.startswith('gh_') for x in (target,parking)):
            raise AXRError('distinct_private_target_and_parking_required')
        seen.add(target);targets.update((target,parking))
        text=item['text']
        if not isinstance(text,str) or not text.strip() or len(text.encode())>8000 or '\x00' in text:raise AXRError('bounded_reply_text_required')
    if len(targets)!=2:raise AXRError('exact_two_bound_private_targets_required')
    return plan
