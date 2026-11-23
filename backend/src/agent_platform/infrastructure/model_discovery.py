"""向 OpenAI 兼容接口查询可用模型：GET {base_url}/models。

只服务于设置页的“获取可用模型”：请求仅发往用户本人填写的 Base URL，
API Key 只作为 Authorization 头透传给该地址——不写库、不落盘、不改任何配置。
DeepSeek / 通义（compatible-mode）/ 智谱 / OpenAI 等主流平台均实现了这个端点，
返回的即是该 Key 当前真实可调用的模型名，天然“随官方政策同步”。

响应形状按 OpenAI 约定：{"data": [{"id": "...", ...}, ...]}。
"""
from __future__ import annotations

import httpx

TIMEOUT_SECONDS = 12.0


class DiscoveryError(RuntimeError):
    """Base URL 不合法、连不上、鉴权失败或响应形状不对。"""


def normalize_base_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    if not url:
        raise DiscoveryError("Base URL 为空")
    if not url.startswith(("http://", "https://")):
        raise DiscoveryError("Base URL 需以 http:// 或 https:// 开头")
    return url


def _error_brief(resp: httpx.Response) -> str:
    """HTTP 错误尽量带上服务端信息，但截断以免刷屏。"""
    detail = ""
    try:
        payload = resp.json()
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            detail = str(err.get("message") or "")
    except ValueError:
        pass
    if not detail:
        detail = resp.text
    return detail[:200] or f"HTTP {resp.status_code}"


async def discover_models(base_url: str, api_key: str, *, client: httpx.AsyncClient | None = None) -> list[str]:
    """拉取模型 id 列表；失败抛 DiscoveryError。client 可注入（测试用 MockTransport）。"""
    url = f"{normalize_base_url(base_url)}/models"
    key = api_key.strip()
    if not key:
        raise DiscoveryError("API Key 为空")
    headers = {"Authorization": f"Bearer {key}"}
    if client is not None:
        resp = await client.get(url, headers=headers)
    else:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as own:
            resp = await own.get(url, headers=headers)
    if resp.status_code != 200:
        raise DiscoveryError(f"HTTP {resp.status_code}：{_error_brief(resp)}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise DiscoveryError("响应不是 JSON，可能不是 OpenAI 兼容接口") from exc
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise DiscoveryError("响应缺少标准 data 列表，可能不支持 /models")
    return [str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")]
