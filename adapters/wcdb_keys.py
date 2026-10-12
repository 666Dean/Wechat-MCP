# SPDX-License-Identifier: MIT
"""Owner-only WCDB key validation and exact contact identity qualification.

No MCP key endpoint, memory scan, bulk contact export or plaintext key file.
SQLCipher4 first-page validation adapted from acmerfight's MIT local toolkit;
see THIRD_PARTY_NOTICES.md. Database reads use the native read-only pager.
"""
import hashlib
import hmac
import os
from pathlib import Path
from axr.aet import AXRError, identifier, digest
from .wcdb import CipherConnection
from database_key_probe import verified_page_key


def verified_raw_key(key, page):
    if not isinstance(key, bytes) or len(key) != 32 or len(page) != 4096:
        return False
    if page.startswith(b'SQLite format 3\0'):
        return False
    mac_key=hashlib.pbkdf2_hmac('sha512',key,bytes(x^0x3a for x in page[:16]),2,32)
    mac=hmac.new(mac_key,page[16:4032]+b'\x01\x00\x00\x00',hashlib.sha512).digest()
    return hmac.compare_digest(mac,page[4032:4096])


def private_database_path(root, relative):
    root=Path(root).absolute()
    rel=Path(relative)
    if rel.anchor or '..' in rel.parts or not rel.parts or rel.suffix!='.db':
        raise AXRError('database_path_outside_account')
    path=root/rel
    for parent in (root,*root.parents):
        if parent.is_symlink() or parent.is_junction():raise AXRError('database_symlink_denied')
    current=root
    for part in rel.parts:
        current=current/part
        if current.is_symlink() or current.is_junction():raise AXRError('database_symlink_denied')
    if not path.is_file():raise AXRError('database_missing')
    return path.resolve(strict=True)


def inventory(root, maximum=128):
    if type(maximum) is not int or not 1<=maximum<=128:raise AXRError('database_inventory_budget')
    root=Path(root).absolute()
    if not root.is_dir():raise AXRError('account_database_root_missing')
    result={}
    def denied(_):raise AXRError('database_inventory_directory_unreadable')
    visited=0
    for directory,dirs,files in os.walk(root,followlinks=False,onerror=denied):
        visited+=len(dirs)+len(files)+1
        if visited>4096:raise AXRError('database_inventory_budget')
        dirs.sort()
        if any((Path(directory)/d).is_symlink() or (Path(directory)/d).is_junction() for d in dirs):raise AXRError('database_symlink_denied')
        for name in sorted(files):
            if not name.endswith('.db'):continue
            path=private_database_path(root,(Path(directory)/name).relative_to(root))
            with path.open('rb') as stream:page=stream.read(4096)
            if page.startswith(b'SQLite format 3\0'):continue
            if len(page)!=4096:raise AXRError('encrypted_database_page_format_unqualified')
            if len(result)>=maximum:raise AXRError('database_inventory_budget')
            result[path.relative_to(root).as_posix()]={'path':path,'page':page,'salt':page[:16].hex()}
    if not result:raise AXRError('encrypted_database_inventory_empty')
    return result


def provision_verified(root, relative, key, secret_store, expected_salt, *, key_mode='raw'):
    if key_mode not in ('raw','password'):raise AXRError('unsupported_database_key_mode')
    path=private_database_path(root,relative)
    with path.open('rb') as stream:page=stream.read(4096)
    if page[:16].hex()!=expected_salt:raise AXRError('database_generation_changed_before_key_provision')
    effective=verified_page_key(page,key,key_mode)
    if effective is None:raise AXRError('candidate_key_hmac_rejected')
    ref='wcdb:'+digest([str(path),expected_salt])
    secret_store.provision(ref,effective)
    return {'key_reference':ref,'salt':expected_salt,'cipher_profile':'wcdb4-raw'}


def qualify_contacts(path, library, key, account_id, labels, *, profile='wcdb4-raw', account_root=None):
    """Exact owner labels -> stable usernames, never first-of-duplicate matches."""
    identifier(account_id)
    if not labels or len(labels)>32 or len(set(labels))!=len(labels):
        raise AXRError('explicit_unique_contact_labels_required')
    for label in labels:identifier(label)
    db=CipherConnection(path,library,key.hex(),profile)
    try:
        columns={r['name'] for r in db.query('PRAGMA table_info("contact")')}
        if not {'username','nick_name','remark','delete_flag'}<=columns:raise AXRError('contact_schema_unqualified')
        own=db.query('SELECT username FROM contact WHERE username=? LIMIT 2',(account_id,))
        if len(own)!=1:raise AXRError('account_identity_not_in_contact_database')
        if account_root is not None:
            root=Path(account_root).absolute()
            if root.name!='db_storage':raise AXRError('account_layout_unqualified')
            # v4 account folders are username[_installation-suffix]. Resolve
            # bounded exact candidate names, rejecting prefix collisions.
            parts=root.parent.name.split('_')
            if len(parts)>16:raise AXRError('account_directory_identity_unqualified')
            candidates=['_'.join(parts[:n]) for n in range(1,len(parts)+1)]
            marks=','.join('?' for _ in candidates)
            names=db.query('SELECT username FROM contact WHERE username IN ('+marks+') LIMIT 2',tuple(candidates))
            if len(names)!=1 or names[0]['username']!=account_id:
                raise AXRError('account_directory_identity_missing_or_ambiguous')
        bindings=[]
        for label in labels:
            rows=db.query("SELECT username,nick_name,remark FROM contact WHERE (username=? OR nick_name=? OR remark=?) "
                          "AND delete_flag=0 AND username NOT LIKE '%@chatroom' AND substr(username,1,3)!='gh_' LIMIT 3",
                          (label,label,label))
            if len(rows)!=1:raise AXRError('contact_identity_missing_or_ambiguous')
            username=identifier(rows[0]['username'])
            if username.endswith('@chatroom'):raise AXRError('private_test_contact_required')
            bindings.append({'conversation_id':username,'display_name':label,'schema':'v4','data_class':'personal'})
        if len({b['conversation_id'] for b in bindings})!=len(bindings):raise AXRError('duplicate_stable_contact_identity')
        return bindings
    finally:db.close()
