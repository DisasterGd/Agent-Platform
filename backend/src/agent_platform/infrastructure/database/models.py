from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agent_platform.infrastructure.database.base import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # v0.4.1 用户自定义分组（默认分组“项目/任务/未分组”由代码归类，不落列）
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # v0.4 会话记忆：超长历史的自动压缩摘要（临时记忆，非持久化知识）
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_covered_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    # 只读关联：供 kind 归类与列表加载（任务会话删除由数据库级联负责）
    tasks: Mapped[list["Task"]] = relationship(viewonly=True, foreign_keys="Task.conversation_id")

    @property
    def kind(self) -> str:
        """会话类别（默认分组“任务”的判定依据）：任务模式产生的会话为 task。"""
        return "task" if self.tasks else "chat"

class Project(Base):
    """v0.4 项目：会话与项目记忆的归属分组。"""
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_user_updated", "user_id", "updated_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="未命名项目")
    description: Mapped[str] = mapped_column(Text, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class ConversationGroup(Base):
    """v0.4.1 用户自定义分组：仅存自定义分组，默认分组（项目/任务/未分组）由代码归类。

    kind: group=根级自定义分组（普通会话可归入）；task=“任务”分区下的子分组
    （仅任务模式会话可归入，任务会话与普通会话不可混用）。
    """
    __tablename__ = "conv_groups"
    __table_args__ = (Index("ix_conv_groups_user_updated", "user_id", "updated_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="未命名分组")
    kind: Mapped[str] = mapped_column(String(16), default="group", server_default="group")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class Memory(Base):
    """v0.4 长期记忆（真正的系统级记忆：存库、可 CRUD、可启用/禁用、上下文自动注入）。

    scope: global（全局，跨项目）/ project（挂在具体项目下）；
    category 由模型归类（用户信息/用户偏好/项目/领域知识/其他）；
    source: explicit（用户要求记住）/ auto（对话自动提炼）/ manual（界面手动添加）。
    """
    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_user_scope", "user_id", "scope"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(16), default="global", server_default="global")
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(50), default="其他", server_default="其他")
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="auto", server_default="auto")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 版本链：同一逻辑消息（重新生成/编辑产生的多个版本）共享 group_id，组内按 variant_index 递增。
    # 首版的 group_id 为自身 id（由仓储在插入后回填），旧数据由迁移脚本回填。
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    variant_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

class Task(Base):
    """v0.3 任务：目标 → 计划步骤 → 执行结果。status:
    awaiting_approval / running / completed / failed / cancelled
    """
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="awaiting_approval", server_default="awaiting_approval")
    # MySQL 的 TEXT 列不支持 DEFAULT：summary/error 仅用 Python 端默认值，建表由迁移管理
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    steps: Mapped[list["TaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.idx"
    )

class TaskStep(Base):
    """任务计划中的单个步骤。status: pending / running / done / failed"""
    __tablename__ = "task_steps"
    __table_args__ = (Index("ix_task_steps_task_idx", "task_id", "idx"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    artifacts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    task: Mapped["Task"] = relationship(back_populates="steps")
