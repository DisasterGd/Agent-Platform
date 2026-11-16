"""根据配置创建联网搜索提供方。"""
from __future__ import annotations

from agent_platform.config import settings
from agent_platform.infrastructure.search.base import SearchProvider
from agent_platform.infrastructure.search.bing import BingSearchProvider
from agent_platform.infrastructure.search.duckduckgo import DuckDuckGoSearchProvider
from agent_platform.infrastructure.search.tavily import TavilySearchProvider


class SearchUnavailableError(RuntimeError):
    pass


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
    return DuckDuckGoSearchProvider()
