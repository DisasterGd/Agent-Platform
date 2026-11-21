"""v0.3 规划器/执行器核心逻辑测试（不依赖数据库与网络）。"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from agent_platform.core.planner import Planner, PlanStep, parse_plan
from agent_platform.core.runner import Runner
from agent_platform.models.base import ModelResponse, StreamEvent, ToolCall
from agent_platform.tools.registry import ToolRegistry, ToolResult


class FakeModel:
    """按轮次返回预设输出；rounds 中每项是 (文本片段列表, 工具调用列表)。"""

    def __init__(self, rounds: list[tuple[list[str], list[ToolCall]]] | None = None, complete_text: str = "") -> None:
        self._rounds = list(rounds or [([], [])])
        self._complete_text = complete_text

    async def stream(self, messages) -> AsyncIterator[str]:
        for token in self._pop_round()[0]:
            yield token

    async def complete(self, messages) -> str:
        return self._complete_text

    async def complete_with_tools(self, messages, tools) -> ModelResponse:
        return ModelResponse(content=self._complete_text)

    async def stream_with_tools(self, messages, tools) -> AsyncIterator[StreamEvent]:
        texts, calls = self._pop_round()
        for token in texts:
            yield StreamEvent(kind="text", text=token)
        if calls:
            yield StreamEvent(kind="tool_calls", tool_calls=calls)

    def _pop_round(self):
        if len(self._rounds) == 1:
            return self._rounds[0]
        return self._rounds.pop(0)


async def _collect(agen) -> list:
    return [e async for e in agen]


# ---------- Planner ----------

def test_parse_plan_valid_and_fenced():
    raw = '规划如下：\n```json\n[{"title": "搜索", "detail": "搜索 X"}, {"title": "汇总", "detail": "写报告"}]\n```'
    steps = parse_plan(raw)
    assert [s.title for s in steps] == ["搜索", "汇总"]


def test_parse_plan_garbage_returns_empty():
    assert parse_plan("对不起，我无法输出 JSON") == []


def test_parse_plan_caps_steps():
    import json

    raw = json.dumps([{"title": f"t{i}", "detail": "d"} for i in range(20)])
    assert len(parse_plan(raw)) == 6


def test_planner_uses_model():
    planner = Planner(FakeModel(complete_text='[{"title": "第一步", "detail": "做 A"}]'))
    steps = asyncio.run(planner.plan("目标"))
    assert steps == [PlanStep("第一步", "做 A")]


def test_planner_fallbacks_on_no_model_or_garbage():
    assert asyncio.run(Planner(None).plan("目标A")) == [PlanStep("完成任务", "目标A")]
    assert asyncio.run(Planner(FakeModel(complete_text="乱七八糟")).plan("目标B")) == [
        PlanStep("完成任务", "目标B")
    ]


# ---------- Runner ----------

def test_runner_demo_mode_completes_all_steps():
    runner = Runner(model=None)
    events = asyncio.run(_collect(runner.run("目标", [{"title": "步骤1"}, {"title": "步骤2"}])))
    types = [e.type for e in events]
    assert types.count("step_started") == 2
    assert types.count("step_completed") == 2
    assert "step_failed" not in types
    assert all(o.status == "done" for o in runner.outcomes)


def test_runner_step_without_output_fails():
    runner = Runner(model=FakeModel(rounds=[(["  \n"], [])]))
    events = asyncio.run(_collect(runner.run("目标", [{"title": "S", "detail": "d"}])))
    failed = [e for e in events if e.type == "step_failed"]
    assert len(failed) == 1
    assert runner.outcomes[0].status == "failed"


def test_runner_artifact_verification_fails_when_file_missing():
    """程序化校验：模型声称生成了文件，但磁盘上不存在 → 该步骤必须判失败。"""

    async def fake_gen():
        return ToolResult(
            content='{"ok": true}',
            artifacts=[{"filename": "不存在的文件_9527.pdf", "url": "/api/files/generated/x.pdf", "format": "pdf"}],
        )

    tools = ToolRegistry()
    tools.register("fake_gen", "测试", {"type": "object", "properties": {}}, fake_gen)
    call = ToolCall(id="c1", name="fake_gen", arguments={})
    model = FakeModel(rounds=[([""], [call]), (["我已生成报告"], [])])

    runner = Runner(model=model, tools=tools)
    events = asyncio.run(_collect(runner.run("生成报告", [{"title": "产出报告", "detail": "调用工具"}])))
    failed = [e for e in events if e.type == "step_failed"]
    assert len(failed) == 1
    assert "校验失败" in failed[0].data["error"]
    # 失败后不再执行后续步骤
    assert [e.type for e in events].count("step_started") == 1


def test_runner_artifact_verification_uses_stored_name():
    """校验必须以 stored_name（磁盘真实名）为准：显示名含全角标点也不应误报“找不到”。"""
    import uuid

    from agent_platform.config import settings

    settings.generated_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.md"
    target = settings.generated_dir / stored
    target.write_bytes("# 内容".encode())
    try:

        async def fake_gen():
            return ToolResult(
                content='{"ok": true}',
                artifacts=[
                    {
                        "filename": "安全教学示例：文件加解密演示（合法替代）.md",
                        "stored_name": stored,
                        "url": f"/api/files/generated/{stored}",
                        "format": "md",
                    }
                ],
            )

        tools = ToolRegistry()
        tools.register("fake_gen", "测试", {"type": "object", "properties": {}}, fake_gen)
        call = ToolCall(id="c1", name="fake_gen", arguments={})
        model = FakeModel(rounds=[([""], [call]), (["已生成文档"], [])])

        runner = Runner(model=model, tools=tools)
        events = asyncio.run(_collect(runner.run("生成文档", [{"title": "产出文档", "detail": "调用工具"}])))
        assert [e.type for e in events].count("step_failed") == 0
        assert runner.outcomes[0].status == "done"
    finally:
        target.unlink(missing_ok=True)


def test_runner_collects_summaries_for_service():
    runner = Runner(model=FakeModel(rounds=[(["结果A"], []), (["结果B"], [])]))
    events = asyncio.run(
        _collect(runner.run("目标", [{"title": "S1", "detail": "d1"}, {"title": "S2", "detail": "d2"}]))
    )
    assert [o.summary for o in runner.outcomes] == ["结果A", "结果B"]
    completed = [e for e in events if e.type == "step_completed"]
    assert [e.data["index"] for e in completed] == [0, 1]
