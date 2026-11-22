"""任务与步骤数据读写。"""
from __future__ import annotations

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from agent_platform.infrastructure.database.models import Task, TaskStep


class TaskRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self, user_id: int, goal: str, conversation_id: int | None = None, project_id: int | None = None
    ) -> Task:
        task = Task(user_id=user_id, goal=goal, conversation_id=conversation_id, project_id=project_id)
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get(self, task_id: int) -> Task | None:
        stmt = (
            select(Task)
            .options(selectinload(Task.steps))
            .where(Task.id == task_id)
        )
        return self.db.scalars(stmt).first()

    def list_by_conversation(self, conversation_id: int) -> list[Task]:
        stmt = (
            select(Task)
            .options(selectinload(Task.steps))
            .where(Task.conversation_id == conversation_id)
            .order_by(Task.created_at.desc(), Task.id.desc())
        )
        return list(self.db.scalars(stmt))

    def list_by_user(self, user_id: int, limit: int | None = None) -> list[Task]:
        """v0.4.1 任务界面：该用户的全部任务（含未绑定会话的待审阅任务）。"""
        stmt = (
            select(Task)
            .options(selectinload(Task.steps))
            .where(Task.user_id == user_id)
            .order_by(Task.updated_at.desc(), Task.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.db.scalars(stmt))

    def search(self, user_id: int, keyword: str, limit: int = 20) -> list[Task]:
        """目标或最终总结命中关键词（搜索弹窗“任务”范围）。"""
        like = f"%{keyword}%"
        stmt = (
            select(Task)
            .options(selectinload(Task.steps))
            .where(Task.user_id == user_id, or_(Task.goal.like(like), Task.summary.like(like)))
            .order_by(Task.updated_at.desc(), Task.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def replace_steps(self, task_id: int, steps: list[dict]) -> list[TaskStep]:
        """整体替换计划（仅在 awaiting_approval 阶段允许）。"""
        self.db.execute(delete(TaskStep).where(TaskStep.task_id == task_id))
        rows = [
            TaskStep(
                task_id=task_id,
                idx=i,
                title=str(s.get("title", ""))[:200],
                detail=str(s.get("detail", "")),
                status="pending",
            )
            for i, s in enumerate(steps)
        ]
        self.db.add_all(rows)
        self.db.commit()
        # sessionmaker 的 expire_on_commit=False：Core 删除+插入不会刷新已缓存的关系集合，
        # 显式过期一次，保证随后的 get/查询从数据库重新加载步骤。
        self.db.expire_all()
        return rows

    def set_status(self, task_id: int, status: str, summary: str | None = None, error: str | None = None) -> None:
        task = self.db.get(Task, task_id)
        if task is None:
            return
        task.status = status
        if summary is not None:
            task.summary = summary
        if error is not None:
            task.error = error
        self.db.commit()

    def set_conversation(self, task_id: int, conversation_id: int) -> None:
        task = self.db.get(Task, task_id)
        if task is not None:
            task.conversation_id = conversation_id
            self.db.commit()

    def get_step(self, task_id: int, idx: int) -> TaskStep | None:
        stmt = select(TaskStep).where(TaskStep.task_id == task_id, TaskStep.idx == idx)
        return self.db.scalars(stmt).first()

    def update_step(
        self,
        task_id: int,
        idx: int,
        status: str,
        summary: str | None = None,
        error: str | None = None,
        artifacts: list | None = None,
    ) -> None:
        step = self.get_step(task_id, idx)
        if step is None:
            return
        step.status = status
        if summary is not None:
            step.summary = summary
        if error is not None:
            step.error = error
        if artifacts is not None:
            step.artifacts = artifacts
        self.db.commit()

    def delete(self, task_id: int) -> bool:
        """删除任务记录（步骤一并删除）；不影响任务已产生的会话。"""
        task = self.db.get(Task, task_id)
        if task is None:
            return False
        self.db.execute(delete(TaskStep).where(TaskStep.task_id == task_id))
        self.db.delete(task)
        self.db.commit()
        return True

    def reset_steps(self, task_id: int) -> None:
        """重试前把步骤恢复为 pending。"""
        for row in self.db.scalars(select(TaskStep).where(TaskStep.task_id == task_id)):
            row.status = "pending"
            row.summary = ""
            row.error = ""
            row.artifacts = None
        self.db.commit()
