"""聊天业务用例：会话管理 + 流式回复（v0.2 工具调用，v0.3 附件）。"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.orm import Session

from agent_platform.core.agent import Agent
from agent_platform.core.events import (
    Event,
    error,
    task_completed,
    task_started,
    text_delta,
)
from agent_platform.infrastructure.attachments import (
    extract_text,
    image_to_data_uri,
    parse_file_url,
)
from agent_platform.infrastructure.database.models import Conversation, LocalProject
from agent_platform.memory.manager import MemoryManager
from agent_platform.models.base import ChatMessage, ImagePart
from agent_platform.models.factory import create_model, create_vision_model
from agent_platform.repositories.conversations import ConversationRepository
from agent_platform.repositories.groups import GroupRepository
from agent_platform.repositories.local_projects import LocalProjectRepository
from agent_platform.repositories.messages import MessageRepository
from agent_platform.repositories.projects import ProjectRepository
from agent_platform.services.knowledge_service import KnowledgeService
from agent_platform.services.library_service import LibraryService
from agent_platform.services.settings_service import (
    PRESETS,
    SettingsService,
    get_settings_service,
    user_settings_service,
)
from agent_platform.tools.builtin.registry import build_default_registry
from agent_platform.tools.registry import ToolRegistry

TITLE_SYSTEM_PROMPT = (
    "你是会话标题生成器。根据用户的问题，输出一个不超过 12 个汉字的中文标题，"
    "概括对话主题。只输出标题本身，不要引号、标点或任何解释。"
)

VISION_PROMPT = "请用简洁的中文描述这张图片的内容。"

PROVISIONAL_TITLE_LIMIT = 20

# update_conversation 的“未传该字段”哨兵（None 表示显式移出项目/分组）
UNSET = object()


def provisional_title(content: str) -> str:
    """生成阶段的临时标题：直接截取首条用户消息，让会话列表马上“有内容可依”。"""
    text = " ".join(content.split())
    return text[:PROVISIONAL_TITLE_LIMIT] + ("…" if len(text) > PROVISIONAL_TITLE_LIMIT else "")


class ChatService:
    def __init__(self, db: Session, user_id: int | None = None) -> None:
        self.db = db
        # v0.7：请求者身份（local=None → 共享配置与文件根目录；cloud=按用户隔离配置与文件）
        self.user_id = user_id
        self.conversations = ConversationRepository(db)
        self.messages = MessageRepository(db)
        # v0.4.1：会话移动（添加至项目/分组）时校验归属
        self.projects = ProjectRepository(db)
        self.groups = GroupRepository(db)
        self.model = create_model(db, user_id)
        self.tools: ToolRegistry = build_default_registry()
        # v0.4：会话压缩 + 长期记忆注入/提炼的统一入口
        self.memory = MemoryManager(db, self.model, user_id=user_id)
        # v0.5：生成文件登记进资料库（工具只产出 artifact 事件，落库在这里）
        self.library = LibraryService(db)
        # v0.6.1：知识库检索（工具按轮注入，闭包携带当轮归属）
        self.knowledge = KnowledgeService(db, user_id=user_id)
        # v0.6 打磨：未配置识图角色、但主模型原生支持图像（在其供应商 vision_models 清单内）
        # → 附件图片以 data URI 直传主模型，而不是悄悄丢弃
        self.images_to_main = self._compute_direct_vision()

    def _settings(self) -> SettingsService:
        """该用户生效的设置（cloud=数据库按用户隔离；local=None → 共享文件，行为同 v0.6）。"""
        if self.user_id is None:
            return get_settings_service()
        return user_settings_service(self.db, self.user_id)

    def _compute_direct_vision(self) -> bool:
        if self.model is None:
            return False
        service = self._settings()
        if service.resolve_role("vision") is not None:
            return False
        reasoning = service.resolve_role("reasoning")
        if not reasoning:
            return False
        return reasoning["model"] in (PRESETS.get(reasoning["provider"], {}).get("vision_models") or [])

    def create_conversation(
        self,
        user_id: int,
        title: str = "新会话",
        project_id: int | None = None,
        local_project_id: int | None = None,
    ) -> Conversation:
        """建会话；local_project_id（v0.7.6）与 project_id 互斥，归属需校验（防挂到别人的本地项目）。"""
        if local_project_id is not None:
            if project_id is not None:
                raise ValueError("会话只能归属一个项目：工作项目与本地项目二选一")
            if LocalProjectRepository(self.db).get_owned(int(local_project_id), user_id) is None:
                raise ValueError("本地项目不存在")
        return self.conversations.create(user_id, title, project_id, local_project_id=local_project_id)

    def list_conversations(self, user_id: int, project_id: object = ...) -> list[Conversation]:
        return self.conversations.list_by_user(user_id, project_id=project_id)

    def get_conversation(self, conversation_id: int, user_id: int | None = None) -> Conversation | None:
        """取会话；传 user_id 时校验归属（不是本人的按不存在处理，避免暴露存在性）。"""
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return None
        if user_id is not None and conversation.user_id != user_id:
            return None
        return conversation

    def list_messages(self, conversation_id: int, user_id: int | None = None):
        if self.get_conversation(conversation_id, user_id) is None:
            return None
        return self.messages.list_by_conversation(conversation_id)

    def rename_conversation(self, conversation_id: int, title: str) -> Conversation | None:
        title = title.strip()
        if not title:
            return self.conversations.get(conversation_id)
        return self.conversations.update_title(conversation_id, title)

    def update_conversation(
        self,
        conversation_id: int,
        title: str | None = None,
        pinned: bool | None = None,
        project_id: object = UNSET,
        group_id: object = UNSET,
        user_id: int | None = None,
    ) -> Conversation | None:
        """会话编辑；project_id / group_id 只有显式传入（含 None=移出）才修改归属。

        user_id 传入时校验归属（不是本人的会话一律 404 语义返回 None）。
        """
        conversation = self.get_conversation(conversation_id, user_id)
        if conversation is None:
            return None
        if title is not None:
            title = title.strip() or None
        conversation = self.conversations.update(conversation_id, title=title, pinned=pinned)
        if conversation is None:
            return None
        if project_id is not UNSET:
            if project_id is not None:
                project = self.projects.get(int(project_id))
                if project is None or project.user_id != conversation.user_id:
                    raise ValueError("项目不存在")
            self.conversations.set_project(conversation_id, project_id)  # type: ignore[arg-type]
        if group_id is not UNSET:
            if group_id is not None:
                group = self.groups.get(int(group_id))
                if group is None or group.user_id != conversation.user_id:
                    raise ValueError("分组不存在")
            self.conversations.set_group(conversation_id, group_id)  # type: ignore[arg-type]
        return self.conversations.get(conversation_id)

    def delete_conversation(self, conversation_id: int, user_id: int | None = None) -> bool:
        """删除会话；user_id 传入时校验归属（不是本人的按不存在处理）。"""
        if self.get_conversation(conversation_id, user_id) is None:
            return False
        return self.conversations.delete(conversation_id)

    async def regenerate_reply(
        self,
        conversation_id: int,
        message_id: int,
        new_content: str | None = None,
    ) -> AsyncIterator[Event]:
        """重新生成某条用户提问之后的回复（可选替换该提问内容）。

        不再删除旧内容：提问与回复都按版本链（group_id + variant_index）累积保存，
        历史版本在前端可左右翻页查看。仅支持「最后一轮」重新生成，
        避免会话中途重跑导致后续消息与新版本脱节（分支化留待后续版本）。
        """
        target = self.messages.get(message_id)
        if target is None or target.conversation_id != conversation_id or target.role != "user":
            yield error("要重新生成的消息不存在或不是用户提问")
            return
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            yield error("会话不存在")
            return
        content = new_content.strip() if new_content is not None and new_content.strip() else target.content
        attachments = target.attachments or []

        active = self.messages.list_active_by_conversation(conversation_id)
        group = target.group_id or target.id
        pos = next((i for i, m in enumerate(active) if (m.group_id or m.id) == group), None)
        if pos is None:
            yield error("要重新生成的消息不存在")
            return
        tail = active[pos + 1:]
        if any(m.role != "assistant" for m in tail):
            yield error("仅支持重新生成最后一轮的回复")
            return
        # 被替换的旧回复所属版本链：新回复作为它的下一个版本（若无旧回复则开新链）
        assistant_group = (tail[-1].group_id or tail[-1].id) if tail else None

        yield task_started()

        # 提问变了也要保留原提问：作为同一版本链的新版本入库
        latest = active[pos]
        if content != latest.content:
            self.messages.add(
                conversation_id,
                "user",
                content,
                attachments=attachments,
                group_id=group,
                variant_index=self.messages.next_variant_index(group),
            )

        enriched, direct_images = await self._enrich(content, attachments, conversation.user_id)
        self.conversations.touch(conversation_id)

        # 上下文 = 此前各轮 + 本轮提问（合成一条未落库的最新 id 以免被摘要覆盖）；
        # 丢弃待替换的旧回复，避免模型参照自己的旧答案；同样经过压缩与记忆注入
        prior = [(m.id, m.role, m.content) for m in active[:pos]]
        next_id = max((m.id for m in active), default=0) + 1
        entries = prior + [(next_id, "user", enriched)]
        extra_system = ""
        local = self._local_project(conversation)
        if local is not None:
            extra_system = self._local_project_prompt(local)
        context, ctx_events = await self.memory.build_messages(conversation, entries, extra_system=extra_system)
        self._attach_direct_images(context, direct_images)
        for event in ctx_events:
            yield event
        async for event in self._stream_turn(
            conversation, context, content, assistant_group_id=assistant_group
        ):
            yield event

    def apply_provisional_title(self, conversation_id: int, content: str) -> None:
        """生成开始时同步写入截取式临时标题（仅当标题仍是默认值）。"""
        conversation = self.conversations.get(conversation_id)
        if conversation is None or conversation.title.strip() not in ("", "新会话"):
            return
        self.conversations.update_title(conversation_id, provisional_title(content))

    async def ensure_title(self, conversation_id: int, content: str) -> None:
        """标题仍为默认值或本轮的临时标题时，用模型生成简洁标题（无模型则退化截断）。"""
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return
        current = conversation.title.strip()
        if current not in ("", "新会话", provisional_title(content)):
            return
        title = ""
        if self.model is not None:
            try:
                title = await self.model.complete(
                    [
                        ChatMessage(role="system", content=TITLE_SYSTEM_PROMPT),
                        ChatMessage(role="user", content=content),
                    ]
                )
            except Exception:  # noqa: BLE001 — 标题生成失败不影响主流程
                title = ""
        title = " ".join(title.split()).strip().strip('"\'“”「」『』')
        if not title:
            title = provisional_title(content)
        self.conversations.update_title(conversation_id, title)

    async def _describe_image(self, category: str, stored_name: str, content_type: str, user_id: int | None = None) -> str | None:
        """用视觉模型描述图片；未配置视觉模型时返回 None。"""
        vision = create_vision_model(self.db, user_id if user_id is not None else self.user_id)
        if vision is None:
            return None
        data_uri = image_to_data_uri(category, stored_name, content_type, user_id)
        if data_uri is None:
            return None
        try:
            return await vision.complete(
                [ChatMessage(role="user", content=VISION_PROMPT, images=[ImagePart(url=data_uri)])]
            )
        except Exception:  # noqa: BLE001 — 识图失败不影响主流程
            return None

    async def _enrich(
        self, content: str, attachments: list[dict], user_id: int | None = None
    ) -> tuple[str, list[ImagePart]]:
        """把附件正文/识图结果拼进用户消息，供模型读取（只读该用户目录下的附件文件）。

        返回 (增强正文, 直传主模型的图片)——后者仅在"未配置识图角色且主模型原生支持图像"时有内容。
        """
        parts: list[str] = [content]
        direct_images: list[ImagePart] = []
        for att in attachments:
            parsed = parse_file_url(att.get("url", ""))
            if parsed is None:
                continue
            category, stored_name = parsed
            content_type = att.get("content_type", "")
            name = att.get("name", stored_name)
            if content_type.startswith("image/"):
                description = await self._describe_image(category, stored_name, content_type, user_id)
                if description:
                    parts.append(f"\n\n[图片 {name}]\n{description}")
                elif self.images_to_main:
                    data_uri = image_to_data_uri(category, stored_name, content_type, user_id)
                    if data_uri:
                        direct_images.append(ImagePart(url=data_uri))
                        parts.append(f"\n\n[图片 {name}]\n（原图已附在本消息中，请直接观察）")
                else:
                    parts.append(f"\n\n[图片 {name}]\n（未解析：未配置识图角色，且主模型不支持图像输入）")
            else:
                text = extract_text(category, stored_name, content_type, user_id)
                if text:
                    parts.append(f"\n\n[附件 {name}]\n{text}")
        return "\n".join(parts), direct_images

    def _local_project(self, conversation: Conversation) -> LocalProject | None:
        """会话挂接的本地项目（v0.7.6）：归属不符（理论不可达，防御性）按不存在处理。"""
        if conversation.local_project_id is None:
            return None
        return LocalProjectRepository(self.db).get_owned(conversation.local_project_id, conversation.user_id)

    @staticmethod
    def _local_project_prompt(project: LocalProject) -> str:
        """本地项目会话的系统提示词段：告知根目录、路径约定与写入开关。"""
        write_note = "开启：你可以创建/覆盖项目内的文本文件" if project.allow_write \
            else "关闭（只读）：你没有写文件的工具，只能查看与分析代码"
        return (
            f"【本地项目】你正在本机的真实项目「{project.title}」内工作（目录 {project.root_path}）。\n"
            "- 文件工具 local_list_dir / local_read_file / local_write_file 只作用于此项目根目录之内，"
            "路径一律使用相对路径，越出项目根会被拒绝；\n"
            f"- 该项目的写入开关：{write_note}；\n"
            "- 你读写的是磁盘上的真实文件——写文件时给出完整内容，不要留占位符；"
            "改动完成后提示用户在伪编辑器里刷新即可看到最新内容。"
        )

    def _turn_tools(self, conversation: Conversation, local_project: LocalProject | None = None) -> ToolRegistry:
        """当轮工具表：按会话归属注入用户上下文（文件落 per-user 目录、生图读本人角色）。

        search_knowledge 闭包携带会话归属/项目，工具层因此保持"不碰数据库"。
        本地项目会话（v0.7.6）额外注入 local_* 三件套：root 只来自注册行；写工具须项目 allow_write。
        """
        def search(query: str, project_only: bool) -> list[dict]:
            return self.knowledge.tool_search(conversation.user_id, conversation.project_id, query, project_only)

        def image_config() -> dict | None:
            from agent_platform.models.factory import create_image_config

            return create_image_config(self.db, conversation.user_id)

        local = local_project if local_project is not None else self._local_project(conversation)
        return build_default_registry(
            user_id=conversation.user_id,
            knowledge_search=search,
            image_config=image_config,
            local_root=Path(local.root_path) if local is not None else None,
            local_write=local.allow_write if local is not None else False,
        )

    @staticmethod
    def _attach_direct_images(context: list[ChatMessage], images: list[ImagePart]) -> None:
        """直传图挂到最后一条用户消息上（压缩摘要等结构不动，只补 images 字段）。"""
        if not images:
            return
        for msg in reversed(context):
            if msg.role == "user":
                msg.images = list(images)
                return

    def _register_asset(self, conversation: Conversation, artifact: dict) -> None:
        """v0.5：把工具产出的文件登记进资料库（带会话/项目归属）。

        登记失败绝不能打断回复流，所以整段吞掉异常：文件已经落盘，用户仍可在消息里下载。
        """
        try:
            self.library.register_artifact(
                artifact,
                user_id=conversation.user_id,
                source="chat",
                project_id=conversation.project_id,
                conversation_id=conversation.id,
            )
        except Exception:  # noqa: BLE001,S110 — 资料库登记失败不影响聊天主流程
            pass

    def _link_attachments(self, conversation: Conversation, attachments: list[dict]) -> None:
        """v0.5：上传附件在“发送这一刻”才确定归属，补写会话与项目。"""
        if not attachments:
            return
        try:
            self.library.link_attachments(
                attachments,
                user_id=conversation.user_id,
                conversation_id=conversation.id,
                project_id=conversation.project_id,
            )
        except Exception:  # noqa: BLE001,S110 — 同上，登记失败不阻断发送
            pass

    async def stream_reply(
        self,
        conversation_id: int,
        content: str,
        attachments: list[dict] | None = None,
    ) -> AsyncIterator[Event]:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            yield error("会话不存在")
            return

        yield task_started()

        attachments = attachments or []
        enriched, direct_images = await self._enrich(content, attachments, conversation.user_id)

        # 落库保存原始内容 + 附件元数据，供前端展示与刷新后回显
        self.messages.add(conversation_id, "user", content, attachments=attachments)
        self._link_attachments(conversation, attachments)
        self.conversations.touch(conversation_id)
        # 新会话立刻有可读标题（截取提问），生成完成后再由模型精炼
        self.apply_provisional_title(conversation_id, content)

        # 上下文 = 每个版本链最新一条（末条用附件/识图增强），经 MemoryManager：超长先压缩、再注入记忆
        history = self.messages.list_active_by_conversation(conversation_id)
        entries = [(m.id, m.role, m.content) for m in history]
        if entries and entries[-1][1] == "user":
            entries[-1] = (entries[-1][0], "user", enriched)
        extra_system = ""
        local = self._local_project(conversation)
        if local is not None:
            extra_system = self._local_project_prompt(local)
        context, ctx_events = await self.memory.build_messages(conversation, entries, extra_system=extra_system)
        self._attach_direct_images(context, direct_images)
        for event in ctx_events:
            yield event

        async for event in self._stream_turn(conversation, context, content):
            yield event

    async def _stream_turn(
        self,
        conversation: Conversation,
        chat_messages: list[ChatMessage],
        user_content: str,
        assistant_group_id: int | None = None,
    ) -> AsyncIterator[Event]:
        """调用模型产出一次回复，并作为新消息（或旧回复的新版本）落库。

        中断兜底：模型报错或客户端切走导致流终止时，已生成的部分（含中断说明）也会落库，
        避免“生成到一半的内容凭空消失”。
        """
        conversation_id = conversation.id
        parts: list[str] = []
        persisted = False

        def _persist(note: str = "") -> None:
            nonlocal persisted
            if persisted:
                return
            reply = ("".join(parts) + note).strip()
            if not reply:
                return
            if assistant_group_id is not None:
                # 重新生成：不覆盖旧回复，追加为同一版本链的下一个版本
                self.messages.add(
                    conversation_id,
                    "assistant",
                    reply,
                    group_id=assistant_group_id,
                    variant_index=self.messages.next_variant_index(assistant_group_id),
                )
            else:
                self.messages.add(conversation_id, "assistant", reply)
            persisted = True

        try:
            if self.model is not None:
                agent = Agent(self.model, tools=self._turn_tools(conversation))
                async for event in agent.stream(chat_messages):
                    if event.type == "text_delta":
                        parts.append(event.data.get("content", ""))
                    elif event.type == "artifact_ready":
                        self._register_asset(conversation, event.data)
                    yield event
            else:
                async for token in self._demo_stream(user_content):
                    parts.append(token)
                    yield text_delta(token)
        except (asyncio.CancelledError, GeneratorExit):
            # 客户端断开/切换会话：同步落库部分产出后继续向上抛出（不能在 finally 里 await）
            _persist("\n\n（回复生成被中断）")
            raise
        except Exception as exc:  # noqa: BLE001
            _persist(f"\n\n⚠️ 生成中断：{exc}")
            yield error(f"模型调用失败：{exc}")
            return

        _persist()
        await self.ensure_title(conversation_id, user_content)
        # v0.4：轮末记忆提炼（含用户显式“记住”请求）；提炼失败不阻断主流程
        try:
            reply = "".join(parts).strip()
            memory_events = await self.memory.after_turn(conversation, user_content, reply)
        except Exception:  # noqa: BLE001
            memory_events = []
        for mem_event in memory_events:
            yield mem_event
        yield task_completed()

    async def _demo_stream(self, user_text: str) -> AsyncIterator[str]:
        reply = (
            f"我收到了你的消息：{user_text}\n\n"
            "当前未配置大模型 API Key，运行在本地演示模式。\n"
            "请在项目根目录的 .env 中填写 LLM_API_KEY（默认 DeepSeek）后重启后端，"
            "即可接入真实模型。"
        )
        for i in range(0, len(reply), 8):
            yield reply[i : i + 8]
            await asyncio.sleep(0.02)
