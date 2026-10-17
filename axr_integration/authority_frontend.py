# SPDX-License-Identifier: MIT
"""MCP facade for the independent authority. No local journal or raw credentials."""
import json
import re
import threading
from pathlib import Path
from axr.aet import AXRError, canonical
from axr.authority_server import AuthorityClient
from axr.rooted import RootedDirectory


def load_connection(path, *, include_capability=False):
    path = Path(path).absolute()
    directory = RootedDirectory(path.parent)
    try:raw = directory.read(path.name, 32768)
    finally:directory.close()
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:raise AXRError('authority_profile_invalid')
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique)
        fields = {'version','endpoint','server'} | ({'capability'} if include_capability else set())
        if (type(value) is not dict or set(value) != fields or
                type(value['version']) is not int or value['version'] != 2):
            raise ValueError()
        endpoint, server = value['endpoint'], value['server']
        prefix = '\\\\.\\pipe\\'
        if (not isinstance(endpoint,str) or not endpoint.startswith(prefix) or
                not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}',endpoint[len(prefix):])):
            raise ValueError()
        fields = {'pid','user','birth','image','image_sha256','signature_valid',
                  'signer_sha256','app_container','hardened_runtime','platform'}
        if (type(server) is not dict or set(server) != fields or server['platform'] != 'windows' or
                type(server['pid']) is not int or server['pid'] <= 0 or
                not isinstance(server['birth'],str) or not server['birth'].isdigit() or
                not isinstance(server['user'],str) or not server['user'].startswith('S-1-') or
                not isinstance(server['image'],str) or not Path(server['image']).is_absolute() or
                not isinstance(server['image_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',server['image_sha256']) or
                any(type(server[key]) is not bool for key in ('signature_valid','app_container','hardened_runtime'))):
            raise ValueError()
        if include_capability and (type(value['capability']) is not dict or len(canonical(value['capability'])) > 24000):
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError):
        raise AXRError('authority_profile_invalid') from None


def load_profile(path):
    return load_connection(path, include_capability=True)


class AuthorityFrontend:
    def __init__(self, profile, *, connect=AuthorityClient.connect):
        self.profile, self.connect = profile, connect
        self.channel, self.failed = None, False
        self.lock = threading.RLock()

    def call(self, method, **parameters):
        with self.lock:
            if self.failed:raise AXRError('authority_connection_restart_required')
            try:
                # Use one authenticated connection per request so the Windows
                # first-instance pipe also admits the separate owner channel
                # between MCP operations. Never repeat a request after failure.
                self.channel = self.connect(self.profile['endpoint'],self.profile['server'])
                return self.channel.request('Application', method=method,
                    parameters=parameters, capability=self.profile['capability'])
            except AXRError as error:
                if str(error).startswith('ipc_') or str(error)=='authority_response_invalid':
                    self.failed = True
                raise
            except Exception:
                self.failed = True
                raise AXRError('authority_request_outcome_unknown_no_retry') from None
            finally:
                if self.channel:
                    try:self.channel.close()
                    except Exception:pass
                    self.channel = None

    def status(self):
        try:return self.call('status')
        except Exception:
            return {'backend':'independent-authority','authority_connected':False,
                'send_available':False,'body_disclosed':False,'unknown_retry':False,
                'manual_approval_required':None}

    def close(self):
        with self.lock:
            if self.channel:self.channel.close();self.channel=None
            self.failed = True


def register(mcp, frontend):
    @mcp.tool(annotations={'readOnlyHint':True})
    def wechat_status()->dict:
        """Independent authority connection and metadata; never message bodies."""
        return frontend.status()

    @mcp.tool()
    def wechat_read_context(conversation_id:str,since:int=0,until:int=2**63-1,
                            cursor:str|None=None,limit:int=6)->dict:
        """Read one authorized bounded page into encrypted local context; returns handles only."""
        return frontend.call('read_context',conversation_id=conversation_id,
                             since=since,until=until,cursor=cursor,limit=limit)

    @mcp.tool()
    def wechat_disclose_context(conversation_id:str,context_id:str)->dict:
        """Disclose a scoped context only with separate owner-issued disclosure permission."""
        return frontend.call('disclose_context',conversation_id=conversation_id,context_id=context_id)

    @mcp.tool()
    def wechat_prepare_reply(conversation_id:str,text:str,context_ids:list[str])->dict:
        """Store a source-bound encrypted manual draft. This tool never sends WeChat messages."""
        return frontend.call('prepare_reply',conversation_id=conversation_id,text=text,context_ids=context_ids)

    @mcp.tool(annotations={'readOnlyHint':True})
    def axr_receipt(execution_id:str)->dict:
        """Read the authenticated task's own execution receipt; Unknown is never retried."""
        return frontend.call('receipt',execution_id=execution_id)

    @mcp.tool()
    def axr_execute(job_id:str)->dict:
        """Execute a separately owner-approved disclosure once; cannot approve or send."""
        return frontend.call('execute',job_id=job_id)
