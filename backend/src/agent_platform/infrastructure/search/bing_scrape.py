"""Bing 网页搜索（零配置，抓取 Bing 结果页）。

国内可直接访问，无需 API Key。作为 DuckDuckGo 不可达时的兜底。
"""
from __future__ import annotations

import httpx

from agent_platform.infrastructure.search.base import SearchResult

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class BingHTMLSearchProvider:
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.bing.com/search",
                params={"q": query, "count": max_results + 5, "setlang": "zh-CN"},
                headers=_HEADERS,
            )
            resp.raise_for_status()
            html = resp.text
        return self._parse(html, max_results)

    @staticmethod
    def _parse(html: str, max_results: int) -> list[SearchResult]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("li.b_algo") or soup.select("#b_results > li")
        results: list[SearchResult] = []
        for item in items:
            a = item.select_one("h2 a")
            if a is None:
                continue
            title = a.get_text(" ", strip=True)
            url = a.get("href") or ""
            if not title or not url:
                continue
            p = item.select_one("p") or item.select_one(".b_caption p")
            snippet = p.get_text(" ", strip=True) if p else ""
            results.append(SearchResult(title=title, url=url, snippet=snippet))
            if len(results) >= max_results:
                break
        return results
