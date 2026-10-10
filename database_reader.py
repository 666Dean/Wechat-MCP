"""Read-only WCDB boundary, explicit identity binding and bounded reconciliation.

The native ABI is pinned to EchoTrace v3.0.2. No DLLs or secrets ship here.
"""
import ctypes as C
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path


class ReaderError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_database_config(config):
    required = {"account_id", "session_db", "dll_path", "key_file", "conversations",
                "page_size", "max_pages"}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("database_reader 字段必须与数据库配置模板一致；禁止在配置中放置密钥")
    for key in ("account_id", "session_db", "dll_path", "key_file"):
        if not isinstance(config[key], str) or not config[key].strip() or "\x00" in config[key]:
            raise ValueError(f"database_reader.{key} 必须是非空字符串")
    for key in ("session_db", "dll_path", "key_file"):
        if not Path(config[key]).is_absolute():
            raise ValueError(f"database_reader.{key} 必须是绝对路径")
    if Path(config["key_file"]).suffix.lower() != ".dpapi":
        raise ValueError("key_file 必须使用独立的 .dpapi 文件，不能覆盖数据库或配置")
    if type(config["page_size"]) is not int or not 2 <= config["page_size"] <= 1000:
        raise ValueError("page_size 必须是 2 到 1000 的整数")
    if type(config["max_pages"]) is not int or not 1 <= config["max_pages"] <= 1000:
        raise ValueError("max_pages 必须是 1 到 1000 的整数")
    bindings = config["conversations"]
    if not isinstance(bindings, list):
        raise ValueError("conversations 必须是显式授权的私人会话列表")
    ids, names = set(), set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"conversation_id", "display_name"}:
            raise ValueError("会话绑定必须包含 conversation_id 和 display_name")
        cid, name = binding["conversation_id"], binding["display_name"]
        if any(not isinstance(v, str) or not v.strip() or any(ord(c) < 32 for c in v)
               for v in (cid, name)):
            raise ValueError("会话 ID 和显示名必须是非空且无控制字符的字符串")
        if cid == config["account_id"] or "@" in cid or cid in ("filehelper", "fmessage", "weixin") or cid.startswith("gh_"):
            raise ValueError("仅允许使用者明确指定的私人好友会话")
        if cid in ids or name in names:
            raise ValueError("会话 ID 或显示名重复，拒绝歧义绑定")
        ids.add(cid)
        names.add(name)
    return config


def validate_runtime_paths(config, config_path):
    if config["backend"] != "wcdb":
        return
    path = Path(config_path).resolve()
    reader = config["database_reader"]
    paths = [path, (path.parent / config["state_file"]).resolve(),
             *(Path(reader[k]).resolve() for k in ("session_db", "dll_path", "key_file"))]
    canonical = [os.path.normcase(str(p)) for p in paths]
    if len(set(canonical)) != len(canonical):
        raise ValueError("配置、状态库、微信数据库、DLL 与凭据文件必须使用不同路径")


def account_binding(config):
    """Bind the owner's declared wxid to the canonical account directory.

    The ABI has no self-identity endpoint; this is path binding, not attestation.
    """
    entry = Path(config["session_db"]).resolve()
    root = next((p for p in (entry, *entry.parents) if p.name == "db_storage"), None)
    account = config["account_id"]
    if root is None or not (root.parent.name == account or root.parent.name.startswith(account + "_")):
        raise ReaderError("数据库目录与配置账号不匹配；请核对 account_id 和 db_storage 路径")
    return digest([account, os.path.normcase(str(entry))])


def validate_sessions(rows, names, bindings):
    if not isinstance(rows, list) or not isinstance(names, dict):
        raise ReaderError("会话或显示名返回格式无效")
    ids = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("username"), str) or not row["username"]:
            raise ReaderError("会话 ID 缺失或原生接口返回诊断错误")
        ids.append(row["username"])
    if len(ids) != len(set(ids)):
        raise ReaderError("会话 ID 重复")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in names.items()):
        raise ReaderError("显示名返回格式无效")
    counts = Counter(names.get(cid) for cid in ids)
    for binding in bindings:
        cid, name = binding["conversation_id"], binding["display_name"]
        if cid not in ids or names.get(cid) != name or counts[name] != 1:
            raise ReaderError("授权会话缺失、显示名改变或重名；请在本机重新核对绑定")
    return len(ids)


