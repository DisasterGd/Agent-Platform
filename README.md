# Agent Platform v0.1

本地开发版 Agent 平台脚手架：React + TypeScript + Vite、FastAPI、MySQL、SQLAlchemy 2.x、Alembic、SSE。

## 当前包含

- React 聊天工作台与会话列表
- FastAPI 健康检查、会话 CRUD 基础接口、SSE 消息接口
- MySQL ORM 模型：User / Conversation / Message
- Repository 与 Service 分层
- Alembic 首次迁移
- 本地开发用户初始化脚本

当前回复是演示文本流，不是真实模型调用。当前开发用户 ID 仅用于本地单用户开发，不是身份认证；公网部署前必须实现真实认证和服务端权限校验。

## 环境

Windows 10/11、Python 3.11+（建议 3.12）、Node.js 20.19+ 或 22.12+、MySQL 8.x、Git。

## 1. 创建数据库

在 MySQL 客户端执行（替换密码）：

```sql
CREATE DATABASE agent_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'agent_user'@'localhost' IDENTIFIED BY '请替换为强密码';
GRANT ALL PRIVILEGES ON agent_platform.* TO 'agent_user'@'localhost';
FLUSH PRIVILEGES;
```

## 2. 配置环境变量

在项目根目录执行：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，将 `DATABASE_URL` 中的密码替换为刚设置的密码。密码若含 `@ : / #` 等字符，需要 URL 编码。不要提交 `.env`。

## 3. 启动后端

在项目根目录：

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
alembic upgrade head
python ..\scripts\bootstrap_dev_user.py
uvicorn agent_platform.main:app --reload
```

后端：[http://127.0.0.1:8000](http://127.0.0.1:8000/) API 文档：http://127.0.0.1:8000/docs 健康检查：http://127.0.0.1:8000/api/health 数据库检查：http://127.0.0.1:8000/api/health/database

如果 PowerShell 不允许激活虚拟环境，可直接使用 `.venv\Scripts\python.exe -m ...` 执行对应命令。

## 4. 启动前端

新开一个 PowerShell 窗口，在项目根目录：

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 [http://127.0.0.1:5173](http://127.0.0.1:5173/)。

## 5. 测试

1. 确保 MySQL 服务运行。
2. 运行 Alembic 迁移和开发用户初始化。
3. 启动后端，检查 `/api/health/database`。
4. 启动前端，新建会话并发送消息。
5. 刷新页面，检查会话和消息是否仍然存在。

## 6. Git

```powershell
git init
git add .
git commit -m "chore: initialize agent platform"
git branch -M main
git remote add origin <GitHub仓库地址>
git push -u origin main
```

如果本地目录已经是克隆下来的仓库，不要再次 `git init`。

## 重要架构约束

- React 不直接连接 MySQL。
- FastAPI 路由负责 HTTP 输入输出；业务逻辑放 Service。
- Repository 封装数据库读写；Session 按请求创建和关闭。
- Agent Core 后续保持与 FastAPI、数据库解耦。
- 云端版本必须替换开发身份依赖，增加认证、权限、限流、HTTPS 和密钥管理。