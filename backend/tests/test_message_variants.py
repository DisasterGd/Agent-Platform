"""消息版本链（重新生成保留历史版本）的仓储测试：sqlite 内存库，不依赖 MySQL。"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import Conversation, User
from agent_platform.repositories.messages import MessageRepository


@pytest.fixture()
def repo() -> MessageRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="tester")
    db.add(user)
    db.flush()
    db.add(Conversation(id=1, user_id=user.id, title="t"))
    db.commit()
    return MessageRepository(db)


def test_add_starts_own_group(repo: MessageRepository) -> None:
    msg = repo.add(1, "user", "你好")
    assert msg.group_id == msg.id
    assert msg.variant_index == 0


def test_variant_appends_without_deleting(repo: MessageRepository) -> None:
    first = repo.add(1, "assistant", "答案 v0")
    idx = repo.next_variant_index(first.group_id)
    assert idx == 1
    second = repo.add(1, "assistant", "答案 v1", group_id=first.group_id, variant_index=idx)

    rows = repo.list_by_conversation(1)
    assert len(rows) == 2  # 旧版本保留
    assert second.group_id == first.group_id
    assert second.variant_index == 1


def test_list_active_keeps_latest_per_group(repo: MessageRepository) -> None:
    u = repo.add(1, "user", "问题")
    a0 = repo.add(1, "assistant", "旧答案")
    repo.add(1, "assistant", "新答案", group_id=a0.group_id, variant_index=1)
    repo.add(1, "user", "第二问")

    active = repo.list_active_by_conversation(1)
    contents = [(m.role, m.content) for m in active]
    assert contents == [("user", "问题"), ("assistant", "新答案"), ("user", "第二问")]
    assert active[0].id == u.id


def test_next_variant_index_increments(repo: MessageRepository) -> None:
    a = repo.add(1, "assistant", "v0")
    assert repo.next_variant_index(a.group_id) == 1
    repo.add(1, "assistant", "v1", group_id=a.group_id, variant_index=1)
    assert repo.next_variant_index(a.group_id) == 2
