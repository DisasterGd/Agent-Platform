"""任务执行器（v0.3）。

按规划步骤逐一驱动现有 Agent 循环（含工具调用），并流式汇报进度。
每步完成后做**程序化校验**（呼应开发指南：模型声称已完成 ≠ 真的成功）：
- 步骤必须有非空产出；
- 步骤声明生成的文件必须真实存在于 data/generated。
校验失败即 step_failed 并停止后续步骤（前端可整任务重试）。
核心层不依赖 FastAPI/HTTP。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from agent_platform.config import settings
from agent_platform.core.agent import Agent
from agent_platform.core.events import (
    Event,
    step_completed,
    step_failed,
    step_started,
    text_delta,
)
from agent_platform.infrastructure.storage.local import get_storage
from agent_platform.models.base import ChatMessage, ChatModel
from agent_platform.tools.registry import ToolRegistry

EXECUTOR_SYSTEM_PROMPT = (
    "你是任务执行器，负责完成多步任务中的“当前步骤”。"
    "结合总体目标、完整计划和已完成步骤的结果，只做当前步骤的事，输出该步骤的完整结果。"
    "可使用提供的工具（web_search / fetch_url / generate_file），需要最新信息时先搜索。"
)

SUMMARY_SYSTEM_PROMPT = "你负责任务收尾：把多步执行结果整合成一段简洁、完整的中文最终答复。"


@dataclass
class StepOutcome:
    """单步执行结果（供服务层落库与汇总）。"""

    index: int
    title: str
    status: str  # done / failed
    summary: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


def _clip(text: str, limit: int = 600) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


class Runner:
    def __init__(self, model: ChatModel | None = None, tools: ToolRegistry | None = None) -> None:
        self.model = model
        self.tools = tools
        self.outcomes: list[StepOutcome] = []

    async def run(self, goal: str, steps: list[dict[str, Any]]) -> AsyncIterator[Event]:
        """执行计划；产出 step_* / text_delta / tool_* / artifact_ready 事件流。

        每步的 StepOutcome 累积在 self.outcomes，供服务层在事件流中读取并持久化/汇总。
        """
        self.outcomes = []
        source = self._run_demo(goal, steps) if self.model is None else self._run_model(goal, steps)
        async for event in source:
            yield event

    async def _run_model(self, goal: str, steps: list[dict[str, Any]]) -> AsyncIterator[Event]:
        for index, step in enumerate(steps):
            title = str(step.get("title") or f"步骤 {index + 1}")
            detail = str(step.get("detail") or title)
            yield step_started(index, title)

            messages = [ChatMessage(role="system", content=EXECUTOR_SYSTEM_PROMPT)]
            messages.append(ChatMessage(role="user", content=self._step_prompt(goal, steps, index, title, detail)))

            parts: list[str] = []
            artifacts: list[dict[str, Any]] = []
            async for event in Agent(self.model, tools=self.tools).stream(messages):
                if event.type == "text_delta":
                    parts.append(event.data.get("content", ""))
                elif event.type == "artifact_ready":
                    artifacts.append(event.data)
                yield event

            summary = "".join(parts).strip()
            missing = [a for a in artifacts if not self._artifact_exists(a)]
            if not summary:
                outcome = StepOutcome(index, title, "failed", error="执行没有产出任何内容")
            elif missing:
                names = "、".join(str(a.get("filename", "")) for a in missing)
                outcome = StepOutcome(index, title, "failed", summary=summary, error=f"产出文件校验失败：找不到 {names}")
            else:
                outcome = StepOutcome(index, title, "done", summary=summary, artifacts=artifacts)
            self.outcomes.append(outcome)

            if outcome.status == "failed":
                yield step_failed(index, outcome.error)
                return
            yield step_completed(index, summary, artifacts)

    async def _run_demo(self, goal: str, steps: list[dict[str, Any]]) -> AsyncIterator[Event]:
        """无模型（本地演示）时的保底执行：逐步骤产出固定文本，保证流程可运行。"""
        for index, step in enumerate(steps):
            title = str(step.get("title") or f"步骤 {index + 1}")
            yield step_started(index, title)
            text = (
                f"（本地演示模式）已完成步骤“{title}”。\n\n"
                "当前未配置大模型 API Key，执行器只输出占位结果。"
                "请在根目录 .env 填写 LLM_API_KEY 或在设置页配置模型后重试。"
            )
            for i in range(0, len(text), 12):
                yield text_delta(text[i : i + 12])
            self.outcomes.append(StepOutcome(index, title, "done", summary=text))
            yield step_completed(index, text)

    def _step_prompt(self, goal: str, steps: list[dict[str, Any]], index: int, title: str, detail: str) -> str:
        lines = [f"总体目标：{goal}", "完整计划："]
        for i, s in enumerate(steps):
            mark = "▶" if i == index else " "
            lines.append(f"{mark} {i + 1}. {s.get('title', f'步骤 {i + 1}')}")
        if index > 0:
            lines.append("已完成步骤的结果：")
            for outcome in self.outcomes:
                lines.append(f"{outcome.index + 1}. {outcome.title}：{_clip(outcome.summary)}")
        lines.append(f"\n当前步骤（只完成这一步）：{title}\n要求：{detail}")
        return "\n".join(lines)

    @staticmethod
    def _artifact_exists(artifact: dict[str, Any]) -> bool:
        """程序化校验：generate_file 声明的文件必须真的在 generated 目录里。

        存储层落盘用可读文件名（清洗非法字符、重名自动加序号），artifact 的
        stored_name 即磁盘真实名，校验以此为准；没有 stored_name 才退回按 filename 查找。
        """
        stored_name = str(artifact.get("stored_name", "")).strip()
        if stored_name:
            return get_storage().resolve("generated", stored_name) is not None
        filename = str(artifact.get("filename", "")).strip()
        if not filename:
            return True  # 无文件名的 artifact（如非文件类产出）不做存在性校验
        return (settings.generated_dir / filename).is_file()
