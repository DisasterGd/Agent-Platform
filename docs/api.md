# API v0.1

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/health` | API 健康检查 |
| GET | `/api/health/database` | 数据库连接检查 |
| GET | `/api/conversations` | 会话列表 |
| POST | `/api/conversations` | 创建会话 |
| GET | `/api/conversations/{id}/messages` | 读取消息 |
| POST | `/api/chat/stream` | SSE 流式演示回复 |

请求体示例：
```json
{"conversation_id": 1, "content": "你好"}
```
SSE 事件：`task_started`、`text_delta`、`task_completed`、`error`。
