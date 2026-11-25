"""构建默认工具注册表。"""
from __future__ import annotations

from collections.abc import Callable

from agent_platform.tools.builtin.archive import (
    CREATE_ZIP_DESCRIPTION,
    CREATE_ZIP_PARAMETERS,
    create_zip,
)
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
from agent_platform.tools.builtin.images import (
    GENERATE_IMAGE_DESCRIPTION,
    GENERATE_IMAGE_PARAMETERS,
    generate_image_tool,
)
from agent_platform.tools.builtin.knowledge_search import (
    SEARCH_KNOWLEDGE_DESCRIPTION,
    SEARCH_KNOWLEDGE_PARAMETERS,
    build_search_knowledge,
)
from agent_platform.tools.builtin.search import (
    WEB_SEARCH_DESCRIPTION,
    WEB_SEARCH_PARAMETERS,
    web_search,
)
from agent_platform.tools.builtin.textfile import (
    WRITE_FILE_DESCRIPTION,
    WRITE_FILE_PARAMETERS,
    write_file,
)
from agent_platform.tools.registry import ToolRegistry


def build_default_registry(
    knowledge_search: Callable[[str, bool], list[dict]] | None = None,
) -> ToolRegistry:
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
    # v0.5：文本/代码文件与压缩包
    registry.register(
        "write_file", WRITE_FILE_DESCRIPTION, WRITE_FILE_PARAMETERS, write_file
    )
    registry.register(
        "create_zip", CREATE_ZIP_DESCRIPTION, CREATE_ZIP_PARAMETERS, create_zip
    )
    # v0.6：图像生成（走“生图角色”配置的供应商与模型，产物进资料库）
    registry.register(
        "generate_image", GENERATE_IMAGE_DESCRIPTION, GENERATE_IMAGE_PARAMETERS, generate_image_tool
    )
    # v0.6.1：知识库检索（闭包携带 user/project 上下文，由 Chat/Task 服务按当轮注入）
    if knowledge_search is not None:
        registry.register(
            "search_knowledge", SEARCH_KNOWLEDGE_DESCRIPTION, SEARCH_KNOWLEDGE_PARAMETERS,
            build_search_knowledge(knowledge_search),
        )
    return registry
