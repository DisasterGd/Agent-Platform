"""任务业务用例（v0.3 任务规划与执行）。

状态机：awaiting_approval →（用户确认）running → completed / failed / cancelled。
计划由 Planner 生成，用户可先编辑再执行；执行由 Runner 驱动并逐步落库；
任务完成后把「目标 + 最终总结」写入会话（无会话则懒创建），保证聊天上下文连续。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_platform.core.events import Event, error, plan_created, task_completed
from agent_platform.core.planner import Planner
from agent_platform.core.runner import Runner
from agent_platform.infrastructure.database.models import Conversation, Task
from agent_platform.models.base import ChatMessage
from agent_platform.models.factory import create_model
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.messages import MessageRepository
from agent_platform.repositories.tasks import TaskRepository
from agent_platform.services.chat_service import ChatService
from agent_platform.tools.builtin.registry import build_default_registry

SUMMARY_SYSTEM_PROMPT = "你负责任务收尾：结合目标与各步骤结果，输出一段简洁完整的中文最终答复，不要提及内部步骤结构。"

EXECUTABLE_STATUSES = ("awaiting_approval", "failed")


class TaskService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.tasks = TaskRepository(db)
        self.conversations = ConversationRepository(db)
        self.messages = MessageRepository(db)
        self.model = create_model()
        self.tools = build_default_registry()
        self.planner = Planner(self.model)
        self.chat = ChatService(db)

    async def create_task(
        self, user_id: int, goal: str, conversation_id: int | None = None
    ) -> Task:
        goal = goal.strip()
        task = self.tasks.create(user_id, goal, conversation_id)
        steps = await self.planner.plan(goal)
        self.tasks.replace_steps(task.id, [{"title": s.title, "detail": s.detail} for s in steps])
        return self.tasks.get(task.id) or task

    def get_task(self, task_id: int, user_id: int) -> Task | None:
        task = self.tasks.get(task_id)
        if task is None or task.user_id != user_id:
            return None
        return task

    def list_by_conversation(self, conversation_id: int, user_id: int) -> list[Task]:
        return [t for t in self.tasks.list_by_conversation(conversation_id) if t.user_id == user_id]

    def revise(self, task_id: int, user_id: int, steps: list[dict[str, Any]]) -> Task | None:
        """审阅阶段编辑计划：整体替换步骤。"""
        task = self.get_task(task_id, user_id)
        if task is None or task.status != "awaiting_approval":
            return task
        cleaned = [
            {"title": str(s.get("title", "")).strip(), "detail": str(s.get("detail", "")).strip()}
            for s in steps
            if str(s.get("title", "")).strip() or str(s.get("detail", "")).strip()
        ][:6]
        if not cleaned:
            return task
        self.tasks.replace_steps(task_id, cleaned)
        return self.tasks.get(task_id)

    def cancel(self, task_id: int, user_id: int) -> Task | None:
        task = self.get_task(task_id, user_id)
        if task is None:
            return None
        if task.status in ("awaiting_approval", "running"):
            self.tasks.set_status(task_id, "cancelled")
        return self.tasks.get(task_id)

    async def execute(self, task_id: int, user_id: int) -> AsyncIterator[Event]:
        task = self.get_task(task_id, user_id)
        if task is None:
            yield error("任务不存在")
            return
        if task.status not in EXECUTABLE_STATUSES:
            yield error(f"任务当前状态（{task.status}）不可执行")
            return

        steps = [{"index": s.idx, "title": s.title, "detail": s.detail, "status": "pending"} for s in task.steps]
        if not steps:
            yield error("任务没有可执行的步骤")
            return

        self.tasks.set_status(task_id, "running")
        self.tasks.reset_steps(task_id)
        yield plan_created(steps)

        runner = Runner(self.model, tools=self.tools)
        async for event in runner.run(task.goal, steps):
            # 取消检查：任何时刻把状态改为 cancelled 都会在下一个事件生效
            if self._is_cancelled(task_id):
                yield task_completed({"status": "cancelled", "summary": ""})
                return
            self._persist_step_event(task_id, event)
            yield event
            if event.type == "step_failed":
                self.tasks.set_status(task_id, "failed", error=event.data.get("error", ""))
                yield task_completed({"status": "failed", "summary": "", "error": event.data.get("error", "")})
                return

        summary = await self._compose_summary(task.goal, runner.outcomes)
        self.tasks.set_status(task_id, "completed", summary=summary)
        conversation_id = await self._finalize_conversation(task, summary)
        yield task_completed(
            {"status": "completed", "summary": summary, "conversation_id": conversation_id}
        )

    def _is_cancelled(self, task_id: int) -> bool:
        status = self.db.execute(select(Task.status).where(Task.id == task_id)).scalar_one_or_none()
        return status == "cancelled"

    def _persist_step_event(self, task_id: int, event: Event) -> None:
        if event.type == "step_started":
            self.tasks.update_step(task_id, event.data["index"], "running")
        elif event.type == "step_completed":
            self.tasks.update_step(
                task_id, event.data["index"], "done",
                summary=event.data.get("summary", ""), artifacts=event.data.get("artifacts"),
            )
        elif event.type == "step_failed":
            self.tasks.update_step(task_id, event.data["index"], "failed", error=event.data.get("error", ""))

    async def _compose_summary(self, goal: str, outcomes: list) -> str:
        """程序汇总：优先让模型整合；无模型或失败时按步骤拼接。"""
        if not outcomes:
            return ""
        if self.model is not None and len(outcomes) > 1:
            lines = [f"目标：{goal}"]
            for o in outcomes:
                lines.append(f"{o.index + 1}. {o.title}：{o.summary[:1500]}")
            text = ""
            try:
                text = await self.model.complete(
                    [
                        ChatMessage(role="system", content=SUMMARY_SYSTEM_PROMPT),
                        ChatMessage(role="user", content="\n".join(lines)),
                    ]
                )
                text = text.strip()
            except Exception:  # noqa: BLE001 — 汇总失败退回拼接
                text = ""
            if text:
                return text
        if len(outcomes) == 1:
            return outcomes[0].summary
        parts = [f"已完成目标：{goal}\n"]
        for o in outcomes:
            parts.append(f"【{o.title}】\n{o.summary}\n")
        return "\n".join(parts).strip()

    async def _finalize_conversation(self, task: Task, summary: str) -> int:
        """把任务结果落到会话：无会话则懒创建；写入目标与最终总结；补标题。"""
        conversation: Conversation | None = (
            self.conversations.get(task.conversation_id) if task.conversation_id else None
        )
        if conversation is None or conversation.user_id != task.user_id:
            conversation = self.conversations.create(task.user_id, "新会话")
            self.tasks.set_conversation(task.id, conversation.id)
        self.messages.add(conversation.id, "user", task.goal)
        self.messages.add(conversation.id, "assistant", summary)
        self.conversations.touch(conversation.id)
        await self.chat.ensure_title(conversation.id, task.goal)
        return conversation.id
