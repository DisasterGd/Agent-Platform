# API v0.2

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/health` | API 健康检查 |
| GET | `/api/health/database` | 数据库连接检查 |
| GET | `/api/conversations` | 会话列表 |
| POST | `/api/conversations` | 创建会话 |
| PATCH | `/api/conversations/{id}` | 重命名会话 |
| GET | `/api/conversations/{id}/messages` | 读取消息 |
| POST | `/api/chat/stream` | SSE 流式回复（支持工具调用） |
| POST | `/api/files` | 上传文件/图片（multipart） |
| GET | `/api/files/{category}/{name}` | 下载上传/生成的文件 |

## 聊天流（`POST /api/chat/stream`）

请求体：
```json
{"conversation_id": 1, "content": "帮我查一下今天的天气，并生成一份报告"}
```

SSE 事件：`task_started`、`text_delta`、`tool_started`、`tool_completed`、`artifact_ready`、`task_completed`、`error`。

- `text_delta`：`{"content": "..."}` 增量文本
- `tool_started` / `tool_completed`：`{"name": "web_search"}` 工具调用开始/结束
- `artifact_ready`：`{"filename", "url", "format", "content_type"}` Agent 生成的可下载文件

## 内置工具

| 工具 | 说明 |
|---|---|
| `web_search` | 联网搜索（DuckDuckGo / Tavily / Bing，由 `SEARCH_PROVIDER` 决定） |
| `generate_file` | 生成 md / docx / pdf 文件 |
