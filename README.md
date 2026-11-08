# Agent Platform v0.1

本地开发版 Agent 平台脚手架：React + TypeScript + Vite、FastAPI、MySQL、SQLAlchemy 2.x、Alembic、SSE。

## 当前已实现（v0.1）

- React 聊天工作台与会话列表，SSE 流式输出
- FastAPI 健康检查、会话 CRUD、消息读取、`POST /api/chat/stream` 流式回复
- MySQL ORM 模型：User / Conversation / Message（预留 `project_id` 归属字段）
- Repository / Service / Agent Core / Model 适配器分层
- OpenAI 兼容模型适配器（默认 DeepSeek），未配置 Key 时回退到本地演示回复
- Alembic 首次迁移、数据库检查与开发用户初始化脚本

当前开发用户 ID 仅用于本地单用户开发，不是身份认证；公网部署前必须实现真实认证和服务端权限校验。

## 环境要求

| 组件 | 版本 |
| --- | --- |
| Windows | 10/11 |
| Python | **3.11 及以上（强烈建议 3.12）** |
| Node.js | 20.19+ 或 22.12+（本机 24.x 已满足） |
| MySQL | 8.x |
| Git | 任意 |

> ⚠️ **重要**：本项目要求 Python 3.11+。如果你的电脑只有 Python 3.9（本仓库当前检测到的情况），后端**无法运行**。请先安装 Python 3.12。

### 安装 Python 3.12（手动步骤，详细）

1. 打开微软商店（Microsoft Store），搜索 "Python 3.12"，点击安装；**或**到 https://www.python.org/downloads/windows/ 下载 "Python 3.12.x Windows installer (64-bit)"。
2. 运行安装包时，**务必勾选 "Add python.exe to PATH"**，再点 "Install Now"。
3. 安装完成后，**新开一个 PowerShell** 验证：
   ```powershell
   py -0p
   ```
   应看到一行 `-3.12-64  ...`。
4. 之后所有后端命令用 `py -3.12` 代替 `python`。

> 本仓库根目录有一个旧的 `.venv`（Python 3.9），可以删除：`Remove-Item -Recurse -Force .venv`。下面会在 `backend/` 下重新创建 3.12 的虚拟环境，两者互不影响。

## 1. 创建数据库（手动，一次性）

在 MySQL 客户端执行（替换密码）：

```sql
CREATE DATABASE agent_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'agent_user'@'localhost' IDENTIFIED BY '请替换为强密码';
GRANT ALL PRIVILEGES ON agent_platform.* TO 'agent_user'@'localhost';
FLUSH PRIVILEGES;
```

## 2. 配置环境变量（手动，一次性）

在**项目根目录**（`Agent-Platform/`）执行：

```powershell
Copy-Item .env.example .env
```

用记事本或 VS Code 打开 `.env`，修改两处：

1. `DATABASE_URL` 里的 `password` 换成第 1 步设置的密码（密码含 `@ : / #` 等字符需 URL 编码）。
2. `LLM_API_KEY=` 填入你的 DeepSeek API Key（https://platform.deepseek.com 申请）。**不填也能跑**，只是回复是本地演示文本。

`.env` 已被 `.gitignore` 忽略，**不要提交**。

## 3. 启动后端（手动）

在项目根目录，**新开一个 PowerShell**：

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
alembic upgrade head
python ..\scripts\init_db.py
uvicorn apps.api.main:app --reload
```

> 如果 PowerShell 提示“禁止运行脚本”，执行：
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
> 再重新激活虚拟环境。也可以不激活，直接用 `.\.venv\Scripts\python.exe -m ...` 运行每条命令。

说明：

- `alembic upgrade head` 创建 `users` / `conversations` / `messages` 三张表。
- `init_db.py` 会补一个开发用户（id=1），并做一次幂等的建表兜底。
- `uvicorn apps.api.main:app --reload` 启动后端，**必须在 `backend` 目录下执行**。

后端就绪后可访问：

- 根路径：http://127.0.0.1:8000/
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health
- 数据库检查：http://127.0.0.1:8000/api/health/database

## 4. 启动前端（手动）

**再开一个 PowerShell**，在项目根目录：

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 http://127.0.0.1:5173/ 。

前端通过 Vite 把 `/api` 代理到 `http://127.0.0.1:8000`，所以开发时后端要在跑。

## 5. 验证（测试方法）

1. 确认 MySQL 服务已启动。
2. 后端启动后访问 `/api/health/database`，应返回 `{"status":"ok","database":"connected"}`。
3. 前端“新建会话”，输入一句话发送，应看到流式打字效果。
4. 刷新页面，会话和消息应仍在（说明已写入 MySQL）。
5. 填了 `LLM_API_KEY` 后重启后端，再发送消息，回复将来自真实模型。

## 6. Git

```powershell
git add .
git commit -m "chore: initialize agent platform"
git branch -M main
git remote add origin <GitHub 仓库地址>
git push -u origin main
```

如果本地目录已经是克隆下来的仓库，不要再次 `git init`。

## 目录结构（关键部分）

```text
backend/
  apps/api/                 FastAPI 入口与路由
  src/agent_platform/       核心库（config / core / models / repositories / services / infrastructure ...）
  migrations/               Alembic 迁移
  pyproject.toml            后端依赖（pip install -e ".[dev]"）
frontend/                   React + TypeScript 前端
scripts/                    check_db.py / init_db.py
.env.example                环境变量模板
```

## 重要架构约束

- React 不直接连接 MySQL；只通过 HTTP/SSE 调用 FastAPI。
- FastAPI 路由负责输入输出；业务逻辑放 Service。
- Repository 封装数据库读写；Session 按请求创建和关闭。
- Agent Core 不依赖 FastAPI Request/Response，保持可独立演进。
- 云端版本必须替换开发身份依赖，增加认证、权限、限流、HTTPS 和密钥管理。
