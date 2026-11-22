"""v0.4.1 分组优化与全局搜索测试：sqlite 内存库，不依赖 MySQL 与网络。

覆盖：
- 自定义分组 CRUD；会话“添加至分组 / 移出分组”；删除分组后会话退回默认归类；
- 会话“添加至项目 / 移出项目”（显式 null 才移出，未传字段不改动）；
- 默认分组归类依据：会话 kind（任务模式相关会话 = task）；
- 全局搜索：标题 / 消息正文 / 任务目标 / 项目名 / 分组名命中与范围过滤。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import User
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.messages import MessageRepository
from agent_platform.repositories.tasks import TaskRepository
from agent_platform.services.chat_service import ChatService
from agent_platform.services.group_service import GroupService
from agent_platform.services.project_service import ProjectService
from agent_platform.services.search_service import SearchService


@pytest.fixture()
def db_user() -> tuple[Session, int]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="tester")
    db.add(user)
    db.commit()
    return db, user.id


def test_group_crud_and_membership(db_user: tuple[Session, int]) -> None:
    db, uid = db_user
    groups = GroupService(db)
    chat = ChatService(db)
    convs = ConversationRepository(db)

    g = groups.create(uid, "阅读笔记")
    assert [x.id for x in groups.list(uid)] == [g.id]

    c = chat.create_conversation(uid, "读书交流")
    chat.update_conversation(c.id, group_id=g.id)
    assert convs.get(c.id).group_id == g.id

    # 移出分组
    chat.update_conversation(c.id, group_id=None)
    assert convs.get(c.id).group_id is None

    # 改名
    groups.update(g.id, uid, name="读书笔记")
    assert groups.get(g.id, uid).name == "读书笔记"

    # 删除分组：会话退回默认归类
    chat.update_conversation(c.id, group_id=g.id)
    assert groups.delete(g.id, uid) is True
    assert convs.get(c.id).group_id is None


def test_move_project_sentiment(db_user: tuple[Session, int]) -> None:
    """显式 null 才移出；未传字段不动（标题、置顶保持不变）。"""
    db, uid = db_user
    chat = ChatService(db)
    projects = ProjectService(db)
    convs = ConversationRepository(db)

    p1 = projects.create(uid, "工作")
    p2 = projects.create(uid, "学习")
    c = chat.create_conversation(uid, "周报模板", project_id=p1.id)

    # 只改标题：项目归属不变
    chat.update_conversation(c.id, title="周报模板 v2")
    row = convs.get(c.id)
    assert row.project_id == p1.id and row.title == "周报模板 v2"

    # 换项目 / 移出项目
    chat.update_conversation(c.id, project_id=p2.id)
    assert convs.get(c.id).project_id == p2.id
    chat.update_conversation(c.id, project_id=None)
    assert convs.get(c.id).project_id is None

    with pytest.raises(ValueError):
        chat.update_conversation(c.id, project_id=9999)


def test_conversation_kind_task(db_user: tuple[Session, int]) -> None:
    """任务模式相关会话的 kind 派生自任务表（默认分组“任务”的归类依据）。"""
    db, uid = db_user
    chat = ChatService(db)
    tasks = TaskRepository(db)
    convs = ConversationRepository(db)

    plain = chat.create_conversation(uid, "普通对话")
    assert convs.list_by_user(uid)[0].kind == "chat"

    task_conv = chat.create_conversation(uid, "任务对话")
    tasks.create(uid, "整理资料", conversation_id=task_conv.id)
    kinds = {c.id: c.kind for c in convs.list_by_user(uid)}
    assert kinds[task_conv.id] == "task" and kinds[plain.id] == "chat"


def test_search_scopes_and_snippet(db_user: tuple[Session, int]) -> None:
    db, uid = db_user
    chat = ChatService(db)
    messages = MessageRepository(db)
    tasks = TaskRepository(db)

    conv = chat.create_conversation(uid, "向量数据库选型")
    messages.add(conv.id, "user", "帮我看看 pgvector 和 Milvus 的差异")
    messages.add(conv.id, "assistant", "两者在部署方式与过滤性能上差异明显")
    orphan = chat.create_conversation(uid, "闲聊")

    projects = ProjectService(db)
    p = projects.create(uid, "架构调研", "含向量库对比")
    groups = GroupService(db)
    g = groups.create(uid, "收藏")

    search = SearchService(db)

    all_res = search.search(uid, "Milvus")
    assert [c.id for c, _ in all_res.conversations] == [conv.id]
    assert "两者" in all_res.conversations[0][1]  # 摘要取最后一条消息

    by_goal = search.search(uid, "整理")
    tasks.create(uid, "整理季度资料", conversation_id=orphan.id)
    assert [t.goal for t in search.search(uid, "整理").tasks] == ["整理季度资料"]
    assert by_goal.tasks == []

    by_project = search.search(uid, "架构")
    assert [x.id for x in by_project.projects] == [p.id]
    # 范围过滤：搜项目时不返回会话/任务/分组
    assert not by_project.conversations and not by_project.tasks and not by_project.groups

    by_group = search.search(uid, "收藏")
    assert [x.name for x in by_group.groups] == [g.name]

    # 空关键词 → 全部为空
    empty = search.search(uid, "  ")
    assert not empty.conversations and not empty.tasks and not empty.projects and not empty.groups
