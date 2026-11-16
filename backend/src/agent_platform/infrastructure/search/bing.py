"""Bing Web Search（需 Azure/Bing 搜索 API Key，国内可直接访问）。"""
from __future__ import annotations

import httpx

from agent_platform.infrastructure.search.base import SearchResult


class BingSearchProvider:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://api.bing.microsoft.com/v7.0/search",
                params={"q": query, "count": max_results, "mkt": "zh-CN"},
                headers={"Ocp-Apim-Subscription-Key": self.api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        pages = data.get("webPages", {}).get("value", [])
        return [
            SearchResult(
                title=item.get("name") or "",
                url=item.get("url") or "",
                snippet=item.get("snippet") or "",
            )
            for item in pages
        ]
