# SPDX-License-Identifier: MIT
"""Existing Hello owner enrollment evidence, without implicit hardware trust.

The native host protects installation files. Certificate evidence only travels
over its private setup channel; never return it from MCP or put it in logs.
Initial key creation and cross-session setup transport are separate code paths.
"""
import json
import sys
import time
from axr import _axr_native as native
from axr.aet import AXRError, canonical, digest
from axr.rooted import RootedDirectory
from .windows_owner import enrolled_key, frame


def installed_json(runtime_root,name,maximum):
    directory=RootedDirectory(runtime_root)
    try:raw=directory.read(name,maximum)
    finally:directory.close()
    def unique(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError()
            value[key]=item
        return value
    try:return json.loads(raw,object_pairs_hook=unique)
    except (ValueError,TypeError):raise AXRError('wechat_owner_installation_json_invalid') from None


def hex_bytes(value,maximum):
    if type(value) is not str or not value or len(value)>maximum*2:raise ValueError()
    raw=bytes.fromhex(value)
    if raw.hex()!=value:raise ValueError()
    return raw


def trust_roots(runtime_root):
    try:
        value=installed_json(runtime_root,'hello-trust.json',140000)
        if (type(value) is not dict or set(value)!={'version','roots'} or
                type(value['version']) is not int or value['version']!=2 or
                type(value['roots']) is not list or not 1<=len(value['roots'])<=8):raise ValueError()
        roots=[hex_bytes(item,8192) for item in value['roots']]
        if len(set(roots))!=len(roots):raise ValueError()
        return roots
    except (OSError,ValueError,TypeError,AXRError):
        raise AXRError('wechat_owner_hardware_trust_roots_required') from None


def validate_attestation(key,evidence,roots):
    if type(evidence) is not dict or set(evidence)!={'statement','certificate_chain'}:raise ValueError()
    statement=hex_bytes(evidence['statement'],65536);chain=hex_bytes(evidence['certificate_chain'],65536)
    if not native.verify_windows_hello_attestation(key,statement,chain,roots):raise ValueError()


def validate_response(challenge,response,roots,*,clock=time.time):
    try:
        if (type(challenge) is not dict or type(challenge.get('expires')) not in (int,float) or
                not clock()<challenge['expires']<=clock()+180 or
                type(response) is not dict or set(response)!={'version','provider','challenge','public_key','signature','attestation'} or
                type(response['version']) is not int or response['version']!=2 or
                response['provider']!='WindowsHello/RSA2048' or response['challenge']!=challenge):raise ValueError()
        key=hex_bytes(response['public_key'],294);signature=hex_bytes(response['signature'],256)
        if (len(key)!=294 or len(signature)!=256 or
                not native.verify_owner_signature(key,canonical(challenge),signature)):raise ValueError()
        validate_attestation(key,response['attestation'],roots)
        return key
    except (ValueError,TypeError,KeyError):
        raise AXRError('wechat_owner_hardware_enrollment_invalid') from None


def respond(runtime_root,source,emit,*,clock=time.time):
    challenge=frame(source);now=clock()
    try:
        if (set(challenge)!={'version','kind','configuration_digest','nonce','expires'} or
                type(challenge['version']) is not int or challenge['version']!=2 or
                challenge['kind']!='wechat-owner-enrollment' or
                len(hex_bytes(challenge['nonce'],32))!=32 or
                len(hex_bytes(challenge['configuration_digest'],32))!=32 or
                type(challenge['expires']) not in (int,float) or not now<challenge['expires']<=now+180):raise ValueError()
        registration=installed_json(runtime_root,'deployment.json',32768)
        if (type(registration) is not dict or set(registration)!={'version','application_module','deployment'} or
                type(registration['version']) is not int or registration['version']!=2 or
                registration['application_module']!='axr_applications.wechat'):raise ValueError()
        from .wechat import _configuration
        if digest(_configuration(registration['deployment']))!=challenge['configuration_digest']:raise ValueError()
    except (ValueError,TypeError,KeyError):raise AXRError('owner_enrollment_challenge_invalid') from None
    roots=trust_roots(runtime_root)
    key=enrolled_key(runtime_root) # Existing pin only; no creation or fallback.
    evidence=json.loads(key.attestation())
    try:validate_attestation(key.public_key,evidence,roots)
    except (ValueError,TypeError,KeyError):raise AXRError('wechat_owner_hardware_enrollment_invalid') from None
    if clock()>=challenge['expires']:raise AXRError('owner_enrollment_challenge_expired')
    response={'version':2,'provider':'WindowsHello/RSA2048','public_key':key.public_key.hex(),
        'signature':key.sign(canonical(challenge)).hex(),'challenge':challenge,'attestation':evidence}
    if clock()>=challenge['expires']:raise AXRError('owner_enrollment_challenge_expired')
    validate_response(challenge,response,roots,clock=clock)
    emit(response)
    return response


def main(runtime_root):
    if sys.platform!='win32' or native.security_release is not True:raise AXRError('formal_windows_owner_host_required')
    return respond(runtime_root,sys.stdin.buffer,
        lambda value:print(json.dumps(value,separators=(',',':')),flush=True))
