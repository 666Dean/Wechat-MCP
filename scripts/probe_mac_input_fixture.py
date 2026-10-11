"""Exercise ONLY the separately opened AXR synthetic fixture; never WeChat.

Synthetic authority is temporary, with fixed non-production identifiers. No
OwnerStore, account discovery, clipboard, real client launch or agent grants.
"""
import argparse
import json
import tempfile
import time
import uuid
from pathlib import Path

from axr.aet import Action, Resource
from axr.guard import Guard
from axr.host import Supervisor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', required=True)
    args = parser.parse_args()
    helper = str(Path(args.helper).resolve(strict=True))
    supervisor = Supervisor(timeout=35)
    scope = {'bundle': 'dev.axr.input-fixture', 'expected_platform': 'fixture',
             'expected_account': 'fixture-account', 'expected_identity': 'fixture-chat',
             'expected_title': 'fixture-title'}
    def invoke(op, **kwargs):
        return supervisor.invoke([helper], {'op': op, **scope, **kwargs})['result']
    try:
        structure = invoke('structure')
        paths = {n['identifier']: n['path'] for n in structure['nodes']
                 if n['identifier'] in {'account', 'identity', 'header', 'input','messages'}}
        if set(paths) != {'account', 'identity', 'header', 'input','messages'}:
            raise RuntimeError('Open only the built AXR synthetic input fixture first')
        scope['expected_pid'] = structure['pid']
        before = invoke('status')
        text = 'AXR native fixture reply ' + uuid.uuid4().hex[:8]
        resource = Resource('fixture', 'fixture-account', 'fixture-chat')
        with tempfile.TemporaryDirectory(prefix='axr-synthetic-input-') as directory:
            guard = Guard(Path(directory) / 'guard.db', b'g' * 32)
            action = Action('fixture-owner', resource, 'messages.send', 'synthetic-input', {'text': text})
            grant = guard._issue_owner(principal=action.principal, resource=resource, operations=[action.operation],
                purpose=action.purpose, expires_at=time.time()+120, max_uses=1, workflow=action.workflow, intent=action.seal)
            try:
                gid, version = guard.consume(action)
                proof = guard.execution_proof(action, gid, version)
                request = {'path': paths['input'], 'account_path': paths['account'],
                           'identity_path': paths['identity'], 'header_path': paths['header'],
                           'messages_path': paths['messages'], 'send_method': 'pid_return',
                           'return_sends_message': True, 'guard_context': proof}
                altered = invoke('send_text', text=text+' altered', **request)
                other_windows=[n['path'] for n in structure['nodes'] if n['role']=='AXWindow' and n['path']!=paths['input'][:-1]]
                cross = (invoke('send_text', text=text, **{**request,'messages_path':other_windows[0]})
                         if other_windows else None)
                result = invoke('send_text', text=text, **request)
                after = invoke('status')
            finally:
                guard.revoke_owner(grant)
                guard.close()
        summary = {'synthetic_only': True, 'altered_text_denied': altered.get('error') == 'authority_or_requested_scope_changed',
                   'verified': result.get('verified') is True, 'error': result.get('error'),
                   'foreground_before': before['foreground'], 'foreground_after': after['foreground'],
                   'all_windows_minimized_before': before.get('all_windows_minimized'),
                   'cross_window_denied': cross.get('error')=='cross_window_scope_denied' if cross else None,
                   'delivery_confirmed': False, 'retry': False}
        print(json.dumps(summary))
        if not summary['altered_text_denied'] or not summary['verified'] or (cross and not summary['cross_window_denied']):
            raise SystemExit(1)
    finally:
        supervisor.cancel()


if __name__ == '__main__':
    main()
