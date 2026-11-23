"""OpenAI 兼容图像生成（v0.6 生图角色）：POST {base_url}/images/generations。

端点、凭据、模型名全部来自用户配置的“生图角色”（settings_service.resolve_role("image_gen")）——
请求只发往用户填写/预设的 Base URL，Key 只作为该家 Authorization 头，不落日志、不转发第三方。

响应两种形状都接：
- {"data":[{"b64_json":"..."}]} —— 直接解码；
- {"data":[{"url":"https://..."}]} —— 服务端代取下载（仅 https、限 10MB，超时 60s）。

百炼 compatible-mode / 智谱 v4 等均为 OpenAI 兼容 images 端点；各家对 size 的取值不完全一致，
默认 1024x1024，非法值由厂商报错、原样透出给用户可见的错误文本。
"""
from __future__ import annotations

import base64

import httpx

TIMEOUT_SECONDS = 120.0
DOWNLOAD_TIMEOUT_SECONDS = 60.0
MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEFAULT_SIZE = "1024x1024"


class ImageGenError(RuntimeError):
    """端点不可达、鉴权失败、形状不对、图片过大。"""


def _error_brief(resp: httpx.Response) -> str:
    detail = ""
    try:
        payload = resp.json()
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            detail = str(err.get("message") or "")
        elif isinstance(err, str):
            detail = err
    except ValueError:
        pass
    if not detail:
        detail = resp.text
    return detail[:200] or f"HTTP {resp.status_code}"


def _sniff_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


async def _download_image(client: httpx.AsyncClient, url: str) -> bytes:
    if not url.startswith("https://"):
        raise ImageGenError("厂商返回了非 https 的图片地址，出于安全不代为下载")
    try:
        resp = await client.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise ImageGenError(f"下载生成结果失败：{exc}") from exc
    if resp.status_code != 200:
        raise ImageGenError(f"下载生成结果失败：HTTP {resp.status_code}")
    data = resp.content
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageGenError("生成结果超过 10MB 上限，已丢弃")
    return data


async def generate_image(
    base_url: str, api_key: str, model: str, prompt: str,
    size: str = DEFAULT_SIZE,
    *, client: httpx.AsyncClient | None = None,
) -> tuple[bytes, str]:
    """生成一张图，返回 (bytes, content_type)；client 可注入（测试用 MockTransport）。"""
    endpoint = f"{base_url.strip().rstrip('/')}/images/generations"
    if not api_key.strip():
        raise ImageGenError("生图角色缺少 API Key")
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
    payload = {"model": model, "prompt": prompt, "size": size, "n": 1}
    try:
        if client is not None:
            resp = await client.post(endpoint, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as own:
                resp = await own.post(endpoint, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise ImageGenError(f"请求失败：{exc}") from exc
    if resp.status_code != 200:
        raise ImageGenError(f"HTTP {resp.status_code}：{_error_brief(resp)}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise ImageGenError("生图响应不是 JSON，端点可能不兼容 OpenAI images 格式") from exc
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise ImageGenError("生图响应缺少标准 data[0]")
    item = items[0]
    if item.get("b64_json"):
        try:
            data = base64.b64decode(str(item["b64_json"]), validate=False)
        except ValueError as exc:
            raise ImageGenError("b64_json 解码失败") from exc
        if len(data) > MAX_IMAGE_BYTES:
            raise ImageGenError("生成结果超过 10MB 上限，已丢弃")
        return data, _sniff_mime(data)
    if item.get("url"):
        if client is not None:
            data = await _download_image(client, str(item["url"]))
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as own:
                data = await _download_image(own, str(item["url"]))
        return data, _sniff_mime(data)
    raise ImageGenError("生图响应 data[0] 里既没有 b64_json 也没有 url")
