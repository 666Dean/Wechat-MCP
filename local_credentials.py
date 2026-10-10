"""Owner-provisioned database key, encrypted using current-user Windows DPAPI."""
import ctypes as C
import os
import re
import tempfile
from pathlib import Path


class Blob(C.Structure):
    _fields_ = [("size", C.c_uint32), ("data", C.POINTER(C.c_ubyte))]


def _crypt(data, entropy, *, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("本机密钥存储仅支持 Windows DPAPI")
    crypto = C.WinDLL("crypt32", use_last_error=True)
    kernel = C.WinDLL("kernel32", use_last_error=True)
    function = crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
    function.argtypes = [C.POINTER(Blob), C.c_void_p, C.POINTER(Blob), C.c_void_p,
                         C.c_void_p, C.c_uint32, C.POINTER(Blob)]
    function.restype = C.c_int
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [C.c_void_p], C.c_void_p
    buffer, salt = C.create_string_buffer(data), C.create_string_buffer(entropy)
    src = Blob(len(data), C.cast(buffer, C.POINTER(C.c_ubyte)))
    extra = Blob(len(entropy), C.cast(salt, C.POINTER(C.c_ubyte)))
    result = Blob()
    try:
        if not function(C.byref(src), None, C.byref(extra), None, None, 1, C.byref(result)):
            raise RuntimeError("本机 DPAPI 密钥操作失败；核对 Windows 用户和账号路径绑定")
        return C.string_at(result.data, result.size)
    finally:
        C.memset(buffer, 0, C.sizeof(buffer))
        if result.data:
            C.memset(result.data, 0, result.size)
            kernel.LocalFree(result.data)


def store_key(config, key):
    from database_reader import account_binding
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", key):
        raise ValueError("密钥必须是 64 位十六进制字符串，未保存")
    encrypted = _crypt(key.encode("ascii"), account_binding(config).encode("ascii"))
    path = Path(config["key_file"])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".credential-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(encrypted)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_key(config):
    from database_reader import account_binding
    try:
        encrypted = Path(config["key_file"]).read_bytes()
    except OSError:
        raise RuntimeError("本机密钥未配置或不可访问；请运行 --store-database-key") from None
    try:
        return _crypt(encrypted, account_binding(config).encode("ascii"), decrypt=True).decode("ascii")
    except UnicodeError:
        raise RuntimeError("本机密钥内容格式无效") from None
