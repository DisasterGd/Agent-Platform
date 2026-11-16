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
    "不需要工具时直接回答即可。"
)


def build_context(history: list[tuple[str, str]]) -> list[ChatMessage]:
    """把数据库中的 (role, content) 历史转换为发给模型的上下文。"""
    messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
    messages.extend(ChatMessage(role=role, content=content) for role, content in history)
    return messages
