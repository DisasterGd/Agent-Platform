"""构建默认工具注册表。"""
from __future__ import annotations

from agent_platform.tools.builtin.fetch import (
    FETCH_URL_DESCRIPTION,
    FETCH_URL_PARAMETERS,
    fetch_url,
)
from agent_platform.tools.builtin.files import (
    GENERATE_FILE_DESCRIPTION,
    GENERATE_FILE_PARAMETERS,
    generate_file,
)
from agent_platform.tools.builtin.search import (
    WEB_SEARCH_DESCRIPTION,
    WEB_SEARCH_PARAMETERS,
    web_search,
)
from agent_platform.tools.registry import ToolRegistry


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        "web_search", WEB_SEARCH_DESCRIPTION, WEB_SEARCH_PARAMETERS, web_search
    )
    registry.register(
        "fetch_url", FETCH_URL_DESCRIPTION, FETCH_URL_PARAMETERS, fetch_url
    )
    registry.register(
        "generate_file", GENERATE_FILE_DESCRIPTION, GENERATE_FILE_PARAMETERS, generate_file
    )
    return registry
