# Agent Platform v0.2

本地优先的智能 Agent 平台：React + TypeScript + Vite、FastAPI、MySQL、SQLAlchemy 2.x、Alembic、SSE，默认接入 DeepSeek（OpenAI 兼容接口）。

## 当前已实现

**v0.1（基础）**

- React 聊天工作台与会话列表，SSE 流式输出
- FastAPI 健康检查、会话 CRUD、消息读取、`POST /api/chat/stream` 流式回复
- MySQL ORM 模型：User / Conversation / Message（预留 `project_id` 归属字段）
- Repository / Service / Agent Core / Model 适配器分层
- OpenAI 兼容模型适配器（默认 DeepSeek），未配置 Key 时回退到本地演示回复
- Alembic 迁移、数据库检查与开发用户初始化脚本

**v0.2（工具调用）**

- Agent 工具调用循环（function calling）：模型可自动决定何时调用工具，最多 6 轮
- 联网搜索工具 `web_search`：DuckDuckGo（默认）/ Tavily / Bing，改 `.env` 即可切换
- 文件生成工具 `generate_file`：把模型输出的 Markdown 导出为 md / docx（Word）/ pdf
- 文件与图片上传/下载：`POST /api/files`、`GET /api/files/{category}/{name}`
- 多模型供应商登记入口 `register_model_provider`，消息结构已支持图片（为多模态预留）

当前开发用户 ID 仅用于本地单用户开发，不是身份认证；公网部署前必须实现真实认证和服务端权限校验。

## 环境要求

| 组件 | 版本 |
| --- | --- |
| Windows | 10/11 |
| Python | **3.11 及以上（建议 3.12）** |
| Node.js | 20.19+ 或 22.12+ |
| MySQL | 8.x |
| Git | 任意 |

## 1. 安装 Python 3.12

1. 到 https://www.python.org/downloads/windows/ 下载 "Python 3.12.x Windows installer (64-bit)"。
2. 运行安装包时**勾选 "Add python.exe to PATH"**，再点 "Install Now"。
3. 新开 PowerShell 验证：`py -0p`，应看到 `-3.12-64`。

## 2. 创建虚拟环境（仓库根目录）

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> 如果 PowerShell 提示"禁止运行脚本"，执行 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 后重试；也可以不激活，直接用 `.\.venv\Scripts\python.exe` 运行每条命令。

## 3. 安装后端依赖（在 backend 目录下）

```powershell
cd backend
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

依赖包括 FastAPI、SQLAlchemy、openai、httpx、ddgs（联网搜索）、python-docx、reportlab（文档生成）、python-multipart（文件上传）等。

## 4. 创建数据库（一次性）

在 MySQL 客户端执行（替换密码）：

```sql
CREATE DATABASE agent_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'agent_user'@'localhost' IDENTIFIED BY '请替换为强密码';
GRANT ALL PRIVILEGES ON agent_platform.* TO 'agent_user'@'localhost';
FLUSH PRIVILEGES;
```

## 5. 配置环境变量（一次性）

在**项目根目录**执行：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

1. `DATABASE_URL` 里的 `password` 换成第 4 步的密码（密码含 `@ : / #` 等字符需 URL 编码）。
2. `LLM_API_KEY=` 填入 DeepSeek API Key（https://platform.deepseek.com 申请）。**不填也能跑**，只是回复是本地演示文本。
3. （可选）联网搜索：默认 `SEARCH_PROVIDER=duckduckgo` 零配置；国内建议改用 Bing 并填 `SEARCH_API_KEY`，见下文「联网搜索」。

`.env` 已被 `.gitignore` 忽略，**不要提交**。

## 6. 初始化数据库并启动后端

```powershell
cd backend
python -m alembic upgrade head
python ..\scripts\init_db.py
python run.py
```

- `alembic upgrade head` 创建 `users` / `conversations` / `messages` 三张表。
- `init_db.py` 补一个开发用户（id=1）并做幂等建表兜底。
- `run.py` 一键启动后端并同时托管已构建的 `frontend/dist`，自动打开浏览器。

就绪后访问：

- 根路径：http://127.0.0.1:8000/
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health
- 数据库检查：http://127.0.0.1:8000/api/health/database

## 7. 启动前端

**另开一个 PowerShell**，在项目根目录：

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 http://127.0.0.1:5173/ 。前端通过 Vite 把 `/api` 代理到 `http://127.0.0.1:8000`。

> 生产/本地一体化运行：`cd frontend && npm run build` 产出 `dist/`，之后只需启动后端，`run.py` 会把前端页面托管在 8000 端口。

## 8. 验证

1. 确认 MySQL 服务已启动。
2. 后端启动后访问 `/api/health/database`，应返回 `{"status":"ok","database":"connected"}`。
3. 前端"新建会话"发送一句话，应看到流式打字效果；刷新后会话与消息仍在（已写 MySQL）。
4. 填了 `LLM_API_KEY` 后重启后端，回复来自真实模型。
5. 工具调用：发送「帮我查一下今天的热点新闻」应触发联网搜索；发送「写一份周报并导出成 PDF」应触发文件生成并出现下载卡片。

## 联网搜索（重要）

默认 `SEARCH_PROVIDER=duckduckgo` 零配置，但**国内网络常不可达**。生产使用建议切到 Bing（国内可直连）：

```env
SEARCH_PROVIDER=bing
SEARCH_API_KEY=你的Bing搜索API Key   # Azure 门户免费申请
```

也可用 `SEARCH_PROVIDER=tavily`（面向 LLM 的搜索 API，国内可能需要代理）。切换只改 `.env`，无需改代码。

## 目录结构（关键部分）

```text
backend/
  apps/api/                  FastAPI 入口与路由（含文件上传/下载）
  src/agent_platform/        核心库
    core/                    Agent 工具调用循环、上下文、事件
    models/                  大模型适配层（供应商登记表）
    tools/                   工具注册表 + 内置工具（web_search / generate_file）
    services/                业务用例层
    repositories/            数据访问层
    infrastructure/          database / storage / search / generation
  migrations/                Alembic 迁移
  pyproject.toml             后端依赖（pip install -e ".[dev]"）
frontend/                    React + TypeScript 前端
scripts/                     check_db.py / init_db.py
docs/                        architecture / database / api
data/                        上传与生成的文件（gitignored）
.env.example                 环境变量模板
```

## 重要架构约束

- React 不直接连接 MySQL；只通过 HTTP/SSE 调用 FastAPI。
- FastAPI 路由负责输入输出；业务逻辑放 Service。
- Repository 封装数据库读写；Session 按请求创建和关闭。
- Agent Core 不依赖 FastAPI Request/Response，保持可独立演进。
- 云端版本必须替换开发身份依赖，增加认证、权限、限流、HTTPS 和密钥管理。
