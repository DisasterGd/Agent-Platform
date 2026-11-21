"""v0.4 记忆系统核心测试：压缩、提炼、归类、注入封顶（sqlite，不依赖 MySQL/网络）。"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.core.context import MEMORY_HEADER, build_context
from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import Conversation, User
from agent_platform.memory.conversation import ConversationMemory
from agent_platform.memory.long_term import (
    LongTermMemory,
    format_block,
    looks_explicit,
    parse_memories,
)
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.memories import MemoryRepository
from agent_platform.repositories.messages import MessageRepository


class EchoModel:
    """complete 固定返回预设文本；记录每次收到的提示词。"""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.prompts: list[str] = []

    async def complete(self, messages) -> str:
        self.prompts.append(messages[-1].content)
        return self.text

    async def stream(self, messages) -> AsyncIterator[str]:  # pragma: no cover
        yield ""


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    user = User(username="tester")
    session.add(user)
    session.flush()
    session.add(Conversation(id=1, user_id=user.id, title="t"))
    session.commit()
    yield session
    session.close()


# ---------- 解析与显式识别 ----------

def test_parse_memories_valid_and_junk() -> None:
    raw = '结果：[{"category":"用户偏好","title":"爱吃辣","content":"用户明确表示喜欢吃辣。","importance":4}]'
    items = parse_memories(raw)
    assert len(items) == 1 and items[0]["category"] == "用户偏好"
    assert parse_memories("没有 JSON") == []
    assert parse_memories('[{"content": ""}, {"content": "有效一条"}]') == [
        {"category": "其他", "title": "有效一条", "content": "有效一条", "importance": 2}
    ]


def test_parse_memories_caps_items() -> None:
    import json

    raw = json.dumps([{"content": f"事实{i}", "importance": 5} for i in range(10)])
    assert len(parse_memories(raw)) == 3


def test_looks_explicit() -> None:
    assert looks_explicit("请记住，我的项目预算是 5 万")
    assert looks_explicit("以后都请用中文回答")
    assert not looks_explicit("今天天气怎么样")


# ---------- 会话历史压缩 ----------

def test_ensure_summary_compresses_over_budget(db: Session) -> None:
    messages = MessageRepository(db)
    for i in range(10):
        messages.add(1, "user" if i % 2 == 0 else "assistant", "内容" * 1500)  # 远超阈值
    entries = [(m.id, m.role, m.content) for m in messages.list_active_by_conversation(1)]

    model = EchoModel(text="这是早期对话的摘要。")
    convo = ConversationMemory(model, messages, ConversationRepository(db))
    compressed = asyncio.run(convo.ensure_summary(db.get(Conversation, 1), entries))

    conv = db.get(Conversation, 1)
    assert compressed == len(entries) - settings.context_keep_recent
    assert conv.summary == "这是早期对话的摘要。"
    assert conv.summary_covered_id == entries[compressed - 1][0]
    # 再次调用不重复压缩
    assert asyncio.run(convo.ensure_summary(conv, entries)) == 0


def test_ensure_summary_skips_small_or_no_model(db: Session) -> None:
    messages = MessageRepository(db)
    messages.add(1, "user", "短")
    entries = [(m.id, m.role, m.content) for m in messages.list_active_by_conversation(1)]
    model = EchoModel(text="不该被调用")
    convo = ConversationMemory(model, messages, ConversationRepository(db))
    assert asyncio.run(convo.ensure_summary(db.get(Conversation, 1), entries)) == 0
    assert model.prompts == []
    assert asyncio.run(ConversationMemory(None, messages, ConversationRepository(db)).ensure_summary(
        db.get(Conversation, 1), entries
    )) == 0


# ---------- 长期记忆：提炼保存 / 去重更新 ----------

def test_extract_and_save_creates_and_updates(db: Session) -> None:
    repo = MemoryRepository(db)
    user_id = db.get(Conversation, 1).user_id
    model = EchoModel(
        text='[{"category":"用户信息","title":"职业","content":"用户是一名软件工程师。","importance":4}]'
    )
    ltm = LongTermMemory(model, repo)
    saved = asyncio.run(ltm.extract_and_save(user_id, None, "随便聊聊", "好的"))
    assert len(saved) == 1 and saved[0]["source"] == "auto"

    # 同标题再来一条 → 更新而非重复
    model.text = '[{"category":"用户信息","title":"职业","content":"用户是一名后端软件工程师，偏 Python。","importance":4}]'
    saved2 = asyncio.run(ltm.extract_and_save(user_id, None, "请记住我是后端", "收到"))
    rows = repo.list(user_id)
    assert len(rows) == 1
    assert rows[0].content == "用户是一名后端软件工程师，偏 Python。"
    assert rows[0].source == "explicit"  # 显式要求升级来源标记
    assert saved2[0]["source"] == "explicit"
    # 提示词里带上了显式标记与已有标题
    assert "明确提出了记忆要求" in model.prompts[-1]


def test_extract_ignores_low_importance(db: Session) -> None:
    repo = MemoryRepository(db)
    model = EchoModel(text='[{"title":"小事","content":"用户今天问了天气","importance":1}]')
    ltm = LongTermMemory(model, repo)
    assert asyncio.run(ltm.extract_and_save(1, None, "今天天气如何", "晴")) == []
    assert repo.list(1) == []


# ---------- 注入：作用域过滤 + 分组 + 封顶 ----------

def test_format_block_grouping_and_budget(db: Session) -> None:
    repo = MemoryRepository(db)
    user_id = db.get(Conversation, 1).user_id
    repo.create(user_id, content="全局事实一", scope="global", category="用户信息", title="事实一")
    repo.create(user_id, content="全局事实二", scope="global", category="其他", title="事实二")
    memories = repo.list_for_context(user_id, None)
    block = format_block(memories, budget=100000)
    assert "全局记忆：" in block and "〔用户信息〕" in block

    tight = format_block(memories, budget=30)
    assert tight == "" or len(tight) <= 60  # 封顶：要么装不下返回空，要么带省略提示

    rows = format_block(memories)
    assert MEMORY_HEADER not in rows  # header 由 context 层添加


def test_build_context_places_summary_and_memory(db: Session) -> None:
    ctx = build_context(
        [("user", "继续")],
        summary="前文摘要内容",
        memory_block="- 用户喜欢简洁回答",
    )
    assert ctx[0].role == "system" and MEMORY_HEADER in ctx[0].content
    assert ctx[1].content.startswith("【前文摘要】")
    assert ctx[2].content == "继续"
