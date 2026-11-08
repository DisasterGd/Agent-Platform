"""任务规划器（v0.3 实现）。

当前只提供占位接口，Agent 核心暂不调用。
"""
from __future__ import annotations


class Planner:
    def plan(self, goal: str) -> list[str]:
        raise NotImplementedError("任务规划将在 v0.3 实现")
