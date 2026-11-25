"""图像生成适配（v0.6 生图角色；v0.6.2 按厂商响应形状分支）。

端点、凭据、模型名全部来自用户配置的“生图角色”（settings_service.resolve_role("image_gen")）——
请求只发往用户填写/预设的 Base URL，Key 只作为该家 Authorization 头，不落日志、不转发第三方。

响应形状按厂商分支（2026-11 用真实 Key 实测）：
- 通用 OpenAI 兼容：POST {base_url}/images/generations → {"data":[{"b64_json"|"url"}]}
  （智谱 v4 等；b64 直接解码，url 由服务端代取，仅 https、限 10MB）；
- DashScope（百炼）：compatible-mode 的 /images/generations 实测对 qwen-image-*/wan* 一律 404，
  真正的同步端点是原生 multimodal-generation（POST {origin}/api/v1/services/aigc/multimodal-generation/generation，
  响应 {"output":{"choices":[{"message":{"content":[{"image": url}]}}]}}）；
  size 用 W*H 星号写法。若某模型只给异步形状（{"output":{"task_id":...}}，如 text2image 系），
  则轮询 {origin}/api/v1/tasks/{id} 直到 SUCCEEDED 再取图。
- 厂商原生错误形状 {"code","message"} 也进错误摘要，保证用户看到可读文本（而不是空 body）。
"""
from __future__ import annotations

import asyncio
import base64
import time
from contextlib import asynccontextmanager

import httpx

TIMEOUT_SECONDS = 120.0
DOWNLOAD_TIMEOUT_SECONDS = 60.0
MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEFAULT_SIZE = "1024x1024"
#: 原生异步任务轮询：总时限与间隔（本地工具场景，超时即报错，不留后台任务）
TASK_POLL_LIMIT_SECONDS = 180.0
TASK_POLL_INTERVAL_SECONDS = 3.0


class ImageGenError(RuntimeError):
    """端点不可达、鉴权失败、形状不对、图片过大、异步任务失败/超时。"""


def _error_brief(resp: httpx.Response) -> str:
    detail = ""
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or err.get("code") or "")
            elif isinstance(err, str):
                detail = err
            if not detail:
                # 部分兼容端点的原生错误形状：{"code": "...", "message": "...", "request_id": "..."}
                detail = str(payload.get("message") or payload.get("code") or "")
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


@asynccontextmanager
async def _client_scope(client: httpx.AsyncClient | None):
    """外部注入了 client（测试 MockTransport）就用它，否则自建并负责关闭。"""
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as own:
        yield own


