"""构建默认工具注册表。

按轮注入上下文（沿用 search_knowledge 的闭包模式，工具层保持"不碰数据库"）：
- user_id：会话/任务归属 → 文件类产物落进 per-user 目录（v0.7）；
- knowledge_search：携带 user/project 的知识库检索闭包（v0.6.1）；
- image_config：按用户解析生图角色（cloud 模式各用户各凭据，v0.7）；
- local_root / local_write：本地项目会话注入 local_list_dir/local_read_file（写入还须 allow_write，
  v0.7.6）——root 只来自服务层校验过的注册行，模型给不出 root。
"""
from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

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
from agent_platform.tools.builtin.local_fs import (
    LOCAL_LIST_DESCRIPTION,
    LOCAL_LIST_PARAMETERS,
    LOCAL_READ_DESCRIPTION,
    LOCAL_READ_PARAMETERS,
    LOCAL_WRITE_DESCRIPTION,
    LOCAL_WRITE_PARAMETERS,
    local_list_dir,
    local_read_file,
    local_write_file,
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
    *,
    user_id: int | None = None,
    knowledge_search: Callable[[str, bool], list[dict]] | None = None,
    image_config: Callable[[], dict | None] | None = None,
    local_root: Path | None = None,
    local_write: bool = False,
    search_factory: Callable[[], object] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        "web_search", WEB_SEARCH_DESCRIPTION, WEB_SEARCH_PARAMETERS,
        partial(web_search, provider_factory=search_factory),
    )
    registry.register(
        "fetch_url", FETCH_URL_DESCRIPTION, FETCH_URL_PARAMETERS, fetch_url
    )
    registry.register(
        "generate_file", GENERATE_FILE_DESCRIPTION, GENERATE_FILE_PARAMETERS,
        partial(generate_file, user_id=user_id),
    )
    # v0.5：文本/代码文件与压缩包
    registry.register(
        "write_file", WRITE_FILE_DESCRIPTION, WRITE_FILE_PARAMETERS,
        partial(write_file, user_id=user_id),
    )
    registry.register(
        "create_zip", CREATE_ZIP_DESCRIPTION, CREATE_ZIP_PARAMETERS,
        partial(create_zip, user_id=user_id),
    )
    # v0.6：图像生成（走"生图角色"配置的供应商与模型，产物进资料库）
    registry.register(
        "generate_image", GENERATE_IMAGE_DESCRIPTION, GENERATE_IMAGE_PARAMETERS,
        partial(generate_image_tool, user_id=user_id, image_config=image_config),
    )
    # v0.6.1：知识库检索（闭包携带 user/project 上下文，由 Chat/Task 服务按当轮注入）
    if knowledge_search is not None:
        registry.register(
            "search_knowledge", SEARCH_KNOWLEDGE_DESCRIPTION, SEARCH_KNOWLEDGE_PARAMETERS,
            build_search_knowledge(knowledge_search),
        )
    # v0.7.6：本地项目（真实目录）——root 由服务层注入；写工具只在项目 allow_write 时存在
    if local_root is not None:
        registry.register(
            "local_list_dir", LOCAL_LIST_DESCRIPTION, LOCAL_LIST_PARAMETERS,
            partial(local_list_dir, root=local_root),
        )
        registry.register(
            "local_read_file", LOCAL_READ_DESCRIPTION, LOCAL_READ_PARAMETERS,
            partial(local_read_file, root=local_root),
        )
        if local_write:
            registry.register(
                "local_write_file", LOCAL_WRITE_DESCRIPTION, LOCAL_WRITE_PARAMETERS,
                partial(local_write_file, root=local_root),
            )
    return registry
