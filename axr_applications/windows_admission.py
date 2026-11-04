# SPDX-License-Identifier: MIT
"""Pinned reviewer evidence for one Windows installation, never a UI switch.

Signatures authenticate a reviewer's statement, not the underlying experiment.
Software evidence is inspectable but cannot qualify the product. Only a device
review explicitly recording completion of the whole software audit can do so.
No signing keys, hardware operations, UI probes or evidence files are generated.
"""
import hashlib,math,threading,time
from pathlib import Path
from axr import _axr_native as native
from axr.aet import AXRError,canonical,digest
from axr.release import CATEGORIES,ReleaseGate
from .windows_navigation import read_json,decode_json,sha

MAX_AGE=30*24*3600

def trust_keys(value):
    try:
        if (type(value) is not dict or set(value)!={'version','keys'} or type(value['version']) is not int or
            value['version']!=2 or type(value['keys']) is not dict or not 1<=len(value['keys'])<=8):raise ValueError()
        keys={}
        for key_id,hex_key in value['keys'].items():
            if not sha(key_id) or type(hex_key) is not str:raise ValueError()
            key=bytes.fromhex(hex_key)
            if len(key)!=65 or key[0]!=4 or key.hex()!=hex_key or hashlib.sha256(key).hexdigest()!=key_id:raise ValueError()
            keys[key_id]=key
        return keys
    except (KeyError,ValueError,TypeError):raise AXRError('windows_admission_trust_invalid') from None

def installed_trust(root,application):
    from axr.rooted import RootedDirectory
    directory=RootedDirectory(Path(root)/'runtime')
    try:raw=directory.read('admission-trust.json',4096)
    finally:directory.close()
    if hashlib.sha256(raw).hexdigest()!=application.get('admission_trust_sha256'):
        raise AXRError('windows_admission_trust_changed')
    # Duplicate JSON members must be rejected, even with a matching file pin.
    return trust_keys(decode_json(raw))

def subject(config,build,owner_public_key,os_build):
    navigation=config['application'].get('reply_navigation')
    if not navigation:raise AXRError('windows_admission_navigation_required')
    return {'configuration':digest(config),'build':build,'owner_key':digest(owner_public_key),
        'navigation':digest(navigation),'os_build':os_build,'platform':'windows-x64'}

def request(expected):
    """Unsigned review input, with no successful checks or implicit signature."""
    return {'version':2,'product':'wechat-codex-mcp/windows','subject':decode_json(canonical(expected)),
        'required_categories':list(CATEGORIES),'device_review_required':True,'authorization_granted':False}

def verify(envelope,keys,expected,*,clock=time.time):
    try:
        if type(envelope) is not dict or set(envelope)!={'body','key_id','signature'}:raise ValueError()
        body=envelope['body'];signature=envelope['signature']
        if type(signature) is not str or len(signature)>160:raise ValueError()
        signature_bytes=bytes.fromhex(signature)
        if signature_bytes.hex()!=signature or not native.verify_root_signature(keys[envelope['key_id']],canonical(body),signature_bytes):raise ValueError()
        if (type(body) is not dict or set(body)!={'version','product','sequence','subject','created','expires','stage','code_audit','evidence'} or
            type(body['version']) is not int or body['version']!=2 or body['product']!='wechat-codex-mcp/windows' or
            type(body['sequence']) is not int or not 1<=body['sequence']<=2**53-1 or
            canonical(body['subject'])!=canonical(expected) or body['stage'] not in ('software','device')):raise ValueError()
        now=clock()
        if (any(type(t) not in (int,float) or not math.isfinite(t) for t in (body['created'],body['expires'],now)) or
            not body['created']<=now<body['expires'] or not 0<body['expires']-body['created']<=MAX_AGE):raise ValueError()
        audit=body['code_audit'];evidence=body['evidence']
        if (type(audit) is not dict or set(audit)!={'complete','record_sha256'} or type(audit['complete']) is not bool or not sha(audit['record_sha256']) or
            type(evidence) is not dict or set(evidence)!=set(CATEGORIES)):raise ValueError()
        checks={}
        for category,row in evidence.items():
            if (type(row) is not dict or set(row)!={'result','kind','record_sha256'} or row['result'] not in ('pass','fail','unknown') or
                row['kind'] not in ('software','device') or not sha(row['record_sha256']) or
                body['stage']=='software' and row['kind']!='software'):raise ValueError()
            checks[category]=(row['result']=='pass' and row['kind']=='device' and body['stage']=='device' and audit['complete'])
        return {'material_valid':True,'qualified':all(checks.values()),'stage':body['stage'],
            'code_stage_complete':audit['complete'],'checks':checks,'expires':body['expires'],'sequence':body['sequence'],'evidence_digest':digest(body)}
    except (KeyError,ValueError,TypeError,OverflowError):raise AXRError('windows_admission_material_invalid') from None

