"""OpenAI 兼容嵌入调用（v0.6.2 向量检索）：POST {base_url}/embeddings。

端点、凭据、模型名全部来自用户配置的“嵌入角色”（settings_service.resolve_role("embedding")）——
请求只发往用户填写/预设的 Base URL，Key 只作为该家 Authorization 头，不落日志、不转发第三方。

各家对单次请求的文本条数上限不一（DashScope compatible-mode 为 ≤10 条），统一按 10 条一批
顺序请求（本地规模无需并发），返回顺序与输入一致（响应带 index 字段时按其复位）。
失败抛 EmbeddingError（文本可读、含厂商错误摘要），由调用方决定吞掉还是透出——
索引链路要求“嵌入失败绝不阻断切块”，检索链路要求“失败静默降级纯关键词”。
"""
from __future__ import annotations

from collections.abc import Sequence

import httpx

TIMEOUT_SECONDS = 60.0
#: 单次请求的文本条数上限（各家公共的最小约束，DashScope embeddings 即 ≤10）
BATCH_SIZE = 10


class EmbeddingError(RuntimeError):
    """端点不可达、鉴权失败、响应形状不对。"""


def _error_brief(resp: httpx.Response) -> str:
    detail = ""
    try:
        payload = resp.json()
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            detail = str(err.get("message") or err.get("code") or "")
        elif isinstance(err, str):
            detail = err
        if not detail and isinstance(payload, dict):
            # 部分兼容端点的原生错误形状：{"code": "...", "message": "..."}
            detail = str(payload.get("message") or payload.get("code") or "")
    except ValueError:
        pass
    if not detail:
        detail = resp.text
    return detail[:200] or f"HTTP {resp.status_code}"


def _parse_batch(resp: httpx.Response, size: int) -> list[list[float]]:
    try:
        body = resp.json()
    except ValueError as exc:
        raise EmbeddingError("嵌入响应不是 JSON，端点可能不兼容 OpenAI embeddings 格式") from exc
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or len(data) != size:
        got = len(data) if isinstance(data, list) else "缺失"
        raise EmbeddingError(f"嵌入响应 data 数量（{got}）与请求条数（{size}）不一致")
    pairs: list[tuple[int, list[float]]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise EmbeddingError("嵌入响应 data 里出现非对象元素")
        raw = item.get("embedding")
        if not isinstance(raw, list) or not raw or not all(isinstance(x, (int, float)) for x in raw):
            raise EmbeddingError("嵌入响应缺少数值 embedding 数组")
        try:
            idx = int(item.get("index", i))  # OpenAI 兼容端点会回显 index，缺省按出现顺序
        except (TypeError, ValueError):
            idx = i
        pairs.append((idx, [float(x) for x in raw]))
    if sorted(p[0] for p in pairs) != list(range(size)):
        raise EmbeddingError("嵌入响应 index 序列异常，无法与输入对齐")
    pairs.sort(key=lambda p: p[0])
    return [p[1] for p in pairs]


def embed_texts(
    base_url: str, api_key: str, model: str, texts: Sequence[str],
    *, client: httpx.Client | None = None,
) -> list[list[float]]:
    """批量嵌入（≤10 条/请求、顺序、不并发），返回与 texts 同序的向量列表。

    client 可注入（测试用 MockTransport，https 端点也能被 mock）；不注入时自建并关闭。
    """
    if not texts:
        return []
    endpoint = f"{base_url.strip().rstrip('/')}/embeddings"
    if not api_key.strip():
        raise EmbeddingError("嵌入角色缺少 API Key")
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
    vectors: list[list[float]] = []
    own = client is None
    cli = client if client is not None else httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            payload = {"model": model, "input": batch}
            try:
                resp = cli.post(endpoint, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"请求失败：{exc}") from exc
            if resp.status_code != 200:
                raise EmbeddingError(f"HTTP {resp.status_code}：{_error_brief(resp)}")
            vectors.extend(_parse_batch(resp, len(batch)))
        return vectors
    finally:
        if own:
            cli.close()
