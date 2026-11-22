# API v0.5.0

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
| POST | `/api/files` | 上传文件/图片（multipart，≤20MB，不限类型；文本/代码可直接被模型读取）→ 同时登记资料库，返回含 `asset_id`/`kind`/`size_label` |
| GET | `/api/files/{category}/{name}` | 下载/预览文件；`?inline=1` 改为浏览器内打开（图像、音视频）；显示名取资料库记录，重命名后下载即得新名 |
| GET | `/api/library/assets` | v0.5 资料库列表：`project_id`（省略=全部，`none`=未归类，数字=项目）、`kind`、`category`、`source`、`q`、`limit/offset`；返回 `items` + `matched`（筛选数）/ `total`（全库）/ `kinds` / `categories` / `projects` 计数 |
| POST | `/api/library/scan` | v0.5 存量扫描：把磁盘上有、库里没有的历史文件登记进资料库（幂等） |
| GET | `/api/library/assets/{id}` | 单条资料详情 |
| GET | `/api/library/assets/{id}/preview` | 预览：`preview` = text（含 `content`/`truncated`/`line_count`）/ image / audio / video / archive（含 `entries`）/ binary / missing |
| PATCH | `/api/library/assets/{id}` | 重命名（缺后缀自动补回原后缀）/ 移动项目（显式传 `project_id`，null=移出项目） |
| DELETE | `/api/library/assets/{id}` | 删除条目（`?keep_file=true` 只移除记录、保留磁盘文件） |
| POST | `/api/library/assets/batch-delete` | 批量删除 `{ids, keep_files}` |
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
- `artifact_ready`：`{"filename", "stored_name", "url", "format", "content_type", "category", "size", "kind", "tool"}`
  生成的可下载文件（显示名=磁盘名=URL 尾段，重名自动加 ` (2)`）；`tool` 由 Agent 核心补写，
  服务层据此把文件登记进资料库并带上会话/项目归属（v0.5）
- `context_compressed`：`{"count": n}` v0.4 超长历史已自动压缩 n 条为摘要（会话记忆）
- `memory_saved`：`{"items": [{"title","scope","category","source"}]}` v0.4 本轮写入的全局/项目记忆

## 内置工具

| 工具 | 说明 |
|---|---|
| `web_search` | 联网搜索（provider=auto：DuckDuckGo → Bing 网页抓取兜底，可换 bing/tavily） |
| `fetch_url` | 读取搜索结果链接正文 |
| `generate_file` | Markdown 导出 md / docx / pdf 文档 |
| `write_file` | v0.5 按指定文件名原样写出文本/代码/配置（后缀白名单 + 路径清洗，二进制拒绝） |
| `create_zip` | v0.5 把多个文件打成 zip：`files` 内联内容 + `from_files` 引用本轮已生成的文件 |