def integer(row, key, default=None):
    value = row.get(key, default)
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    raise ReaderError("消息数值字段缺失或无效")


def normalize_message(row, account, conversation):
    if not isinstance(row, dict) or "_error" in row:
        raise ReaderError("消息返回格式无效或原生查询失败")
    # Some native versions expose a shard name; never mistake message 'source'
    # (a payload field in WeChat) for the database shard identity.
    shard = row.get("source_db")
    if shard is not None and (not isinstance(shard, str) or not shard):
        raise ReaderError("分库标识无效")
    local = integer(row, "local_id")
    server = integer(row, "server_id", 0)
    created = integer(row, "create_time")
    seq = integer(row, "sort_seq", 0)
    if local <= 0 or created <= 0 or seq < 0:
        raise ReaderError("消息身份或时间无效")
    if not shard and server <= 0:
        raise ReaderError("消息缺少分库标识和有效 server_id；停止读取以避免 local_id 冲突")
    source = "shard:" + digest(shard) if shard else "native-server"
    # With a shard identity, server acknowledgement (0 -> positive server_id)
    # must not create another event. Without a shard, require the server identity
    # plus native metadata rather than assuming server_id alone is globally unique.
    identity = [local, created, seq] if shard else [local, server, created, seq]
    key = digest([account, conversation, source, identity])
    sender = row.get("sender_username")
    flags = [integer(row, k) for k in ("computed_is_send", "is_send") if row.get(k) is not None]
    if any(flag not in (0, 1) for flag in flags):
        raise ReaderError("消息方向字段无效")
    incoming = sender == conversation and sender != account and not any(flags)
    # Without sender identity, only an explicit receive flag permits text ingestion.
    if not sender:
        incoming = bool(flags) and all(flag == 0 for flag in flags)
    kind = integer(row, "local_type", 0)
    text = row.get("message_content")
    # Compressed/binary content needs a separately validated decoder, not guessing.
    compressed = row.get("compress_content") or row.get("WCDB_CT_message_content")
    readable = incoming and kind == 1 and isinstance(text, str) and bool(text.strip()) and not compressed
    return {"key": key, "source": source, "created": created, "seq": seq,
            "text": text if readable else None}


