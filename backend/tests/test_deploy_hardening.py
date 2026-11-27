"""v0.8.1 部署加固测试：SSE 心跳 + 全站限流 + 模型客户端复用 + 连接池参数（SQLite 跳过）。

项目未引入 pytest-asyncio：异步场景用 asyncio.run 在同步用例里整体驱动。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from agent_platform.config import settings
from agent_platform.core.events import Event, error, text_delta
from agent_platform.models.openai_compatible import _clients, _get_client
from apps.api.main import RateLimiter
from apps.api.sse import HEARTBEAT_INTERVAL_SECONDS, with_heartbeat

# ---------- SSE 心跳 ----------


async def _slow_source(events: list[Event], delay: float) -> AsyncIterator[Event]:
    for e in events:
        await asyncio.sleep(delay)
        yield e


def test_heartbeat_inserts_comment_frames_when_idle() -> None:
    """流空闲超过间隔 → 心跳注释帧；事件帧照常透传；结束即止不拖尾巴。"""
    async def main() -> list[str]:
        frames: list[str] = []
        async for frame in with_heartbeat(_slow_source([text_delta("hi"), error("boom")], delay=0.12),
                                          interval=0.05):
            frames.append(frame)
        return frames

    frames = asyncio.run(asyncio.wait_for(main(), timeout=5))
    pings = [f for f in frames if f.startswith(": ping")]
    assert pings, "空闲期应有心跳注释帧"
    assert all(f == ": ping\n\n" for f in pings)
    assert any('"text_delta"' in f for f in frames)
    assert any('"error"' in f for f in frames)
    assert frames[-1].startswith("data:")  # 心跳只出现在事件之间的空窗


def test_heartbeat_propagates_source_exception() -> None:
    """事件源抛错：主循环原样重抛（与无心跳时行为一致）。"""
    async def broken() -> AsyncIterator[Event]:
        yield text_delta("ok")
        raise RuntimeError("llm exploded")

    async def main() -> list[str]:
        frames: list[str] = []
        async for frame in with_heartbeat(broken(), interval=30):
            frames.append(frame)
        return frames

    with pytest.raises(RuntimeError, match="llm exploded"):
        asyncio.run(main())


def test_heartbeat_cancels_source_on_client_disconnect() -> None:
    """客户端断开（aclose → GeneratorExit）→ pump 被取消 → 源内部收到 CancelledError（落库兜底语义不变）。"""
    async def main() -> tuple[int, bool]:
        cancelled = {"flag": False}

        async def endless() -> AsyncIterator[Event]:
            try:
                while True:
                    await asyncio.sleep(0.02)
                    yield text_delta("x")
            except asyncio.CancelledError:
                cancelled["flag"] = True
                raise

        gen = with_heartbeat(endless(), interval=30)
        got: list[str] = []
        try:
            for _ in range(3):
                got.append(await gen.__anext__())
        finally:
            await gen.aclose()
        await asyncio.sleep(0.1)
        return len(got), cancelled["flag"]

    got, cancelled = asyncio.run(main())
    assert got == 3 and cancelled is True


def test_heartbeat_default_interval() -> None:
    assert HEARTBEAT_INTERVAL_SECONDS == 30


# ---------- 全站限流 ----------


def test_rate_limiter_sliding_window() -> None:
    limiter = RateLimiter(3, window_seconds=1.0)
    assert [limiter.allow("ip1") for _ in range(3)] == [True, True, True]
    assert limiter.allow("ip1") is False          # 窗口内超限
    assert limiter.allow("ip2") is True           # 不同 IP 互不影响
    time.sleep(1.05)
    assert limiter.allow("ip1") is True           # 窗口滑过 → 恢复


def test_rate_limiter_disabled_when_zero() -> None:
    limiter = RateLimiter(0)
    assert all(limiter.allow("ip") for _ in range(1000))


def test_rate_limit_default_setting() -> None:
    assert settings.rate_limit_per_minute == 120  # 合理默认（本地单用户无感，上线防刷）


# ---------- 模型客户端复用 ----------


def test_openai_client_reuse_by_base_url_and_key() -> None:
    _clients.clear()
    c1 = _get_client("https://api.deepseek.com", "sk-a")
    c2 = _get_client("https://api.deepseek.com", "sk-a")
    c3 = _get_client("https://api.deepseek.com", "sk-b")
    assert c1 is c2          # 同 base_url + 同 Key 复用
    assert c1 is not c3      # 不同 Key 隔离
    assert len(_clients) == 2
    for i in range(70):      # 容量上限：超出后挤掉最旧的
        _get_client("https://x.example.com", f"k{i}")
    assert len(_clients) <= 64
    _clients.clear()


# ---------- 连接池（SQLite 分支不炸；真实参数在 MySQL 下生效，容器演练时验） ----------


def test_engine_pool_tuning_defaults() -> None:
    assert settings.db_pool_size == 10 and settings.db_max_overflow == 20


def test_engine_usable_under_sqlite_branch() -> None:
    from agent_platform.infrastructure.database import session as db_session

    with db_session.engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
