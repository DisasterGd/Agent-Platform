"""任务服务（会话绑定与留痕）测试：sqlite 内存库，不依赖 MySQL 与网络。

覆盖 v0.3.1 修复：
- 执行开始即创建/绑定会话（plan_created 携带 conversation_id）；
- 首次执行把目标写入会话（用户消息）；
- 任务失败时会话里仍留下失败记录（此前失败任务“消失、无任何记录”）。
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_platform.core.planner import Planner
from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import User
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.messages import MessageRepository
from agent_platform.repositories.tasks import TaskRepository
from agent_platform.services.task_service import TaskService


class EmptyModel:
    """任何步骤都产出空文本 → 触发“执行没有产出任何内容”的失败路径。"""

    async def stream(self, messages):
        return
        yield  # pragma: no cover

    async def complete(self, messages) -> str:
        return ""

    async def stream_with_tools(self, messages, tools):
        from agent_platform.models.base import StreamEvent

        yield StreamEvent(kind="text", text="")

    async def complete_with_tools(self, messages, tools):  # pragma: no cover
        from agent_platform.models.base import ModelResponse

        return ModelResponse(content="")


def _make_service() -> tuple[TaskService, Session, int]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="tester")
    db.add(user)
    db.commit()
    service = TaskService(db)
    # 离线：不触网（模型改由用例逐个指定）
    service.model = None
    service.planner = Planner(None)
    service.chat.model = None
    return service, db, user.id


@pytest.fixture()
def service_db():
    service, db, user_id = _make_service()
    yield service, db, user_id
    db.close()


async def _collect(agen) -> list:
    return [e async for e in agen]


def test_execute_binds_conversation_at_start_and_records_result(service_db) -> None:
    service, db, user_id = service_db
    task = asyncio.run(service.create_task(user_id, "整理我的截图并写一份 README 说明"))
    assert task.conversation_id is None  # 创建阶段还没会话

    events = asyncio.run(_collect(service.execute(task.id, user_id)))
    plan = next(e for e in events if e.type == "plan_created")
    conv_id = plan.data.get("conversation_id")
    assert conv_id is not None, "执行开始就应该绑定/创建会话"

    # 目标作为用户消息、总结作为助手消息都落在会话里
    msgs = MessageRepository(db).list_by_conversation(conv_id)
    roles = [m.role for m in msgs]
    assert roles == ["user", "assistant"]
    assert msgs[0].content == task.goal

    # 标题从内容截取，而不是停留在“新会话”
    conv = ConversationRepository(db).get(conv_id)
    assert conv is not None and conv.title not in ("", "新会话")

    done = TaskRepository(db).get(task.id)
    assert done is not None and done.status == "completed"


def test_failed_task_leaves_record_in_conversation(service_db) -> None:
    service, db, user_id = service_db
    task = asyncio.run(service.create_task(user_id, "生成一份安全教学文档"))
    service.model = EmptyModel()  # 空产出 → 步骤失败

    events = asyncio.run(_collect(service.execute(task.id, user_id)))
    assert any(e.type == "step_failed" for e in events)
    completed = next(e for e in events if e.type == "task_completed")
    assert completed.data["status"] == "failed"
    conv_id = completed.data.get("conversation_id")
    assert conv_id is not None, "失败也必须已绑定会话（否则刷新后卡片无处恢复）"

    msgs = MessageRepository(db).list_by_conversation(conv_id)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert "任务执行失败" in msgs[1].content
    assert "执行没有产出任何内容" in msgs[1].content
