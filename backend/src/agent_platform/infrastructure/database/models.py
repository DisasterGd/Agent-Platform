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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agent_platform.infrastructure.database.base import Base


class User(Base):
    """用户（v0.7 扩列）：email 是 cloud 模式的登录身份；local 模式仍只有 dev 行（email 为 NULL）。

    无密码方案：没有 password 列，登录凭证是 auth_codes 验证码 + sessions 会话。
    status: active / disabled（停用即时撤销全部 session，见 admin 路由）。
    """
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    """v0.7 登录会话（服务端 session 表 + cookie，不用 JWT：可撤销、封号即时生效）。

    cookie 里只放随机 token（secrets.token_urlsafe），库里存其 SHA-256——拖库不泄露可用令牌。
    30 天滑动续期：resolve 时过期临近则顺延 expires_at。
    """
    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuthCode(Base):
    """v0.7 登录/注册一次性验证码：库里只存 SHA-256 哈希，10 分钟有效，错 5 次作废。

    注册登录合一：邮箱没注册过，验证通过即建号（验证码即凭证）。
    行同时承担频控依据（按 email/IP 统计 created_at 窗口内的行数）。
    """
    __tablename__ = "auth_codes"
    __table_args__ = (Index("ix_auth_codes_email_created", "email", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(24), default="login", server_default="login")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_ip: Mapped[str] = mapped_column(String(64), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserSetting(Base):
    """v0.7 个人设置（cloud 模式）：等价 settings.json v3 的 JSON 一列，按 user 隔离。

    local 模式不使用本表（仍走 settings.json 单例文件，行为零变化）。
    结构与 settings_service 的 v3 布局完全一致（profiles+roles+memory_enabled），
    API Key 仍经 secret_store 加密后存进 JSON，永不回显。
    """
    __tablename__ = "user_settings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DeploymentSetting(Base):
    """v0.8 部署级配置（配置界面化）：全站唯一的运行期可变配置，按 name 存 JSON。

    与 UserSetting 的分界：那是"每用户"的（模型凭据/记忆开关），这是"每部署"的
    （邮件通道、搜索源）——云端只有平台管理员可写，本地模式即本机用户。
    敏感字段（SMTP 密码/搜索 Key）入库前经 secret_store 加密（按 auth_mode 选后端），
    HTTP 响应永不回显。.env 仍是兜底：某字段未在库中配置时回退 .env 值。
    """
    __tablename__ = "deployment_settings"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # v0.7.4 本地项目：与 project_id 互斥（服务层建号时校验），FK 级联置空——注销项目不丢会话
    local_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("local_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
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


class LocalProject(Base):
    """v0.7.4 本地项目：用户机器上真实目录的注册记录（伪编辑器，仅 local 模式暴露路由）。

    root_path 一经注册不再修改——磁盘即事实来源；删除注册只删本行、绝不动磁盘文件，
    关联会话的 local_project_id 由数据库置空（会话保留，只是脱离项目）。
    与 v0.4 Project（归档容器）互不混用：会话二者取其一。
    """
    __tablename__ = "local_projects"
    __table_args__ = (
        UniqueConstraint("user_id", "root_path", name="uq_local_projects_user_root"),
        Index("ix_local_projects_user_updated", "user_id", "updated_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    root_path: Mapped[str] = mapped_column(String(500))
    # 项目级写入开关（v0.7.6 工具注入用）：False=Agent 只读（根本不给写工具）
    allow_write: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class FileAsset(Base):
    """v0.5 资料库条目：磁盘上每个上传/生成文件在库里的唯一记录。

    category: uploads（用户上传）/ generated（Agent 产出）
    kind: 见 infrastructure/filetypes（code/document/image/archive/audio/video/other），
          资料库页签与筛选按它归类，落库避免每次重新猜。
    source: upload（聊天附件）/ chat（聊天中生成）/ task（任务步骤生成）/ library（存量扫描登记）
    stored_name = 磁盘真实文件名（v0.7 起落在 data/{category}/u{user_id}/ 下）；重命名只改 filename，
    因此历史消息里的旧下载链接一直有效。
    conversation_id 不建外键：删除会话不应连带删除用户资料库里的文件。
    """
    __tablename__ = "file_assets"
    __table_args__ = (
        Index("ix_file_assets_user_created", "user_id", "created_at"),
        Index("ix_file_assets_project_created", "project_id", "created_at"),
        # v0.7 per-user 目录：同一磁盘文件名在不同用户目录下互不冲突，唯一性随 user 走
        UniqueConstraint("user_id", "category", "stored_name", name="uq_file_assets_user_category_stored"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(16), default="generated", server_default="generated")
    stored_name: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(16), default="other", server_default="other")
    source: Mapped[str] = mapped_column(String(16), default="upload", server_default="upload")
    tool: Mapped[str] = mapped_column(String(32), default="", server_default="")
    size: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class KnowledgeChunk(Base):
    """v0.6.1（v0.5 收尾）知识库切块：资料库中文本类文件（上传的文档/代码）按段落切出的检索单元。

    检索走关键词打分（指南“先关键词、规模大了再上向量”的最小可行形态）；
    只索引 source=upload 的用户资料——Agent 生成的交付物不算“用户的知识”。
    asset_id 外键 CASCADE：文件删除时切块一起清；project_id 冗余自档案，仅为建块时参考，
    过滤一律走 FileAsset 联查（文件可在资料库里移项目，冗余列会过期）。
    """
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunks_asset_index", "asset_id", "chunk_index"),
        Index("ix_knowledge_chunks_user", "user_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("file_assets.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    content: Mapped[str] = mapped_column(Text)
    char_len: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # v0.6.2 向量检索：embedding 为 JSON 数值数组（MySQL JSON / SQLite TEXT 均可），embedding_model 记产生它的模型。
    # 两者必须成对看：角色换模型后旧向量不再可比（维度/空间都不同），按“未嵌入”对待、重建时重算。
    embedding_model: Mapped[str] = mapped_column(String(64), default="", server_default="")
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

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
