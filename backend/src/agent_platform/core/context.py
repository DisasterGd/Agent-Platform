"""对话上下文构建。"""
from __future__ import annotations

from agent_platform.models.base import ChatMessage

SYSTEM_PROMPT = (
    "你是一个乐于助人的智能助手，请用简洁清晰的中文回答。\n"
    "你可以使用以下工具：\n"
    "- web_search：需要最新信息、事实或时效性内容时，先搜索再回答，并注明信息来源链接。\n"
    "- fetch_url：当搜索摘要不足以回答（例如需要具体数字、最新数据、详细内容）时，"
    "打开 web_search 结果里的链接读取正文后再回答。\n"
    "- generate_file：当用户要求生成可下载的文档（md/docx/pdf）时调用。\n"
    "不需要工具时直接回答即可。\n"
    "数学公式必须使用带定界符的 LaTeX：行内公式用 $...$，独立公式用 $$ 单独成行的 $$ 块；"
    "列表项或段落中的公式同样必须带定界符，禁止输出不带 $ 或 $$ 的裸 LaTeX 命令。"
)

MEMORY_HEADER = (
    "【记忆】以下是系统从历史对话中沉淀并持久化保存的记忆（可信但可能过时；"
    "若与用户当前说法冲突，一律以用户当前说法为准）："
)
SUMMARY_HEADER = "【前文摘要】本会话较早的内容已自动压缩为以下摘要："


def build_context(
    history: list[tuple[str, str]],
    *,
    summary: str = "",
    memory_block: str = "",
    extra_system: str = "",
) -> list[ChatMessage]:
    """把数据库中的 (role, content) 历史转换为发给模型的上下文。

    v0.4：
    - memory_block：注入到系统提示词末尾的全局/项目记忆；
    - summary：超长会话早期消息的自动压缩摘要，放在历史消息之前。
    v0.7.6：extra_system——本地项目会话追加的项目说明（放在主提示词之后、记忆之前）。
    """
    system = SYSTEM_PROMPT
    if extra_system:
        system = f"{system}\n\n{extra_system}"
    if memory_block:
        system = f"{system}\n\n{MEMORY_HEADER}\n{memory_block}"
    messages = [ChatMessage(role="system", content=system)]
    if summary:
        messages.append(ChatMessage(role="system", content=f"{SUMMARY_HEADER}\n{summary}"))
    messages.extend(ChatMessage(role=role, content=content) for role, content in history)
    return messages
