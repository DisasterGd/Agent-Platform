"""根据配置创建联网搜索提供方。"""
from __future__ import annotations

from agent_platform.config import settings
from agent_platform.infrastructure.search.base import SearchProvider, SearchResult
from agent_platform.infrastructure.search.bing import BingSearchProvider
from agent_platform.infrastructure.search.bing_scrape import BingHTMLSearchProvider
from agent_platform.infrastructure.search.duckduckgo import DuckDuckGoSearchProvider
from agent_platform.infrastructure.search.tavily import TavilySearchProvider


class SearchUnavailableError(RuntimeError):
    pass


class FallbackSearchProvider:
    """依次尝试多个提供方，返回第一个非空结果；全部失败时抛错。"""

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = providers

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        errors: list[str] = []
        for provider in self.providers:
            try:
                results = await provider.search(query, max_results)
            except Exception as exc:  # noqa: BLE001 — 逐个尝试，记录失败继续
                errors.append(f"{type(provider).__name__}: {exc}")
                continue
            if results:
                return results
        detail = "; ".join(errors) if errors else "所有搜索源均未返回结果"
        raise SearchUnavailableError(detail)


def create_search_provider() -> SearchProvider:
    name = settings.search_provider.strip().lower()
    if name == "tavily":
        if not settings.search_api_key:
            raise SearchUnavailableError("使用 tavily 搜索需要配置 SEARCH_API_KEY")
        return TavilySearchProvider(settings.search_api_key)
    if name == "bing":
        if not settings.search_api_key:
            raise SearchUnavailableError("使用 bing 搜索需要配置 SEARCH_API_KEY")
        return BingSearchProvider(settings.search_api_key)
    if name == "bing_scrape":
        return BingHTMLSearchProvider()
    if name == "auto":
        return FallbackSearchProvider([DuckDuckGoSearchProvider(), BingHTMLSearchProvider()])
    return DuckDuckGoSearchProvider()
