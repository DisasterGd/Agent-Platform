"""统一事件定义。

Agent 核心、Service 与 API 层之间通过这些结构化事件传递流式输出。
SSE 编码只发生在 API 层，核心层不依赖 HTTP 细节。

v0.2 新增：工具调用与文件产出事件。
v0.3 新增：任务规划与执行事件（plan_created / step_started / step_completed / step_failed）。
v0.4 新增：记忆系统事件（context_compressed / memory_saved）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


def text_delta(content: str) -> Event:
    return Event("text_delta", {"content": content})


def task_started() -> Event:
    return Event("task_started")


def task_completed(data: dict[str, Any] | None = None) -> Event:
    return Event("task_completed", data or {})


def error(message: str) -> Event:
    return Event("error", {"message": message})


def tool_started(name: str) -> Event:
    return Event("tool_started", {"name": name})


def tool_completed(name: str) -> Event:
    return Event("tool_completed", {"name": name})


def artifact_ready(artifact: dict[str, Any]) -> Event:
    """Agent 生成了一个可下载文件。"""
    return Event("artifact_ready", artifact)


def plan_created(steps: list[dict[str, Any]], conversation_id: int | None = None) -> Event:
    """v0.3：规划器产出了任务步骤计划（[{index,title,detail,status}...]）。

    conversation_id：执行开始时绑定的会话（无会话时后端已即时新建）。
    """
    data: dict[str, Any] = {"steps": steps}
    if conversation_id is not None:
        data["conversation_id"] = conversation_id
    return Event("plan_created", data)


def step_started(index: int, title: str) -> Event:
    return Event("step_started", {"index": index, "title": title})


def step_completed(index: int, summary: str, artifacts: list[dict[str, Any]] | None = None) -> Event:
    return Event("step_completed", {"index": index, "summary": summary, "artifacts": artifacts or []})


def step_failed(index: int, error: str) -> Event:
    return Event("step_failed", {"index": index, "error": error})


def context_compressed(count: int) -> Event:
    """v0.4：会话历史超长，已自动压缩 count 条早期消息为摘要。"""
    return Event("context_compressed", {"count": count})


def memory_saved(items: list[dict[str, Any]]) -> Event:
    """v0.4：本轮对话写入了记忆（[{title,scope,category,source}...]）。"""
    return Event("memory_saved", {"items": items})


def to_sse(event: Event) -> str:
    """把事件编码为一条 SSE 帧（`data: {...}\n\n`）。"""
    return f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
