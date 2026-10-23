# SPDX-License-Identifier: MIT
"""Hello first/existing owner enrollment, without implicit hardware trust.

The native host protects installation files. Certificate evidence only travels
over its private setup channel; never return it from MCP or put it in logs.
First creation is a separately reviewed native operation, never an error
fallback for an existing pin. Cross-session transport is a fixed native pipe.
"""
import json
import hashlib
import io
from pathlib import Path
from datetime import datetime
import sys
import time
from axr import _axr_native as native
from axr.aet import AXRError, canonical, digest
from axr.rooted import RootedDirectory
from .windows_owner import enrolled_key,enrolled_public_key,frame

MACHINE_TRUST={'version':2,'source':'local-machine-root'}


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
        if value==MACHINE_TRUST and type(value.get('version')) is int:return 'local-machine-root'
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
    valid=(native.verify_windows_hello_attestation_machine(key,statement,chain) if roots=='local-machine-root' else
        native.verify_windows_hello_attestation(key,statement,chain,roots))
    if not valid:raise ValueError()


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
        if clock()>=challenge['expires']:raise ValueError()
        return key
    except (ValueError,TypeError,KeyError):
        raise AXRError('wechat_owner_hardware_enrollment_invalid') from None


def first_enrollment_review(configuration,challenge):
    # Values are quoted to prevent embedded newlines/control characters from
    # impersonating headings or scope. This text stays on the local owner UI.
    def quote(value):return json.dumps(value,ensure_ascii=False)
    app=configuration['application']
    lines=['微信代理首次登记','请核对本次安装和联系人范围。确认后将请求 Windows Hello 创建所有者密钥。',
        '后续任务仍需单独授权。','',f"账户：{quote(app['account_id'])}",
        f"安装状态目录：{quote(configuration['state'])}",f"本地服务：{quote(configuration['endpoint'])}",
        '人工审批：'+('开启' if app.get('manual_approval_required',True) else '关闭'),
        '自动回复：未启用','',f"联系人范围（{len(app['resources'])} 项）："]
    lines.extend(quote(row['conversation_id']) for row in app['resources'])
    source=configuration.get('credential_import')
    if source:lines.extend(['','凭据解释：'+{'raw':'原始页密钥','password':'32 字节口令，按各分库 salt 派生'}.get(source.get('key_mode'),'按文件声明；纯 hex 视为原始页密钥')])
    lines.extend(['',f"配置指纹：{challenge['configuration_digest']}",
        '确认截止：'+datetime.fromtimestamp(challenge['expires']).astimezone().isoformat(timespec='seconds')])
    if 'build_digest' in challenge:lines.extend(['',f"构建指纹：{challenge['build_digest']}"])
    if challenge['kind']=='wechat-owner-orphan-recovery':
        lines[0]='微信代理中断登记恢复'
        lines[1]='没有可用的配置收据。本次只打开既有 Windows Hello 密钥；请核对程序、配置和即将显示的实际公钥指纹。'
        lines[2]='不会创建或替换密钥，不恢复旧权限；验证硬件证明并签名后才能重新初始化。'
    review='\r\n'.join(lines)
    if len(review.encode('utf-8'))>65536:raise AXRError('owner_enrollment_review_budget')
    return review


def enrollment_key(runtime_root,configuration,challenge):
    # A missing file is the only first-enrollment case. Invalid/unreadable pins
    # or unavailable existing credentials must never fall through to creation.
    if challenge['kind']=='wechat-owner-orphan-recovery':
        try:(Path(runtime_root)/'owner-key.json').lstat()
        except FileNotFoundError:return native.recover_windows_hello_owner(first_enrollment_review(configuration,challenge),challenge['expires'])
        raise AXRError('wechat_owner_orphan_recovery_requires_missing_pin')
    if challenge['kind']!='wechat-owner-enrollment':
        expected=hex_bytes(challenge['expected_public_key'],294)
        if len(expected)!=294:raise AXRError('wechat_owner_enrolled_key_pin_required')
        try:(Path(runtime_root)/'owner-key.json').lstat()
        except FileNotFoundError:
            if challenge['kind']!='wechat-owner-recovery':raise AXRError('wechat_owner_enrolled_key_pin_required') from None
        else:
            if enrolled_public_key(runtime_root)!=expected:raise AXRError('wechat_owner_public_key_pin_changed')
        review=('微信代理初始化恢复' if challenge['kind']=='wechat-owner-recovery' else '微信代理构建更新')+'\r\n'+ \
            '确认本次固定配置与构建。旧任务、授权与发送不会恢复，也不会创建或替换密钥。\r\n'+ \
            json.dumps({'configuration':configuration,'challenge':challenge},ensure_ascii=False,indent=2)
        if len(review.encode('utf-8'))>65536:raise AXRError('owner_enrollment_review_budget')
        if not native.review_windows_owner(review,challenge['expires']):raise AXRError('owner_enrollment_recovery_cancelled')
        try:(Path(runtime_root)/'owner-key.json').lstat()
        except FileNotFoundError:
            if challenge['kind']!='wechat-owner-recovery':raise AXRError('wechat_owner_enrolled_key_pin_required') from None
            return native.WindowsHelloOwnerKey(expected)
        key=enrolled_key(runtime_root)
        if key.public_key!=expected:raise AXRError('wechat_owner_public_key_pin_changed')
        return key
    try:(Path(runtime_root)/'owner-key.json').lstat()
    except FileNotFoundError:
        return native.provision_windows_hello_owner(first_enrollment_review(configuration,challenge),challenge['expires'])
    public=enrolled_public_key(runtime_root)
    review=first_enrollment_review(configuration,challenge).replace('首次登记','登记既有所有者密钥').replace('创建所有者密钥','验证既有所有者密钥')
    review+='\r\n公钥指纹：'+hashlib.sha256(public).hexdigest()
    if not native.review_windows_owner(review,challenge['expires']):raise AXRError('owner_enrollment_recovery_cancelled')
    return enrolled_key(runtime_root)


