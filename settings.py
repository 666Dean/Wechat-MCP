"""Validated configuration and cooperative, OS-backed process locks."""
import errno
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path


class LockBusyError(RuntimeError):
    pass


class FileLock:
    """Keep the file: deleting it on unlock would allow two different lock files."""
    def __init__(self, path, timeout=2):
        self.path = Path(path)
        self.timeout = timeout
        self.handle = None

    def acquire(self):
        handle = self.path.open("a+b")
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.handle = handle
                    return self
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() >= deadline:
                        raise LockBusyError("文件正由另一个程序使用，请稍后重试") from exc
                    time.sleep(0.05)
        except BaseException:
            handle.close()
            raise

    def close(self):
        if self.handle is not None:
            # Closing the descriptor releases the OS lock, including on process exit.
            self.handle.close()
            self.handle = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.close()


def normalize_contacts(names):
    if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        raise ValueError("请提供备注名字符串列表；空列表表示取消全部主动代回复")
    result = []
    for name in names:
        name = name.strip()
        if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
            raise ValueError("备注名不能为空、不能含控制字符，且最多 100 字")
        if name not in result:
            result.append(name)
    return result


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("配置必须是 JSON 对象")
    config = dict(config)
    config["active_contacts"] = normalize_contacts(config.get("active_contacts"))
    if type(config.get("send_enabled")) is not bool:
        raise ValueError("send_enabled 必须是 JSON 布尔值 true 或 false")
    for key in ("backend", "state_file", "mention_pattern", "reply_prefix", "introduction"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} 必须是非空字符串")
    try:
        re.compile(config["mention_pattern"])
    except re.error as exc:
        raise ValueError("mention_pattern 不是有效正则表达式") from exc
    maximum = config.get("max_reply_chars")
    if type(maximum) is not int or maximum < 1:
        raise ValueError("max_reply_chars 必须是正整数")
    interval = config.get("min_reply_interval_seconds")
    if type(interval) not in (int, float) or not math.isfinite(interval) or interval < 0:
        raise ValueError("min_reply_interval_seconds 必须是非负有限数字")
    if config["backend"] == "wcdb":
        from database_reader import validate_database_config
        validate_database_config(config.get("database_reader"))
    elif config.get("database_reader") is not None:
        raise ValueError("database_reader 仅可与 backend=wcdb 一起使用")
    return config


def contact_result(config):
    return {"active_contacts": list(config["active_contacts"]),
            "other_friends": "仅明确呼叫 Codex 时回复",
            "matching": "微信中的唯一备注名，精确匹配"}


class ConfigStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def _read(self):
        from database_reader import validate_runtime_paths
        config = validate_config(json.loads(self.path.read_text(encoding="utf-8-sig")))
        validate_runtime_paths(config, self.path)
        return config

    def _write(self, config):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".contacts-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(config, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def _ensure(self):
        if not self.path.exists():
            example = self.path.with_name("config.example.json")
            config = validate_config(json.loads(example.read_text(encoding="utf-8-sig")))
            self._write(config)

    def load(self):
        with FileLock(self.lock_path):
            self._ensure()
            return self._read()

    def set_contacts(self, names):
        names = normalize_contacts(names)
        with FileLock(self.lock_path):
            self._ensure()
            config = self._read()
            config["active_contacts"] = names
            self._write(config)
        return {"status": "saved", **contact_result(config),
                "effective": "运行中的服务将在下一次工具调用时自动加载，无需重启"}
