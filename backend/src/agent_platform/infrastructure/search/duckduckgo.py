"""DuckDuckGo 搜索（默认，零配置）。

依赖 ddgs 包（pip install ddgs）。在国内网络下可能不可达，可切换到 bing/tavily。
"""
from __future__ import annotations

import asyncio

from agent_platform.infrastructure.search.base import SearchResult


class DuckDuckGoSearchProvider:
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        def _run() -> list[dict]:
            from ddgs import DDGS  # 延迟导入，未安装时报清晰错误

            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        raw = await asyncio.to_thread(_run)
        return [
            SearchResult(
                title=item.get("title") or "",
                url=item.get("href") or item.get("url") or "",
                snippet=item.get("body") or "",
            )
            for item in raw
        ]
