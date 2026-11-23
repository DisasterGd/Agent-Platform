# 架构说明

```text
React + TypeScript（侧边栏：新聊天/搜索/项目 + 分组分区 · 搜索弹窗 · 项目弹窗 · 聊天/任务双界面 · 任务卡片 · 思考过程面板 · 设置/记忆页）
       | HTTP / SSE
       v
FastAPI routes（chat / tasks / projects / groups / search / memories / files / library / settings / auth / health）
       v
Services (业务用例: chat_service · task_service · project_service · group_service · search_service · memory_service · settings_service · library_service)
       |                                   |
       v                                   v
Agent Core（agent 工具循环 · planner · runner · context · events）
Memory（v0.4: manager 门面 · conversation 压缩 · long_term 提炼/注入）
Models / Tools / Infrastructure(search · generation · storage · attachments · filetypes 类型词典 · model_discovery 模型探测)
       v
Repositories（唯一 DB 访问）
       v
SQLAlchemy Session -> MySQL
```

约束：前端不访问数据库；路由层不堆复杂业务；Agent Core 与 Memory 模块不依赖 FastAPI Request/Response；
Repository 封装数据读写；Session 按请求创建和关闭；用户归属必须由服务端认证身份决定。

v0.4.1 工作台结构：
- **聊天与任务是两个独立界面**（顶栏切换），共用同一条侧边栏信息栏；任务界面走 `/api/tasks` 全量列表，
  任务的计划审阅、执行、结果都在任务界面完成，结果同时写回会话（“任务”默认分组自动收纳这类会话）。
- **分组归类由代码完成**：任务子分组/自定义分组（conv_groups，kind=task 归入“任务”分区、kind=group 根级）
  → 项目 → 任务（由任务表派生 kind）→ 未分组；任务会话与普通会话的分组归属互不混用；
  搜索（`/api/search`）提供 对话 / 任务 / 项目 / 分组 四个筛选维度。

三级记忆（v0.4）：
- **会话记忆**（临时）：`messages` + `conversations.summary` 自动压缩，随会话删除；
- **项目记忆 / 全局记忆**（持久）：`memories` 表按 `scope` 区分，检索先过滤作用域；
  构建上下文时由 `MemoryManager` 注入系统提示词（有字符预算），轮末自动提炼、用户显式"记住"优先；
  与 CLAUDE.md 式静态文档不同——它是可查看、可编辑、可启停、可删除的数据库记录。

文件与资料库（v0.5）：
- **磁盘是唯一事实来源，`file_assets` 只回答“哪个文件是什么、归谁”**：一行对应一个文件，
  `stored_name` 是磁盘真实名（不可变，历史链接因此永不失效），`filename` 是显示名（可重命名，下载即用新名）。
- **类型判定只有一处**：`infrastructure/filetypes` 是后缀/MIME/归类（code·document·image·audio·video·archive）
  的唯一词典，上传正文提取、`write_file` 白名单、资料库页签三处共用，不再各写一份清单。
  文本识别为“后缀白名单 + 内容嗅探”双保险，所以 `Makefile`、`.env.local`、无后缀文本也能读。
- **登记有三条入口，全部幂等**（`(category, stored_name)` 唯一）：
  上传接口 → `source=upload`；工具产出的 `artifact_ready` 事件 → 由 Chat/Task 服务层登记（`source=chat/task`，
  带上会话与项目归属）；资料库首次打开时扫描磁盘 → 补齐历史文件（`source=library`）。
  工具层保持纯函数、不碰数据库：登记发生在服务层观察事件时，符合分层约束。
- **上传归属分两步**：上传那一刻还不知道会进哪个会话，先登记为未归类；消息落库时按附件 URL 回填
  `conversation_id` / `project_id`（项目联动由此而来，也可在资料库里手动改）。
- 生成能力分工：`generate_file` 把 Markdown 渲染成文档（md/docx/pdf）；`write_file` 按模型给的文件名
  原样写出文本/代码/配置（文件名即用途声明）；`create_zip` 打包多文件（内联内容 + 引用本轮已生成的文件）。
  后两者都受服务端校验：后缀白名单、路径清洗（拒绝绝对路径与 `..`）、体积与条目上限。

模型配置（v0.2 预设起步 → v0.5.1 增强，v0.6 多模型管理的前身）：
- **两级配置，单一事实来源是设置页**：`data/settings.json`（每次请求读取，改完即生效）优先于 `.env`（启动时加载，作兜底）；
  两处都没 API Key 时回退本地演示模式。API Key 目前**明文**存于 settings.json（`data/` 已 gitignore），加密存储留待 v0.7/v0.8 与账号体系统一考虑。
- **预设 = 2026-11 在服型号的精选清单**（`PRESETS.models` / `vision_models` 即设置页下拉候选）；
  `POST /api/settings/discover-models` 可向**用户自己填写的** Base URL 发 OpenAI 兼容 `GET /models`，实测该 Key 实时可调用列表并并入下拉——
  预设清单过期也不影响可用性，这就是“随官方同步”的零维护通道。
- **视觉模型是独立角色的 ChatModel（识图）**：`_enrich` 阶段用 `create_vision_model()` 把图片描述为中文文本、拼进用户消息，
  主模型（可为纯文本模型）再带着这段描述进入工具循环——一轮之内“识图 → 推理”**顺序协作**，并非多模型并行；二者共用同一 Base URL 与 Key。
