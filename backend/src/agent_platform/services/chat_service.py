import asyncio
from collections.abc import AsyncIterator
from sqlalchemy.orm import Session
from agent_platform.repositories.chat_repository import ChatRepository

class ChatService:
    def __init__(self, db: Session):
        self.repository = ChatRepository(db)

    def save_user_message(self, conversation_id: int, content: str):
        return self.repository.add_message(conversation_id, "user", content)

    async def demo_reply_stream(self, conversation_id: int, user_text: str) -> AsyncIterator[str]:
        reply = (
            f"我收到了你的消息：{user_text}\n\n"
            "当前是 Agent Platform v0.1 的本地演示模式。下一阶段会接入模型适配器，"
            "并逐步加入工具调用与任务规划。"
        )
        parts = [reply[i:i + 8] for i in range(0, len(reply), 8)]
        for part in parts:
            yield part
            await asyncio.sleep(0.035)
        self.repository.add_message(conversation_id, "assistant", reply)
