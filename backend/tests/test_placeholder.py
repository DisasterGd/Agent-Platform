"""纯逻辑单元测试（不依赖数据库与网络）。"""
from __future__ import annotations

from agent_platform.core.context import SYSTEM_PROMPT, build_context
from agent_platform.core.events import error, task_completed, text_delta, to_sse


def test_build_context_prepends_system_prompt():
    messages = build_context([("user", "你好"), ("assistant", "你好！")])
    assert messages[0].role == "system"
    assert messages[0].content == SYSTEM_PROMPT
    assert [m.role for m in messages[1:]] == ["user", "assistant"]


def test_to_sse_text_delta():
    frame = to_sse(text_delta("你好"))
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    assert '"type": "text_delta"' in frame
    assert "你好" in frame


def test_to_sse_error_and_completed():
    assert '"type": "error"' in to_sse(error("出错了"))
    assert '"type": "task_completed"' in to_sse(task_completed())
