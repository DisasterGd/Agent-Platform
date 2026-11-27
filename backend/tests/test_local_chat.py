"""v0.7.6 本地项目对话测试：local_* 工具（真实落盘断言）+ 注册表注入 + 会话挂接与系统提示词。

设计验收（docs/design-local-projects.md 0.7.6）：Agent 真改一个文件——这里用工具函数直接验证落盘；
allow_write=False 时模型根本没有写工具；归属校验挡住挂错项目。
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_platform.config import settings
from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import User
from agent_platform.repositories.local_projects import LocalProjectRepository
from agent_platform.services.chat_service import ChatService
from agent_platform.tools.builtin.local_fs import (
    local_list_dir,
    local_read_file,
    local_write_file,
)
from agent_platform.tools.builtin.registry import build_default_registry


@pytest.fixture()
def env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """sqlite 内存库 + 两个用户 + 一个注册的本地项目（无模型：llm_api_key 清空）。"""
    monkeypatch.setattr(settings, "llm_api_key", "")  # model=None，构造 ChatService 不建真实客户端
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    user = User(username="dev")
    session.add(user)
    session.commit()

    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "README.md").write_text("# demo", encoding="utf-8")
    repo = LocalProjectRepository(session)
    project = repo.create(user.id, "proj", str(root.resolve()), allow_write=True)

    return {"db": session, "user_id": user.id, "root": root, "project": project, "repo": repo}


# ---------- 工具函数（真实磁盘结果断言） ----------


def test_local_list_dir_reports_entries(env) -> None:
    result = local_list_dir(".", env["root"])
    data = json.loads(result.content)
    assert data["ok"] is True
    names = [e["name"] for e in data["entries"]]
    assert names[0] == "src" and "README.md" in names


def test_local_read_file_returns_text(env) -> None:
    data = json.loads(local_read_file("README.md", env["root"]).content)
    assert data["ok"] is True and data["content"] == "# demo"


def test_local_write_file_persists_to_disk(env) -> None:
    result = local_write_file("src/utils/helpers.py", "def add(a, b):\n    return a + b\n", env["root"])
    data = json.loads(result.content)
    assert data["ok"] is True
    # 指南铁律：必须由程序检查磁盘实际结果，而不是相信返回值
    disk = env["root"] / "src" / "utils" / "helpers.py"
    assert disk.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_local_write_rejects_escape_and_bad_targets(env) -> None:
    # 越界
    data = json.loads(local_write_file("../evil.txt", "x", env["root"]).content)
    assert data["ok"] is False and "越出" in data["error"]
    # .git
    data = json.loads(local_write_file(".git/hooks/x", "x", env["root"]).content)
    assert data["ok"] is False
    # 目标是目录
    data = json.loads(local_write_file("src", "x", env["root"]).content)
    assert data["ok"] is False and "目录" in data["error"]
    # 覆盖已有文件（合法）→ 磁盘被覆盖
    local_write_file("README.md", "# rewritten", env["root"])
    assert (env["root"] / "README.md").read_text(encoding="utf-8") == "# rewritten"


def test_local_read_blocks_binary_and_oversize(env) -> None:
    (env["root"] / "blob.bin").write_bytes(b"\x00\x01\x02" * 100)
    data = json.loads(local_read_file("blob.bin", env["root"]).content)
    assert data["ok"] is False and "二进制" in data["error"]
    big = env["root"] / "big.txt"
    big.write_text("x" * (513 * 1024), encoding="utf-8")
    data = json.loads(local_read_file("big.txt", env["root"]).content)
    assert data["ok"] is False and "过大" in data["error"]


def test_local_list_dir_blocks_escape_via_error_payload(env) -> None:
    """工具不抛异常、如实返回错误 JSON（模型能读到拒绝原因并纠正）。"""
    data = json.loads(local_list_dir("../../", env["root"]).content)
    assert data["ok"] is False and "越出" in data["error"]


# ---------- 注册表注入（allow_write 决定写工具是否存在） ----------


def test_registry_injects_local_tools_by_allow_write(env) -> None:
    root = env["root"]
    with_write = build_default_registry(local_root=root, local_write=True)
    assert {"local_list_dir", "local_read_file", "local_write_file"} <= set(with_write.names())

    readonly = build_default_registry(local_root=root, local_write=False)
    assert {"local_list_dir", "local_read_file"} <= set(readonly.names())
    assert "local_write_file" not in readonly.names()

    plain = build_default_registry()
    assert not any(name.startswith("local_") for name in plain.names())


def test_turn_tools_respect_project_allow_write(env, monkeypatch: pytest.MonkeyPatch) -> None:
    service = ChatService(env["db"], user_id=env["user_id"])
    conversation = service.create_conversation(
        env["user_id"], local_project_id=env["project"].id
    )
    tools = service._turn_tools(conversation)
    assert "local_write_file" in tools.names()

    # 关掉写入开关 → 模型没有写工具
    env["repo"].update(env["project"], allow_write=False)
    tools_ro = service._turn_tools(conversation)
    assert "local_read_file" in tools_ro.names() and "local_write_file" not in tools_ro.names()

    # 普通会话没有 local 工具
    normal = service.create_conversation(env["user_id"])
    assert not any(n.startswith("local_") for n in service._turn_tools(normal).names())


# ---------- 会话挂接：互斥 + 归属校验 + 系统提示词 ----------


def test_create_conversation_binding_rules(env) -> None:
    service = ChatService(env["db"], user_id=env["user_id"])
    conversation = service.create_conversation(env["user_id"], local_project_id=env["project"].id)
    assert conversation.local_project_id == env["project"].id

    # 与工作项目互斥
    from agent_platform.repositories.projects import ProjectRepository

    other = ProjectRepository(env["db"]).create(env["user_id"], "工作项目")
    with pytest.raises(ValueError, match="二选一"):
        service.create_conversation(env["user_id"], project_id=other.id, local_project_id=env["project"].id)

    # 挂到别人的本地项目 → 拒绝
    from agent_platform.infrastructure.database.models import User as UserModel

    stranger = UserModel(username="stranger")
    env["db"].add(stranger)
    env["db"].commit()
    foreign = env["repo"].create(stranger.id, "foreign", str((env["root"] / "x").resolve()))
    with pytest.raises(ValueError, match="不存在"):
        service.create_conversation(env["user_id"], local_project_id=foreign.id)


def test_system_prompt_mentions_local_project(env, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from agent_platform.core.context import build_context

    service = ChatService(env["db"], user_id=env["user_id"])
    conversation = service.create_conversation(env["user_id"], local_project_id=env["project"].id)
    local = service._local_project(conversation)
    prompt = service._local_project_prompt(local)
    assert "本地项目" in prompt and "相对路径" in prompt
    # 关开关后提示词如实反映只读
    env["repo"].update(env["project"], allow_write=False)
    prompt_ro = service._local_project_prompt(service._local_project(conversation))
    assert "只读" in prompt_ro

    # build_context 把 extra_system 放进系统消息
    messages = build_context([("user", "hi")], extra_system=prompt)
    assert messages[0].role == "system" and "本地项目" in messages[0].content
    assert messages[-1].content == "hi"

    # MemoryManager.build_messages 透传 extra_system（异步收尾，直接跑完）
    context, _events = asyncio.run(service.memory.build_messages(
        conversation, [(1, "user", "hi")], extra_system=prompt
    ))
    assert "本地项目" in context[0].content
