# API v0.4.5

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/health` | API 健康检查 |
| GET | `/api/health/database` | 数据库连接检查 |
| GET | `/api/conversations?project_id=` | 会话列表（`project_id` 省略=全部，`none`=未分组，数字=指定项目；输出含 `group_id` 与 `kind`=chat/task） |
| POST | `/api/conversations` | 创建会话（可带 `project_id`） |
| PATCH | `/api/conversations/{id}` | 重命名 / 置顶 / 添加至项目、分组（显式传 `project_id`/`group_id`，null=移出） |
| DELETE | `/api/conversations/{id}` | 删除会话（级联删除消息与任务） |
| GET | `/api/conversations/{id}/messages` | 读取消息（含版本链全部变体） |
| POST | `/api/chat/stream` | SSE 流式回复（工具调用、附件、记忆注入） |
| POST | `/api/chat/regenerate` | 重新生成最后一轮回复（版本链追加） |
| GET | `/api/search?q=&scope=` | v0.4.1 全局搜索（scope=all/conversations/tasks/projects/groups；会话带最新消息摘要，任务带步骤进度） |
| GET/POST/PATCH/DELETE | `/api/groups[/{id}]` | v0.4.1 自定义分组：列表 / 新建（`kind=group` 根级 / `kind=task` 任务子分组）/ 重命名 / 删除（会话退回默认归类） |
| GET/POST/PATCH/DELETE | `/api/projects[/{id}]` | v0.4 项目：列表 / 新建 / 重命名、改描述、置顶 / 删除 |
| GET/POST/PATCH/DELETE | `/api/memories[/{id}]` | v0.4 记忆：查询（`scope`、`project_id` 过滤）/ 手动添加 / 编辑、启停 / 删除 |
| POST | `/api/files` | 上传文件/图片（multipart） |
| GET | `/api/files/{category}/{name}` | 下载上传/生成的文件（可读文件名） |
| GET/PUT | `/api/settings` | 模型配置 + `memory_enabled` 自动记忆开关 |
| POST | `/api/tasks` | v0.3 创建任务（规划步骤，`awaiting_approval`；v0.4.1 可带 `project_id`） |
| PUT | `/api/tasks/{id}/steps` | 审阅阶段编辑计划 |
| POST | `/api/tasks/{id}/execute` | SSE 流式执行（`plan_created`/`step_*`/`task_completed`） |
| POST | `/api/tasks/{id}/cancel` | 取消任务 |
| DELETE | `/api/tasks/{id}` | v0.4.1 删除任务记录（不影响已产生的会话） |
| GET | `/api/tasks` / `/api/tasks?conversation_id=` / `/api/tasks/{id}` | 任务查询（缺省返回全部，供任务界面） |

## 聊天流（`POST /api/chat/stream`）

请求体：
```json
{"conversation_id": 1, "content": "帮我查一下今天的天气，并生成一份报告", "attachments": []}
```

SSE 事件：`task_started`、`text_delta`、`tool_started`、`tool_completed`、`artifact_ready`、
`context_compressed`、`memory_saved`、`task_completed`、`error`。

- `text_delta`：`{"content": "..."}` 增量文本
- `tool_started` / `tool_completed`：`{"name": "web_search"}` 工具调用开始/结束
- `artifact_ready`：`{"filename", "stored_name", "url", "format", "content_type"}` 生成的可下载文件（显示名=磁盘名=URL 尾段，重名自动加 ` (2)`）
- `context_compressed`：`{"count": n}` v0.4 超长历史已自动压缩 n 条为摘要（会话记忆）
- `memory_saved`：`{"items": [{"title","scope","category","source"}]}` v0.4 本轮写入的全局/项目记忆

## 内置工具

| 工具 | 说明 |
|---|---|
| `web_search` | 联网搜索（provider=auto：DuckDuckGo → Bing 网页抓取兜底，可换 bing/tavily） |
| `fetch_url` | 读取搜索结果链接正文 |
| `generate_file` | 生成 md / docx / pdf 文件 |
