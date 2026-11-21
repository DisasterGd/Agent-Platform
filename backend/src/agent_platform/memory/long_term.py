"""长期记忆（v0.4）：全局记忆与项目记忆，真正的系统级记忆。

与 CLAUDE.md 这类"写进静态文档的假记忆"的区别：
- 存储在数据库 memories 表，用户可在设置界面查看/编辑/禁用/删除；
- 由代码在每次构建上下文时按作用域（全局 + 当前项目）检索并注入系统提示词；
- 每轮对话结束后由模型自动提炼原子化记忆；用户显式"记住…"的要求优先落库并标记来源。

类别（用户信息/用户偏好/项目/领域知识/其他）由大模型自行归类，不预设固定枚举。
"""
from __future__ import annotations

import json
import re

from agent_platform.config import settings
from agent_platform.infrastructure.database.models import Memory
from agent_platform.models.base import ChatMessage
from agent_platform.repositories.memories import MemoryRepository

EXTRACT_SYSTEM_PROMPT = (
    "你是记忆提取器。阅读本轮对话（用户消息与助手回复），提取值得**长期记住**的信息。"
    "只提取稳定、可复用的事实：用户身份信息、偏好与习惯、做过的决定、项目背景与约定、"
    "用户熟悉的领域；不要保存：一次性任务内容、临时提问、模型自己的观点与推测。"
    '每条输出形如 {"category": "用户信息|用户偏好|项目|领域知识|其他之一，也可自行命名", '
    '"title": "不超过20字的短标签", "content": "完整、可独立理解的句子", "importance": 1到5}。'
    "与已有记忆标题相同的，输出更新后的完整条目。最多 3 条；没有值得记的输出 []。"
    "只输出 JSON 数组，不要其它文字。"
)

EXPLICIT_MARKERS = ("记住", "记一下", "帮我记", "别忘了", "remember", "以后都", "从现在开始")

MAX_ITEMS_PER_TURN = 3


def looks_explicit(user_text: str) -> bool:
    lowered = user_text.lower()
    return any(marker in lowered for marker in EXPLICIT_MARKERS)


def parse_memories(text: str) -> list[dict]:
    """从模型输出中提取记忆 JSON 数组；无法解析返回空列表。"""
    match = re.search(r"\[[\s\S]*\]", text or "")
    if not match:
        return []
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    items: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content", "")).split())
        if not content:
            continue
        title = " ".join(str(item.get("title", "")).split())[:60]
        category = " ".join(str(item.get("category", "")).split())[:50] or "其他"
        try:
            importance = int(item.get("importance", 2))
        except (TypeError, ValueError):
            importance = 2
        items.append({"category": category, "title": title or content[:20], "content": content[:500], "importance": importance})
    return items[:MAX_ITEMS_PER_TURN]


def format_block(memories: list[Memory], *, budget: int | None = None, project_name: str = "") -> str:
    """把记忆列表渲染为注入系统提示词的文本块（按类别分组，先全局后项目，字数封顶）。"""
    budget = budget if budget is not None else settings.memory_char_budget
    lines: list[str] = []
    used = 0

    def emit(group: list[Memory], header: str) -> None:
        nonlocal used
        if not group:
            return
        block: list[str] = [header]
        by_category: dict[str, list[Memory]] = {}
        for m in group:
            by_category.setdefault(m.category or "其他", []).append(m)
        for category, rows in by_category.items():
            block.append(f"〔{category}〕")
            for m in rows:
                text = f"- {m.title}：{m.content}" if m.title else f"- {m.content}"
                if used + len("\n".join(block)) + len(text) > budget:
                    block.append("…（更多记忆已在记忆设置中管理）")
                    break
                block.append(text)
            if "…（更多记忆已在记忆设置中管理）" in block:
                break
        chunk = "\n".join(block)
        if used + len(chunk) > budget:
            return
        lines.append(chunk)
        used += len(chunk) + 1

    emit([m for m in memories if m.scope == "global"], "全局记忆：")
    emit([m for m in memories if m.scope == "project"], f"项目记忆（{project_name or '当前项目'}）：")
    return "\n".join(lines)


class LongTermMemory:
    def __init__(self, model, repo: MemoryRepository) -> None:
        self.model = model
        self.repo = repo

    async def extract_and_save(
        self,
        user_id: int,
        project_id: int | None,
        user_text: str,
        reply: str,
    ) -> list[dict]:
        """从本轮对话提炼并写入记忆；返回写入摘要（供事件/UI 展示）。异常一律吞掉不影响主流程。"""
        if self.model is None:
            return []
        explicit = looks_explicit(user_text)
        existing = self.repo.list(user_id, enabled_only=True)
        existing_titles = "、".join(m.title for m in existing[-30:] if m.title)
        prompt = (
            f"已有记忆标题：{existing_titles or '（无）'}\n\n"
            f"用户消息：\n{user_text[:2000]}\n\n助手回复：\n{reply[:2000]}"
        )
        if explicit:
            prompt = "用户在本轮明确提出了记忆要求，其内容必须提取（importance 取 5）。\n\n" + prompt
        try:
            text = await self.model.complete(
                [
                    ChatMessage(role="system", content=EXTRACT_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=prompt),
                ]
            )
        except Exception:  # noqa: BLE001 — 记忆提炼失败不影响对话
            return []
        saved: list[dict] = []
        for item in parse_memories(text):
            if item["importance"] < (3 if explicit else 2):
                continue
            # 标题相同视为同一条记忆：更新内容而非堆重复。
            # （项目记忆目前通过设置界面管理；自动提炼默认写入全局）
            scope = "global"
            source = "explicit" if explicit else "auto"
            existing_row = self.repo.find_similar(user_id, scope, None, item["title"])
            if existing_row is None:
                memory = self.repo.create(
                    user_id,
                    content=item["content"],
                    scope=scope,
                    category=item["category"],
                    title=item["title"],
                    source=source,
                )
            else:
                memory = self.repo.update(
                    existing_row.id,
                    content=item["content"],
                    category=item["category"],
                    source=source if explicit else None,
                )
            if memory is not None:
                saved.append({"title": memory.title, "scope": scope, "category": memory.category, "source": memory.source})
        return saved
