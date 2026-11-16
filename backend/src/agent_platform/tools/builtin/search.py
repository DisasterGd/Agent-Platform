"""联网搜索工具。"""
from __future__ import annotations

import json

from agent_platform.config import settings
from agent_platform.infrastructure.search.factory import create_search_provider
from agent_platform.tools.registry import ToolResult

WEB_SEARCH_DESCRIPTION = (
    "在互联网上搜索实时信息。当需要查询最新新闻、事实、数据，"
    "或用户问及你知识范围之外、时效性强的内容时调用。返回标题、链接和摘要。"
)
WEB_SEARCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "要搜索的关键词或问题，尽量具体"},
    },
    "required": ["query"],
}


async def web_search(query: str) -> ToolResult:
    provider = create_search_provider()
    try:
        results = await provider.search(query, max_results=settings.search_max_results)
    except Exception as exc:  # noqa: BLE001 — 网络不可达/被限流时优雅降级
        payload = {"query": query, "results": [], "error": str(exc)}
        return ToolResult(content=json.dumps(payload, ensure_ascii=False))

    payload = {
        "query": query,
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet} for r in results
        ],
    }
    return ToolResult(content=json.dumps(payload, ensure_ascii=False))