async def _post(client: httpx.AsyncClient, endpoint: str, payload: dict, headers: dict) -> httpx.Response:
    try:
        return await client.post(endpoint, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise ImageGenError(f"请求失败：{exc}") from exc


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


def _is_dashscope(base_url: str) -> bool:
    return "dashscope.aliyuncs.com" in base_url.lower()


def _origin(base_url: str) -> str:
    """https://dashscope.aliyuncs.com/compatible-mode/v1 → https://dashscope.aliyuncs.com（纯字符串截断，不走网络解析）。"""
    head = base_url.strip()
    scheme_sep = head.find("://")
    if scheme_sep < 0:
        return "https://" + head.split("/", 1)[0]
    scheme = head[:scheme_sep]
    host = head[scheme_sep + 3 :].split("/", 1)[0]
    return f"{scheme}://{host}"


def _finish(data: bytes) -> tuple[bytes, str]:
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageGenError("生成结果超过 10MB 上限，已丢弃")
    return data, _sniff_mime(data)


def _native_image_from_output(output: dict) -> str | None:
    """DashScope 原生同步形状：output.choices[*].message.content[*].image（实测 2026-11）。

    返回图片 URL；没找到返回 None。旧 text2image 的 output.results[*].url 也顺带接住。
    """
    choices = output.get("choices")
    if isinstance(choices, list):
        for ch in choices:
            msg = ch.get("message") if isinstance(ch, dict) else None
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("image"):
                        return str(part["image"])
    results = output.get("results")
    if isinstance(results, list):
        for part in results:
            if isinstance(part, dict) and part.get("url"):
                return str(part["url"])
    return None


async def generate_image(
    base_url: str, api_key: str, model: str, prompt: str,
    size: str = DEFAULT_SIZE,
    *, client: httpx.AsyncClient | None = None,
) -> tuple[bytes, str]:
    """生成一张图，返回 (bytes, content_type)；client 可注入（测试用 MockTransport）。"""
    if not api_key.strip():
        raise ImageGenError("生图角色缺少 API Key")
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
    if _is_dashscope(base_url):
        # 实测：百炼 compatible-mode 没有可用的 /images/generations（qwen-image/wan 全 404），走原生同步端点
        endpoint = f"{_origin(base_url)}/api/v1/services/aigc/multimodal-generation/generation"
        payload = {
            "model": model,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
            "parameters": {"size": size.strip().lower().replace("x", "*"), "n": 1},
        }
    else:
        endpoint = f"{base_url.strip().rstrip('/')}/images/generations"
        payload = {"model": model, "prompt": prompt, "size": size, "n": 1}

    async with _client_scope(client) as cli:
        resp = await _post(cli, endpoint, payload, headers)
        if resp.status_code != 200:
            raise ImageGenError(f"HTTP {resp.status_code}：{_error_brief(resp)}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise ImageGenError("生图响应不是 JSON，端点可能不兼容 OpenAI images 格式") from exc
        if not isinstance(body, dict):
            raise ImageGenError("生图响应不是对象，端点可能不兼容")

        # ---- 形状分支 1：OpenAI 标准 data ----
        items = body.get("data")
        if isinstance(items, list) and items:
            if not isinstance(items[0], dict):
                raise ImageGenError("生图响应缺少标准 data[0]")
            item = items[0]
            if item.get("b64_json"):
                try:
                    data = base64.b64decode(str(item["b64_json"]), validate=False)
                except ValueError as exc:
                    raise ImageGenError("b64_json 解码失败") from exc
                return _finish(data)
            if item.get("url"):
                data = await _download_image(cli, str(item["url"]))
                return _finish(data)
            raise ImageGenError("生图响应 data[0] 里既没有 b64_json 也没有 url")

        # ---- 形状分支 2/3：DashScope 原生（同步 choices 出图 / 异步 task_id 轮询）----
        output = body.get("output")
        if isinstance(output, dict):
            task_id = output.get("task_id")
            if task_id:
                return await _await_task(cli, base_url, str(task_id), headers)
            url = _native_image_from_output(output)
            if url:
                data = await _download_image(cli, url)
                return _finish(data)
        raise ImageGenError(f"无法识别的生图响应形状（顶层键：{sorted(body.keys())[:6]}）")


async def _await_task(cli: httpx.AsyncClient, base_url: str, task_id: str, headers: dict) -> tuple[bytes, str]:
    """DashScope 异步任务：轮询 {origin}/api/v1/tasks/{id} 直到 SUCCEEDED / FAILED / 超时。"""
    poll_url = f"{_origin(base_url)}/api/v1/tasks/{task_id}"
    deadline = time.monotonic() + TASK_POLL_LIMIT_SECONDS
    last_status = ""
    while time.monotonic() < deadline:
        await asyncio.sleep(TASK_POLL_INTERVAL_SECONDS)
        try:
            resp = await cli.get(poll_url, headers=headers)
        except httpx.HTTPError as exc:
            raise ImageGenError(f"轮询生图任务失败：{exc}") from exc
        if resp.status_code != 200:
            raise ImageGenError(f"轮询生图任务：HTTP {resp.status_code}：{_error_brief(resp)}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise ImageGenError("生图任务轮询响应不是 JSON") from exc
        output = body.get("output") if isinstance(body, dict) else None
        if not isinstance(output, dict):
            raise ImageGenError("生图任务轮询响应缺少 output")
        last_status = str(output.get("task_status") or "")
        if last_status == "SUCCEEDED":
            url = _native_image_from_output(output)
            if not url:
                raise ImageGenError("生图任务成功但响应里没有图片地址")
            data = await _download_image(cli, url)
            return _finish(data)
        if last_status in ("FAILED", "CANCELED", "UNKNOWN"):
            reason = str(output.get("message") or output.get("code") or "无详情")
            raise ImageGenError(f"生图任务失败（{last_status}）：{reason[:200]}")
    raise ImageGenError(f"生图任务超时（{int(TASK_POLL_LIMIT_SECONDS)}s，最后状态 {last_status or '未知'}）")
