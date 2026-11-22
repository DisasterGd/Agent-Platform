# 数据库说明 v0.4.2

- `users`：用户主体；当前仅创建本地开发用户（`DEV_USER_ID`）。
- `projects`：v0.4 项目，会话与项目记忆的归属分组（`name` / `description` / `pinned`）。
- `conv_groups`：v0.4.1 用户自定义会话分组（仅存自定义分组；默认分组“项目/任务/未分组”由代码归类，不建记录）。
  `kind`=group 根级自定义分组 / task “任务”分区下的子分组（仅任务会话可归入，任务与普通会话不混用）。
- `conversations`：会话。`user_id` 所有权、`project_id` 归属（NULL=未分组）、v0.4.1 `group_id` 自定义分组归属（NULL=按默认归类）；
  v0.4 新增 `summary` + `summary_covered_id`：超长历史的自动压缩摘要（会话记忆，临时性质）；
  `kind`（chat/task）不占列，由任务表派生（存在绑定该会话的任务即为 task，列表用 selectinload 避免 N+1）。
- `messages`：会话消息（`group_id` + `variant_index` 版本链，重新生成保留历史版本）。
- `tasks` / `task_steps`：v0.3 任务与计划步骤（状态机 awaiting_approval/running/completed/failed/cancelled）。
- `memories`：v0.4 长期记忆（**系统级真记忆**：存库、可 CRUD、按作用域注入）。
  `scope`=global/project，`project_id` 仅 project 作用域使用；
  `category` 由模型归类（用户信息/用户偏好/项目/领域知识/其他）；
  `source`=explicit（用户要求记住）/auto（自动提炼）；`enabled` 支持停用而不删除。

概念：
- ORM Model：Python 类与数据库表映射。
- Engine：数据库连接池入口。
- Session：工作单元，跟踪对象并提交事务。
- Repository：封装查询与写入。
- Alembic：数据库结构版本管理（当前迁移链 0001–0008）。

迁移命令（backend 目录）：
```powershell
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```
自动生成迁移后必须人工检查（注意 MySQL 的 TEXT 列不允许 DEFAULT）。