def installed_context(value):
    """Actual protected build and MAC enrollment, not downloaded declarations."""
    from . import wechat
    from .windows_enrollment import enrolled_public_key
    from axr.deployment import OwnerDeployment
    root=Path(native.windows_installation_root())
    if native.security_release is not True:raise AXRError('windows_admission_formal_host_required')
    from . import _wechat_credentials
    if hasattr(_wechat_credentials,'fixture_consumer') or not hasattr(_wechat_credentials,'import_owner_credentials'):
        raise AXRError('windows_admission_formal_consumer_required')
    native.verify_windows_installation(str(root))
    actual=wechat.process_identity(__import__('os').getpid())
    if (actual.get('platform')!='windows' or actual.get('user')!='S-1-5-18' or
        actual.get('app_container') is not False or actual.get('image')!=str(root/'axr-authority.exe')):
        raise AXRError('windows_admission_formal_host_required')
    from axr.deployment_configuration import read
    registration=read(root/'runtime')
    if registration.get('application_module')!='axr_applications.wechat':raise AXRError('windows_admission_configuration_changed')
    config=wechat._configuration(registration['deployment'])
    # Bootstrap contains only the installation anchor, not application settings.
    if config['state']!=value.get('state') or config['endpoint']!=value.get('endpoint'):
        raise AXRError('windows_admission_configuration_changed')
    with __import__('contextlib').closing(wechat.OwnerStore(config['state'],authority_service=True)) as store:
        approved=store.config();deployment=OwnerDeployment(store.secrets,store.vault)
        build=wechat.review_windows_build(approved['application'])
        if deployment._load()!=build or not deployment.verify_process(actual,'server'):
            raise AXRError('windows_admission_build_changed')
        key=enrolled_public_key(root/'runtime').hex()
        if key!=approved['owner_public_key'] or key!=value.get('owner_public_key') or approved['owner_user']!=config.get('owner_user'):
            raise AXRError('windows_admission_owner_changed')
        # Catalog is refreshed independently; every other approved setting must
        # equal the candidate reviewed by the owner. Pending imports cannot run.
        strip=lambda app:{k:v for k,v in app.items() if k not in ('resources','conversations','manual_approval_required')}
        if strip(approved['application'])!=strip(config['application']):raise AXRError('windows_admission_configuration_changed')
        provider=config['application']['codex_provider']
        from axr.rooted import RootedDirectory
        assets=RootedDirectory(root/'runtime')
        try:
            if (provider['binary']!=str(root/'runtime/provider/codex.exe') or provider['tls_bundle']!=str(root/'runtime/provider/ca-bundle.pem') or
                hashlib.sha256(assets.read('provider/codex.exe',512*1024**2)).hexdigest()!=provider['sha256'] or
                hashlib.sha256(assets.read('provider/ca-bundle.pem',2*1024**2)).hexdigest()!=provider['tls_sha256']):
                raise AXRError('windows_admission_provider_changed')
        finally:assets.close()
        navigation=config['application']['reply_navigation']
        from .windows_navigation import validate
        validate(navigation,account=config['application']['account_id'],helper=root/'wechat-uia.exe',endpoint=config['endpoint'],
            helper_sha=hashlib.sha256((root/'wechat-uia.exe').read_bytes()).hexdigest(),
            identities={r['conversation_id'] for r in approved['application']['resources']})
    import sys
    os_version=sys.getwindowsversion()
    expected=subject(config,build['build'],key,[os_version.major,os_version.minor,os_version.build])
    keys=installed_trust(root,config['application'])
    return keys,expected

def gate(value):
    class WindowsGate(ReleaseGate):
        # No mutable cross-request cache; concurrent snapshots are independent.
        def __init__(self):pass
        def runtime(self):return RuntimeAdmission(value)
        def status(self):
            try:
                keys,expected=installed_context(value)
                envelope=read_json(Path(native.windows_data_root())/'windows-admission.json',16000)
                checks=verify(envelope,keys,expected)['checks']
            except Exception:checks={category:False for category in CATEGORIES}
            return {'qualified':all(checks.values()),'checks':checks,'passed':sum(checks.values()),'total':len(CATEGORIES)}
    return WindowsGate()


