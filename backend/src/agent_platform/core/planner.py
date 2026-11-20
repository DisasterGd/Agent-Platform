"""任务规划器（v0.3）。

把一个目标拆解为有序的步骤计划。规划只依赖 ChatModel 协议（非流式 complete），
核心层不依赖 FastAPI/HTTP；模型不可用或输出无法解析时退化为单步计划，保证可运行。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agent_platform.models.base import ChatMessage, ChatModel

MAX_STEPS = 6

PLAN_SYSTEM_PROMPT = (
    "你是任务规划器。把用户目标拆解为按顺序执行的最少步骤。只输出 JSON 数组，"
    '每项形如 {"title": "不超过20字的步骤名", "detail": "该步骤要做什么（给执行者看的指令）"}。'
    "步骤数不超过 6；简单目标给 1 步即可。不要输出 JSON 以外的任何文字。"
)


@dataclass
class PlanStep:
    title: str
    detail: str


def parse_plan(text: str) -> list[PlanStep]:
    """从模型输出中提取 JSON 数组并规整；无法解析时返回空列表。"""
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    steps: list[PlanStep] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title", "")).split())[:60]
        detail = str(item.get("detail", "")).strip()
        if not title and not detail:
            continue
        steps.append(PlanStep(title=title or detail[:20], detail=detail or title))
        if len(steps) >= MAX_STEPS:
            break
    return steps


class Planner:
    def __init__(self, model: ChatModel | None = None) -> None:
        self.model = model

    async def plan(self, goal: str) -> list[PlanStep]:
        if self.model is None:
            return self._fallback(goal)
        try:
            text = await self.model.complete(
                [
                    ChatMessage(role="system", content=PLAN_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=goal),
                ]
            )
        except Exception:  # noqa: BLE001 — 规划失败不阻断，退化为单步
            return self._fallback(goal)
        steps = parse_plan(text)
        return steps or self._fallback(goal)

    @staticmethod
    def _fallback(goal: str) -> list[PlanStep]:
        """无模型/解析失败时的保底计划：直接把目标当作一步执行。"""
        return [PlanStep(title="完成任务", detail=goal)]
