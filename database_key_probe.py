"""Bounded SQLCipher-4 page-one authentication, without native libraries.

Format reference: chatlog-keeper at 2225294fd0761e10ce15540f21e7dbb2ac304c3c,
wechat_db.py (_effective_page_key). No third-party source is bundled.
This diagnoses key compatibility, not account identity or message readability.
"""
import hashlib
import hmac
import os
import re
import struct
from pathlib import Path


def verified_page_key(page, key, mode="raw"):
    """Normalize an explicitly selected SQLCipher4 key mode after page HMAC validation."""
    if mode not in ("raw", "password"):
        raise ValueError("unsupported_database_key_mode")
    if (not isinstance(page, bytes) or len(page) != 4096
            or page.startswith(b"SQLite format 3\0")
            or not isinstance(key, bytes) or len(key) != 32):
        return None
    candidate = (hashlib.pbkdf2_hmac("sha512", key, page[:16], 256000, 32)
                 if mode == "password" else key)
    mac_key = hashlib.pbkdf2_hmac("sha512", candidate,
                                bytes(value ^ 0x3A for value in page[:16]), 2, 32)
    mac = hmac.new(mac_key, page[16:4032] + struct.pack("<I", 1), hashlib.sha512).digest()
    return candidate if hmac.compare_digest(mac, page[4032:]) else None


def page_key_mode(page, key):
    """Return raw/password/unmatched; reject incomplete or invalid inputs."""
    if not isinstance(page, bytes) or len(page) != 4096:
        raise ValueError("数据库首页面大小无效")
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("数据库密钥格式无效")
    salt = page[:16]
    mac_salt = bytes(value ^ 0x3A for value in salt)

    def matches(candidate):
        mac_key = hashlib.pbkdf2_hmac("sha512", candidate, mac_salt, 2, 32)
        mac = hmac.new(mac_key, page[16:4032] + struct.pack("<I", 1), hashlib.sha512)
        return hmac.compare_digest(mac.digest(), page[4032:])

    if matches(key):
        return "raw"
    derived = hashlib.pbkdf2_hmac("sha512", key, salt, 256000, 32)
    return "password" if matches(derived) else "unmatched"


def probe_database_key(config, *, key_loader=None):
    """Read only first pages in the bound account; never output paths or keys."""
    from database_reader import account_binding, validate_database_config
    from local_credentials import load_key
    validate_database_config(config)
    account_binding(config)
    session = Path(config["session_db"]).resolve()
    root = session.parent.parent
    if session != root / "session" / "session.db" or root.name != "db_storage":
        raise ValueError("仅支持绑定账号的标准会话库入口")
    directory = root / "message"
    if directory.resolve() != directory:
        raise ValueError("拒绝消息目录链接或路径重定向")
    files = [session]
    for path in directory.glob("message_*.db"):
        if not re.fullmatch(r"message_[0-9]+\.db", path.name):
            continue
        if path.resolve() != path or not path.is_file():
            raise ValueError("拒绝消息库链接或无效文件")
        files.append(path)
        if len(files) > 65:
            raise ValueError("消息分库超出诊断上限（64）")
    key_text = (key_loader or load_key)(config)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", key_text):
        raise ValueError("本机密钥格式无效")
    key = bytes.fromhex(key_text)
    result = {"checked_count": 0, "message_database_count": len(files) - 1,
              "raw_count": 0, "password_count": 0, "unmatched_count": 0,
              "error_count": 0, "message_body_read": False, "state_changed": False}
    for path in files:
        try:
            with path.open("rb") as handle:
                before = os.fstat(handle.fileno())
                page = handle.read(4096)
                handle.seek(0)
                if handle.read(4096) != page:
                    raise ValueError("首页面读取期间发生变化")
                after = path.stat()
                if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
                    raise ValueError("首页面读取期间文件发生变化")
            mode = page_key_mode(page, key)
            result[mode + "_count"] += 1
            result["checked_count"] += 1
        except (OSError, ValueError):
            result["error_count"] += 1
    result["key_matches_all"] = not (result["unmatched_count"] or result["error_count"])
    result["message_key_verified"] = result["key_matches_all"] and len(files) > 1
    return result
