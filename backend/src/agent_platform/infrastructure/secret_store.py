"""敏感配置字段的加密存储（v0.5.2 引入，v0.7 双后端）。

按 auth_mode 选加密后端——加密结果都带前缀标记，读取时按前缀分派，跨后端的历史密文不受影响：

- local（默认，Windows）：系统 DPAPI（CryptProtectData，按当前登录用户作用域）——零第三方依赖；
  密文前缀 `enc:v1:`。DPAPI 密文与 Windows 用户绑定：换机/换用户后解不开，按"未配置"处理并提示
  重新填入，宁可让用户重填，也绝不解出错误内容。
- cloud：Fernet（`cryptography` 包，v0.7 唯一新增依赖），密钥由 .env 的 SERVICE_SECRET 经
  SHA-256 派生；密文前缀 `enc:f1:`。云端（Linux）没有 DPAPI，SERVICE_SECRET 是唯一的解密根。
  cloud 模式加密时缺 SERVICE_SECRET 直接抛错——宁可启动失败，也绝不把明文 Key 落盘。
- v1 时代的无前缀明文 Key 读取时原样透传，下一次保存自动升级为带前缀密文。

"HTTP 响应与前端状态永不出现明文 Key"的红利照旧成立。
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import sys

from agent_platform.config import settings

PREFIX_DPAPI = "enc:v1:"
PREFIX_FERNET = "enc:f1:"

_FERNET_ERROR = (
    "cloud 模式必须配置 SERVICE_SECRET（.env，用于加密用户 API Key），"
    "否则密钥只能明文落盘——拒绝继续。"
)


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


def _fernet():
    """由 SERVICE_SECRET 派生 Fernet 密钥（任意字符串 → 32 字节 urlsafe base64）。未配置返回 None。"""
    if not settings.service_secret:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:  # pragma: no cover — pyproject 已带 cryptography，缺了要在安装环节暴露
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.service_secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt(plain: str) -> str:
    """明文 → 存储值。local=DPAPI（enc:v1:），cloud=Fernet（enc:f1:）。空串原样返回。"""
    if not plain or plain.startswith((PREFIX_DPAPI, PREFIX_FERNET)):
        return plain
    if settings.auth_mode == "cloud":
        fernet = _fernet()
        if fernet is None:
            raise RuntimeError(_FERNET_ERROR)
        return PREFIX_FERNET + fernet.encrypt(plain.encode("utf-8")).decode("ascii")
    blob = _dpapi(plain.encode("utf-8"), protect=True)
    if blob is None:
        return plain
    return PREFIX_DPAPI + base64.b64encode(blob).decode("ascii")


def decrypt(stored: str) -> str:
    """存储值 → 明文。按前缀分派；解不开（换机/换密钥/损坏）一律视为未配置返回空。"""
    if not stored:
        return ""
    if stored.startswith(PREFIX_FERNET):
        fernet = _fernet()
        if fernet is None:
            return ""
        try:
            return fernet.decrypt(stored[len(PREFIX_FERNET) :].encode("ascii")).decode("utf-8")
        except Exception:  # noqa: BLE001 — 密钥不匹配/损坏密文：按未配置处理
            return ""
    if not stored.startswith(PREFIX_DPAPI):
        return stored  # v1 历史明文透传，下次保存自动升级
    try:
        blob = base64.b64decode(stored[len(PREFIX_DPAPI) :], validate=True)
    except ValueError:
        return ""
    plain = _dpapi(blob, protect=False)
    if plain is None:
        return ""
    return plain.decode("utf-8", errors="replace")
