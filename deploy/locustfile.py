r"""Agent Platform 简单压测（v0.8.1 验收：locust 出数）。

设计文档 4.3：本应用是**长连接型**并发（瓶颈=同时活跃的 Agent 会话数），不是 QPS 型。
本文件覆盖三类真实画像：

1. 轻量读（会话列表/健康检查）——模拟打开界面的常规请求；
2. 会话建/删——模拟日常写路径（落 MySQL）；
3. SSE 流式对话——**默认关闭**（LOCUST_STREAM=1 才开启）：流的瓶颈在上游 LLM 供应商的并发限速
   （设计文档 4.3 预判，2026-11-28 实测证实：20 并发真实流即触发上游限速），且走真实 Key 会产生费用。
   开启时额外上报"首事件时延"与"整流时长"。常规跑分只测本应用自身的读写吞吐。

运行步骤（压测目标实例须关闭限流，否则 429 会污染数据）：

  # 1. 起一个专用实例（环境变量覆盖 .env 的限流；幂等方法带重试防 keep-alive 竞态）
  #    PowerShell：
  #      $env:RATE_LIMIT_PER_MINUTE="0"
  #      cd backend; ..\.venv\Scripts\python.exe -m uvicorn apps.api.main:app --port 8101 --app-dir .
  # 2. 装压测工具（一次性）：..\.venv\Scripts\python.exe -m pip install locust
  # 3. 跑（20 并发用户、每秒进 5 个、持续 30 秒）：
  #      .venv\Scripts\python.exe -m locust -f deploy/locustfile.py --headless -u 20 -r 5 -t 30s --host http://127.0.0.1:8101
  # 4. 压测产生的会话标题带「【压测】」前缀，跑完按前缀清理（参见 README 部署小节的 SQL）。
"""
import os
import time

from locust import HttpUser, between, task
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

STREAM_ENABLED = os.environ.get("LOCUST_STREAM") == "1"


class AgentPlatformUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        # uvicorn keep-alive 超时会回收空闲连接，压测端复用陈旧连接偶发 RemoteDisconnected——
        # 对幂等方法（GET/DELETE）开 2 次重试（POST 不重试，避免重复建会话）
        retry = Retry(total=2, backoff_factor=0.1, allowed_methods=frozenset({"GET", "DELETE"}))
        adapter = HTTPAdapter(max_retries=retry)
        self.client.mount("http://", adapter)
        self.client.mount("https://", adapter)

    @task(4)
    def list_conversations(self):
        self.client.get("/api/conversations")

    @task(2)
    def health(self):
        self.client.get("/api/health")

    @task(2)
    def create_and_delete_conversation(self):
        resp = self.client.post("/api/conversations", json={"title": "【压测】临时会话"})
        if resp.status_code == 201:
            cid = resp.json()["id"]
            self.client.delete(f"/api/conversations/{cid}", name="/api/conversations/[id]")

    @task(1)
    def sse_stream_demo(self):
        """核心画像（LOCUST_STREAM=1 才注册，防误耗真实模型额度）：一路 SSE 流。"""
        if not STREAM_ENABLED:
            return
        resp = self.client.post("/api/conversations", json={"title": "【压测】流式"})
        if resp.status_code != 201:
            return
        cid = resp.json()["id"]
        start = time.perf_counter()
        first_event_ms = None
        ok = False
        try:
            with self.client.post(
                "/api/chat/stream",
                json={"conversation_id": cid, "content": "【压测】你好", "attachments": []},
                stream=True,
                catch_response=True,
                timeout=60,
                name="/api/chat/stream[headers]",
            ) as r:
                if r.status_code != 200:
                    r.failure(f"stream http {r.status_code}")
                    return
                for line in r.iter_lines(decode_unicode=True):
                    if first_event_ms is None and line.startswith("data:"):
                        first_event_ms = (time.perf_counter() - start) * 1000
                    if line.startswith("data:") and '"task_completed"' in line:
                        ok = True
                        break
        finally:
            self.client.delete(f"/api/conversations/{cid}", name="/api/conversations/[id]")

        full_ms = (time.perf_counter() - start) * 1000
        self.environment.events.request.fire(
            request_type="SSE", name="流式对话·整流时长(演示流)",
            response_time=full_ms, response_length=0,
            exception=None if ok else RuntimeError("流未正常完成"), context={},
        )
        if first_event_ms is not None:
            self.environment.events.request.fire(
                request_type="SSE", name="流式对话·首事件时延",
                response_time=first_event_ms, response_length=0, exception=None, context={},
            )
