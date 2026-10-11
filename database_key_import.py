"""Import one explicitly selected local chatlog-keeper cache after page HMAC checks.

Cache format reference: chatlog-keeper 2225294fd0761e10ce15540f21e7dbb2ac304c3c,
wechat_db.py, _parse_cached_wechat_key_text. No upstream code is bundled.
This is cache acquisition, not process-memory extraction or account attestation.
"""
import os
import re
import stat
from pathlib import Path

from database_key_probe import probe_database_key
from local_credentials import store_key


def _identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def read_key_cache(filename):
    """Bounded read of one regular 64-hex cache; no discovery or cache mutation."""
    path = Path(os.path.abspath(filename))
    parents = {}
    # 不跟随符号链接、Windows junction/reparse point；不打开管道或设备。
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("拒绝缓存路径重定向")
        if part != path:
            parents[part] = (info.st_dev, info.st_ino)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 128:
        raise ValueError("缓存必须是有界的普通文件")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if _identity(before) != _identity(opened) or not stat.S_ISREG(opened.st_mode):
            raise ValueError("缓存文件发生变化")
        raw = os.read(fd, 129)
        if (len(raw) > 128 or _identity(opened) != _identity(os.fstat(fd))
                or _identity(opened) != _identity(path.lstat())):
            raise ValueError("缓存文件发生变化")
        for parent, identity in parents.items():
            info = parent.lstat()
            if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                    or identity != (info.st_dev, info.st_ino)):
                raise ValueError("缓存目录发生变化")
    finally:
        os.close(fd)
    key = raw.decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", key):
        raise ValueError("缓存格式不支持")
    return key


def import_key_cache(config, filename):
    """Preserve existing DPAPI credential unless every selected page authenticates."""
    key = read_key_cache(filename)
    result = probe_database_key(config, key_loader=lambda _: key)
    result["key_imported"] = False
    if result["message_key_verified"]:
        # 保存原始候选；不能将某个分库的派生页密钥误当成全账号口令。
        store_key(config, key)
        result["key_imported"] = True
    return result
