# SPDX-License-Identifier: MIT
"""Encrypted local owner preferences. No incoming-message or MCP issuer endpoint."""
from axr import _axr_native as native
from axr.aet import AXRError

DEFAULT={'thread_id':'','thread_title':'','persona':'','style':'简洁、自然、直接；不编造事实，不替主人承诺。','attribution':True}

def load(store):
    path=store.directory/'assistant-preferences.sealed'
    if not path.exists():return dict(DEFAULT)
    if path.is_symlink() or path.stat().st_size>32768:raise AXRError('assistant_preferences_invalid')
    return {**DEFAULT,**store.vault.open(path.read_bytes(),'assistant-preferences-v1')}

def save(store,value):
    if (type(value) is not dict or set(value)!=set(DEFAULT) or type(value['attribution']) is not bool or
            any(not isinstance(value[k],str) for k in DEFAULT if k!='attribution') or
            len(value['persona'].encode())>12000 or len(value['style'].encode())>4000 or
            len(value['thread_title'])>512 or (value['thread_id'] and not valid_thread(value['thread_id']))):
        raise AXRError('assistant_preferences_invalid')
    if not native.durable_write(str(store.directory/'assistant-preferences.sealed'),store.vault.seal(value,'assistant-preferences-v1')):
        raise AXRError('assistant_preferences_write_failed')
    return value

def valid_thread(value):
    import uuid
    try:return str(uuid.UUID(value))==value
    except (ValueError,TypeError,AttributeError):return False
