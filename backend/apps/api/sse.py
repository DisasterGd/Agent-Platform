"""SSE 输出辅助（v0.8.1）：事件帧编码 + 心跳。

心跳解决两类问题（设计文档 4.3）：Caddy/浏览器等中间层对"长时间无字节"的连接掐断；
以及半开的僵尸连接占住 worker。做法是每 ~30s 注入一行 SSE 注释帧（`: ping`）——
注释帧对 EventSource/前端解析器完全透明。

实现注意：不能对 `source.__anext__()` 直接 `asyncio.wait_for`——超时会向流内部注入
CancelledError，把正在等待 LLM 的正常长轮询打断。这里用独立 pump 任务 + 队列：
pump 消费事件流，主循环带超时地读队列，超时只发心跳、不触碰流本身。
- 客户端断开：取消 pump——事件源内部的 CancelledError 兜底（落库已生成内容）语义不变；
- 事件源抛错：pump 结束后把异常在主循环原样重抛（与无心跳时的行为一致——响应中断）。
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from agent_platform.core.events import Event, to_sse

HEARTBEAT_INTERVAL_SECONDS = 30.0


async def with_heartbeat(
    source: AsyncIterator[Event], interval: float = HEARTBEAT_INTERVAL_SECONDS
) -> AsyncIterator[str]:
    async def pump(queue: asyncio.Queue) -> None:
        try:
            async for event in source:
                await queue.put(event)
        finally:
            queue.put_nowait(None)  # 结束哨兵：正常结束 / 抛错 / 被取消都会执行

    queue: asyncio.Queue[Event | None] = asyncio.Queue()
    task = asyncio.create_task(pump(queue))
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event is None:
                break
            yield to_sse(event)
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # 事件源自己的异常（非取消）：原样重抛，保持与无心跳时一致的响应中断行为
        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                raise exc
