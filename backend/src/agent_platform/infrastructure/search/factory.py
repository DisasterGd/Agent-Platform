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


def create_search_provider(db=None) -> SearchProvider:
    """按生效配置组装搜索源（v0.8.0）：传 Session 时 deployment_settings 逐字段覆盖、缺省回退 .env。

    不传 db（防御/直调）按 .env 组装（旧行为）。tavily/bing 需要 API Key（界面或 .env 均可配置）。
    """
    if db is not None:
        from agent_platform.services.platform_settings import effective_search_config

        cfg = effective_search_config(db)
        name, api_key = cfg["provider"], cfg["api_key"]
    else:
        name = settings.search_provider.strip().lower()
        api_key = settings.search_api_key

    if name == "tavily":
        if not api_key:
            raise SearchUnavailableError("使用 tavily 搜索需要配置搜索 API Key（设置 → 平台）")
        return TavilySearchProvider(api_key)
    if name == "bing":
        if not api_key:
            raise SearchUnavailableError("使用 bing 搜索需要配置搜索 API Key（设置 → 平台）")
        return BingSearchProvider(api_key)
    if name == "bing_scrape":
        return BingHTMLSearchProvider()
    if name == "auto":
        return FallbackSearchProvider([DuckDuckGoSearchProvider(), BingHTMLSearchProvider()])
    return DuckDuckGoSearchProvider()
