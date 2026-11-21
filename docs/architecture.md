# 架构说明

```text
React + TypeScript（会话列表 + 项目栏 + 任务卡片 + 思考过程面板 + 设置/记忆页）
       | HTTP / SSE
       v
FastAPI routes（chat / tasks / projects / memories / files / settings / auth / health）
       v
Services (业务用例: chat_service · task_service · project_service · memory_service · settings_service)
       |                                   |
       v                                   v
Agent Core（agent 工具循环 · planner · runner · context · events）
Memory（v0.4: manager 门面 · conversation 压缩 · long_term 提炼/注入）
Models / Tools / Infrastructure(search · generation · storage · attachments)
       v
Repositories（唯一 DB 访问）
       v
SQLAlchemy Session -> MySQL
```

约束：前端不访问数据库；路由层不堆复杂业务；Agent Core 与 Memory 模块不依赖 FastAPI Request/Response；
Repository 封装数据读写；Session 按请求创建和关闭；用户归属必须由服务端认证身份决定。

三级记忆（v0.4）：
- **会话记忆**（临时）：`messages` + `conversations.summary` 自动压缩，随会话删除；
- **项目记忆 / 全局记忆**（持久）：`memories` 表按 `scope` 区分，检索先过滤作用域；
  构建上下文时由 `MemoryManager` 注入系统提示词（有字符预算），轮末自动提炼、用户显式"记住"优先；
  与 CLAUDE.md 式静态文档不同——它是可查看、可编辑、可启停、可删除的数据库记录。
