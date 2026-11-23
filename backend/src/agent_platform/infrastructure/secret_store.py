"""敏感配置字段的本地加密（v0.5.2）。

Windows 下用系统 DPAPI（CryptProtectData，按当前登录用户作用域）加密后落盘——零第三方依赖；
密文以 `enc:v1:` 前缀标记存进 JSON。v1 时代的明文 Key 读取时原样透传，下一次保存自动升级。

DPAPI 密文与 Windows 用户绑定：换机/换用户后解不开，按“未配置”处理并提示重新填入，
宁可让用户重填，也绝不解出错误内容。
非 Windows 平台（未来云端）暂为透传明文：云端应等 v0.7 账号体系后用 KMS/Secrets Manager 统一解决。
"""
from __future__ import annotations

import base64
import ctypes
import sys

PREFIX = "enc:v1:"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, *, protect: bool) -> bytes | None:
    """调用 CryptProtectData / CryptUnprotectData；任何失败返回 None（调用方降级处理）。"""
    if sys.platform != "win32":
        return None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        blob_in = _DataBlob(len(data), ctypes.create_string_buffer(data, len(data)))
        blob_out = _DataBlob()
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.c_void_p] * 7
        fn.restype = ctypes.c_int
        if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            return None
        try:
            buf = ctypes.create_string_buffer(blob_out.cbData)
            ctypes.memmove(buf, blob_out.pbData, blob_out.cbData)
            return buf.raw
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:  # noqa: BLE001 — 加密不可用绝不允许拖垮应用
        return None


def encrypt(plain: str) -> str:
    """明文 → 存储值（DPAPI 可用时为 enc:v1:...，否则原样）。空串原样返回。"""
    if not plain or plain.startswith(PREFIX):
        return plain
    blob = _dpapi(plain.encode("utf-8"), protect=True)
    if blob is None:
        return plain
    return PREFIX + base64.b64encode(blob).decode("ascii")


def decrypt(stored: str) -> str:
    """存储值 → 明文。无前缀视为历史明文；解不开（换用户/换机/损坏）视为未配置返回空。"""
    if not stored:
        return ""
    if not stored.startswith(PREFIX):
        return stored
    try:
        blob = base64.b64decode(stored[len(PREFIX) :], validate=True)
    except ValueError:
        return ""
    plain = _dpapi(blob, protect=False)
    if plain is None:
        return ""
    return plain.decode("utf-8", errors="replace")