def respond(runtime_root,source,emit,*,clock=time.time):
    challenge=frame(source);now=clock()
    try:
        initial=challenge.get('kind')=='wechat-owner-enrollment'
        orphan=challenge.get('kind')=='wechat-owner-orphan-recovery'
        reviewed=challenge.get('kind') in ('wechat-owner-recovery','wechat-owner-build-update')
        fields={'version','kind','configuration_digest','nonce','expires'}
        if reviewed:fields|={'expected_public_key','build_digest'}
        if orphan or initial and 'build_digest' in challenge:fields.add('build_digest')
        if (not (initial or orphan or reviewed) or set(challenge)!=fields or
                type(challenge['version']) is not int or challenge['version']!=2 or
                len(hex_bytes(challenge['nonce'],32))!=32 or
                len(hex_bytes(challenge['configuration_digest'],32))!=32 or
                type(challenge['expires']) not in (int,float) or not now<challenge['expires']<=now+180):raise ValueError()
        if reviewed and (len(hex_bytes(challenge['expected_public_key'],294))!=294 or len(hex_bytes(challenge['build_digest'],32))!=32):raise ValueError()
        if 'build_digest' in challenge and len(hex_bytes(challenge['build_digest'],32))!=32:raise ValueError()
        from axr.deployment_configuration import read
        registration=read(runtime_root)
        if (type(registration) is not dict or set(registration)!={'version','application_module','deployment'} or
                type(registration['version']) is not int or registration['version']!=2 or
                registration['application_module']!='axr_applications.wechat'):raise ValueError()
        from .wechat import _configuration
        configuration=_configuration(registration['deployment'])
        if digest(configuration)!=challenge['configuration_digest']:raise ValueError()
        if 'build_digest' in challenge:
            from .wechat import review_windows_build
            if review_windows_build(configuration['application'])['build']!=challenge['build_digest']:raise ValueError()
    except (ValueError,TypeError,KeyError):raise AXRError('owner_enrollment_challenge_invalid') from None
    roots=trust_roots(runtime_root)
    key=enrollment_key(runtime_root,configuration,challenge)
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
    # Cross-session child receives no inherited stdio/environment configuration.
    # Native code loads the fixed protected descriptor and authenticates both
    # sides against actual PID/birth/image/user evidence before giving a nonce.
    client=native.WindowsOwnerSetupClient()
    try:
        challenge=json.loads(client.challenge)
        return respond(runtime_root,io.BytesIO(canonical(challenge)+b'\n'),
            lambda value:client.respond(canonical(value).decode('utf-8')))
    finally:client.close()


def exchange(configuration,challenge,runtime_root):
    owner=configuration.get('owner_user')
    if type(owner) is not str:raise AXRError('wechat_windows_owner_user_required')
    value=json.loads(native.exchange_windows_owner_setup(owner,canonical(challenge).decode('utf-8')))
    if type(value) is not dict or set(value)!={'response','identity'}:raise AXRError('wechat_owner_host_identity_required')
    if type(value['response']) is not dict or value['response'].get('challenge')!=challenge:
        raise AXRError('wechat_owner_hardware_enrollment_invalid')
    validate_enrollment(configuration,{**value['response'],'identity':value['identity']},runtime_root)
    return value['response'],value['identity']


def validate_enrollment(configuration,enrollment,runtime_root):
    """Recheck a protected setup hook result before creating the new ledger."""
    try:
        owner=configuration['owner_user'];actual=enrollment['identity'];expected=Path(runtime_root).parent/'axr-owner.exe'
        if (actual['user']!=owner or actual['platform']!='windows' or actual['app_container'] is not False or
                Path(actual['image'])!=expected or type(actual['pid']) is not int or actual['pid']<=0 or
                type(actual['birth']) is not str or not actual['birth'] or
                len(hex_bytes(actual['image_sha256'],32))!=32):raise ValueError()
        response={key:value for key,value in enrollment.items() if key!='identity'}
        if response['challenge']['configuration_digest']!=digest(configuration):raise ValueError()
        validate_response(response['challenge'],response,trust_roots(runtime_root))
    except (ValueError,TypeError,KeyError):raise AXRError('wechat_owner_host_identity_required') from None


def persist_pin(runtime_root,public_key):
    """Authority calls this only after proof and new-ledger integrity persist.

    Exclusive create never replaces a previous key. Interrupted writes remain
    an explicit recovery case; owner/model processes cannot write the install.
    """
    raw=hex_bytes(public_key,294)
    if len(raw)!=294:raise AXRError('wechat_owner_enrolled_key_pin_required')
    value={'version':2,'provider':'WindowsHello/RSA2048','public_key':public_key}
    from axr.windows_files import create_once
    directory=RootedDirectory(runtime_root)
    try:
        with directory.parent('owner-key.json') as (parent,name):
            try:create_once(parent,name,canonical(value)+b'\n')
            except FileExistsError:
                previous=installed_json(runtime_root,'owner-key.json',32768)
                if previous!=value or type(previous.get('version')) is not int:
                    raise AXRError('wechat_owner_public_key_pin_changed') from None
        saved=installed_json(runtime_root,'owner-key.json',32768)
        if saved!=value or type(saved.get('version')) is not int:raise AXRError('wechat_owner_public_key_pin_write_failed')
    finally:directory.close()