class RuntimeAdmission:
    """One protected startup, with no evidence replacement or clock extension.

    Installation/build verification is done before consumers are constructed.
    Runtime checks reread bounded configuration/trust/material files; execution
    consumers retain their own actual image/hash and OS identity checks.
    A failed session stays failed even if a file or clock is restored.
    """
    def __init__(self,value,*,clock=time.time,monotonic=time.monotonic):
        self.lock=threading.RLock();self.failed=False
        self.clock,self.monotonic=clock,monotonic
        self.keys,self.expected=installed_context(value)
        self.configuration=Path(native.windows_deployment_configuration())
        from axr.rooted import RootedDirectory
        with __import__('contextlib').closing(RootedDirectory(self.configuration.parent)) as directory:
            self.configuration_digest=hashlib.sha256(directory.read(self.configuration.name,32768)).hexdigest()
        self.root=Path(native.windows_installation_root())
        with __import__('contextlib').closing(RootedDirectory(self.root/'runtime')) as directory:
            self.trust_digest=hashlib.sha256(directory.read('admission-trust.json',4096)).hexdigest()
        self.material=Path(native.windows_data_root())/'windows-admission.json'
        self.wall,self.tick=clock(),monotonic()
        if any(type(t) not in (int,float) or not math.isfinite(t) for t in (self.wall,self.tick)):
            raise AXRError('windows_admission_session_invalid_restart_required')
        envelope=read_json(self.material,16000)
        result=verify(envelope,self.keys,self.expected,clock=lambda:self.wall)
        if not result['qualified']:raise AXRError('security_release_not_qualified')
        self.material_digest=digest(envelope)
        self.deadline=self.tick+result['expires']-self.wall
        # A concurrent import/update between installed_context and the file
        # snapshots must not establish a mixed session.
        keys,expected=installed_context(value)
        if keys!=self.keys or expected!=self.expected:
            raise AXRError('windows_admission_session_invalid_restart_required')
        self.require()

    def require(self):
        with self.lock:
            try:
                if self.failed:raise ValueError()
                wall,tick=self.clock(),self.monotonic()
                if (any(type(t) not in (int,float) or not math.isfinite(t) for t in (wall,tick)) or
                    wall<self.wall or tick<self.tick or tick>=self.deadline):raise ValueError()
                from axr.rooted import RootedDirectory
                with __import__('contextlib').closing(RootedDirectory(self.configuration.parent)) as directory:
                    if hashlib.sha256(directory.read(self.configuration.name,32768)).hexdigest()!=self.configuration_digest:raise ValueError()
                # Verify the pinned reviewer set again, without rehashing the
                # complete installation on every database/UI cancellation poll.
                with __import__('contextlib').closing(RootedDirectory(self.root/'runtime')) as directory:
                    raw=directory.read('admission-trust.json',4096)
                    if hashlib.sha256(raw).hexdigest()!=self.trust_digest or trust_keys(decode_json(raw))!=self.keys:raise ValueError()
                envelope=read_json(self.material,16000)
                if digest(envelope)!=self.material_digest or not verify(envelope,self.keys,self.expected,clock=lambda:wall)['qualified']:
                    raise ValueError()
                self.wall,self.tick=wall,tick
            except Exception:
                self.failed=True
                raise AXRError('windows_admission_session_invalid_restart_required') from None


from .wechat_service import WeChatKernel


class WindowsAdmissionKernel(WeChatKernel):
    """Gate both MCP APIs, task access and authenticated native commit phases.

    Reducing authority and recording an uncertain outcome remain available.
    Setup/refresh can construct a kernel, but cannot execute without a runtime
    admission session installed by create_authority.
    """
    def require_admission(self):
        try:
            if getattr(self,'admission_revoked',False):raise AXRError('windows_admission_runtime_revoked')
            session=getattr(self,'windows_admission',None)
            if session is None:raise AXRError('windows_admission_runtime_required')
            session.require()
        except Exception:
            with self.lock:
                if not getattr(self,'admission_revoked',False):
                    self.challenges.clear()
                    self.security.revoke('kernel')
                    self.admission_revoked=True
            raise AXRError('windows_admission_session_invalid_restart_required') from None

    def dispatch(self,peer,packet):
        operation=packet.get('operation') if type(packet) is dict else None
        payload=packet.get('payload',{}) if type(packet) is dict else None
        phase=payload.get('phase') if type(payload) is dict else None
        reducing=(operation=='Revoke' or operation in ('Access','Commit') and phase=='receipt' or
            operation=='WeChatOwner' and type(payload) is dict and payload.get('method')=='stop')
        if not reducing:self.require_admission()
        return super().dispatch(peer,packet)

    def access(self,*args,**kwargs):
        self.require_admission()
        return super().access(*args,**kwargs)

    def _task(self,*args,**kwargs):
        # The asynchronous reply controller calls _task from its existing
        # cancellation poll, including while waiting for the native helper.
        self.require_admission()
        return super()._task(*args,**kwargs)

    def preflight_commit(self,*args,**kwargs):
        self.require_admission()
        return super().preflight_commit(*args,**kwargs)

    def observe(self,peer,proof,*,verified,evidence_digest):
        if type(verified) is not bool:raise AXRError('native_receipt_invalid')
        try:self.require_admission()
        except AXRError:verified=False
        return super().observe(peer,proof,verified=verified,evidence_digest=evidence_digest)

def review_context(registration):
    """Public, offline import context; the service separately verifies its MAC pin."""
    from . import wechat
    from .windows_enrollment import enrolled_public_key
    root=Path(native.windows_installation_root());native.verify_windows_installation(str(root))
    config=wechat._configuration(registration['deployment'],runtime_root=root/'runtime')
    build=wechat.OwnerDeployment.review(root,wechat._build_assets(config['application'],installation_root=root))
    import sys
    os_version=sys.getwindowsversion();key=enrolled_public_key(root/'runtime').hex()
    return (installed_trust(root,config['application']),
        subject(config,build['build'],key,[os_version.major,os_version.minor,os_version.build]))
