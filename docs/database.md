# 数据库说明 v0.1

- `users`：用户主体；当前仅创建本地开发用户。
- `conversations`：会话，含 `user_id` 所有权字段与预留的 `project_id` 归属字段。
- `messages`：会话消息，通过 `conversation_id` 关联会话。

概念：
- ORM Model：Python 类与数据库表映射。
- Engine：数据库连接池入口。
- Session：工作单元，跟踪对象并提交事务。
- Repository：封装查询与写入。
- Alembic：数据库结构版本管理。

迁移命令（backend 目录）：
```powershell
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```
自动生成迁移后必须人工检查。