def reconcile(reader, conversation, config):
    """Two identical bounded full scans, with overlap on offset pagination.

    The ABI lacks snapshot/keyset queries. Never silently advance after truncation
    or unstable scans. This trades throughput for explicit, retryable failure.
    """
    previous = None
    size = config["page_size"]
    step = max(1, size * 4 // 5)
    for _ in range(3):
        found = {}
        offset = 0
        for _ in range(config["max_pages"]):
            rows = reader.messages(conversation, size, offset)
            if not isinstance(rows, list) or len(rows) > size:
                raise ReaderError("消息分页返回格式无效")
            for row in rows:
                message = normalize_message(row, reader.account_id, conversation)
                old = found.get(message["key"])
                if old is not None and old != message:
                    raise ReaderError("重叠分页中的消息身份冲突")
                found[message["key"]] = message
            if len(rows) < size:
                break
            offset += step
        else:
            raise ReaderError("会话超过 max_pages，未推进基线；请提高本机限额后重启")
        if previous == found:
            return sorted(found.values(), key=lambda m: (m["created"], m["seq"], m["key"]))
        previous = found
    raise ReaderError("分页期间消息持续变化，未推进基线；请再次轮询")


class WcdbReader:
    """Serialized by Bridge's worker; loads only an explicitly selected DLL."""
    def __init__(self, config, *, native=None, key_loader=None):
        from local_credentials import load_key
        self.config = config
        self.account_id = config["account_id"]
        self.binding = account_binding(config)
        self.entry = Path(config["session_db"]).resolve()
        self.file_identity = self._identity()
        self.native = native
        self.handle = C.c_int64()
        self.initialized = False
        self.dll_directory = None
        if native is None:
            if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
                raise ReaderError("WCDB 实时读取需要 Windows x64 Python")
            dll = Path(config["dll_path"]).resolve()
            try:
                self.dll_directory = os.add_dll_directory(str(dll.parent))
                self.native = C.CDLL(str(dll), winmode=0x1100)
            except (OSError, AttributeError):
                self.close()
                raise ReaderError("无法加载指定 WCDB DLL 及其依赖") from None
        try:
            self._declare()
            self._check(self.native.wcdb_init(), "init")
            self.initialized = True
            key = (key_loader or load_key)(config)
            if not isinstance(key, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", key):
                raise ReaderError("本机数据库密钥格式无效")
            key_buffer = C.create_string_buffer(key.encode("ascii"))
            del key
            try:
                code = self.native.wcdb_open_account(str(self.entry).encode("utf-8"), key_buffer, C.byref(self.handle))
                self._check(code, "open_account")
                if self.handle.value <= 0:
                    raise ReaderError("原生账号句柄无效")
            finally:
                C.memset(key_buffer, 0, C.sizeof(key_buffer))
        except BaseException:
            self.close()
            raise

    def _identity(self):
        try:
            stat = self.entry.stat()
            return stat.st_dev, stat.st_ino
        except OSError:
            raise ReaderError("配置的数据库入口不存在或不可访问") from None

    def _verify(self):
        if not self.handle.value or account_binding(self.config) != self.binding or self._identity() != self.file_identity:
            raise ReaderError("数据库账号、入口或文件身份改变，请停止并重新核对配置")

    def _declare(self):
        out = C.POINTER(C.c_void_p)
        specs = {
            "wcdb_init": ([], C.c_int32), "wcdb_shutdown": ([], C.c_int32),
            "wcdb_open_account": ([C.c_char_p, C.c_char_p, C.POINTER(C.c_int64)], C.c_int32),
            "wcdb_close_account": ([C.c_int64], C.c_int32),
            "wcdb_free_string": ([C.c_void_p], None),
            "wcdb_get_sessions": ([C.c_int64, out], C.c_int32),
            "wcdb_get_messages": ([C.c_int64, C.c_char_p, C.c_int32, C.c_int32, out], C.c_int32),
            "wcdb_get_display_names": ([C.c_int64, C.c_char_p, out], C.c_int32),
        }
        for name, (args, result) in specs.items():
            function = getattr(self.native, name)
            function.argtypes, function.restype = args, result

    @staticmethod
    def _check(code, operation):
        if code != 0:
            raise ReaderError(f"WCDB {operation} 失败（状态码 {code}）")

    def _json(self, operation, *args, expected=list):
        self._verify()
        pointer = C.c_void_p()
        try:
            code = getattr(self.native, "wcdb_" + operation)(self.handle, *args, C.byref(pointer))
            self._check(code, operation)
            if not pointer.value:
                raise ReaderError("原生查询未返回 JSON 指针")
            try:
                result = json.loads(C.string_at(pointer).decode("utf-8"))
            except (UnicodeError, ValueError):
                raise ReaderError("原生查询返回无效 UTF-8 JSON") from None
            if not isinstance(result, expected) or (isinstance(result, dict) and "_error" in result) or (
                    isinstance(result, list) and any(not isinstance(r, dict) or "_error" in r for r in result)):
                raise ReaderError("原生查询返回错误或意外结构")
            return result
        finally:
            if pointer.value:
                self.native.wcdb_free_string(pointer)

    def sessions(self):
        rows = self._json("get_sessions")
        # Validate IDs before passing them back to the DLL.
        validate_sessions(rows, {}, [])
        ids = [r["username"] for r in rows]
        names = self._json("get_display_names", json.dumps(ids).encode("utf-8"), expected=dict) if ids else {}
        validate_sessions(rows, names, self.config["conversations"])
        return rows, names

    def messages(self, conversation, limit, offset):
        if conversation not in {b["conversation_id"] for b in self.config["conversations"]}:
            raise ReaderError("该会话未获本机读取授权")
        return self._json("get_messages", conversation.encode("utf-8"), limit, offset)

    def close(self):
        try:
            if self.handle.value and self.native is not None:
                self.native.wcdb_close_account(self.handle)
                self.handle.value = 0
        finally:
            try:
                if self.initialized:
                    self.native.wcdb_shutdown()
                    self.initialized = False
            finally:
                if self.dll_directory is not None:
                    self.dll_directory.close()
                    self.dll_directory = None
