# Agent Platform v0.4.3

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

- Agent 工具调用循环（function calling）：模型自动决定何时调用工具，最多 6 轮
- 内置工具：`web_search`（联网搜索）、`fetch_url`（抓取搜索结果正文）、`generate_file`（Markdown 导出 md / docx / pdf）
- 文件与图片上传/下载：`POST /api/files`、`GET /api/files/{category}/{name}`
- 附件接入模型：文档正文提取、图片视觉理解（可配置独立的视觉模型）
- 设置界面：模型预设 / 自定义 Base URL / API Key / 视觉模型；浅色与深色主题
- 会话管理：置顶、重命名、删除、搜索；消息复制；编辑提问
- **重新生成版本链**：每次重新生成/编辑都不再删除旧内容，按版本链保留（`group_id` + `variant_index`），气泡上 `‹ n/N ›` 左右翻页回看
- Markdown 富渲染：LaTeX 公式（KaTeX，含定界符归一化与防错乱保护）、Mermaid 流程图、代码高亮 + 复制
- 多模型供应商登记入口 `register_model_provider`，消息结构已支持图片（为多模态预留）

**v0.3（任务规划与执行）**

- 输入框「任务模式」显式开关：发送目标后先由 **Planner** 生成结构化步骤计划（JSON，≤6 步）
- **先审阅再执行**：任务卡片上可编辑、增删步骤，确认后由 **Runner** 逐步执行，全程 SSE 流式汇报
- 每一步的执行会带上"总体目标 + 完整计划 + 前序步骤结果"，复用 v0.2 的工具循环（可搜索、可生成文件）
- **程序化校验**（模型声称完成 ≠ 真的完成）：步骤产出非空、声明生成的文件必须真实存在于磁盘，否则该步骤判失败并停止
- 任务与步骤持久化：新增 `tasks` / `task_steps` 表，状态机 `awaiting_approval → running → completed / failed / cancelled`，支持计划编辑、取消、失败重试
- 执行结果写回会话，后续聊天可引用任务产出；刷新页面可恢复未收尾的任务卡片
- 任务进度 UI：步骤状态点（待执行/执行中/完成/失败）、当前步骤流式输出、产物文件下载卡片

**v0.3.1（任务可靠性与生成体验修复）**

- **修复“产出文件校验”误判**：生成文件落盘使用唯一存储名（uuid），校验改为核对真实的存储文件；此前凡调用 `generate_file` 的步骤都会被判“产出文件校验失败：找不到 xxx.md”，导致任务几乎必败
- **生成阶段即建会话**：聊天发送、任务规划/执行开始时会话就已创建并绑定；任务失败或被中断时，目标与已完成步骤的结果也会写入会话，不再“消失、没有任何记录”
- 回复流被中断（切走/报错/断开）时，已生成的部分连同“被中断”说明一并落库，切回会话即可查看
- **“思考过程”动态展示**：输入区上方的滚动面板实时显示模型正在做什么（搜索 / 抓取 / 生成文件 / 逐步执行），每步一行、循环上下滚动，滚动速度与实际生成速度相关联；完成后“虚化”短暂停留后自动移除，内容仅存内存、不占磁盘
- 生成中：左侧会话栏对应行显示转圈动画；标题即时取消息内容截取（不再停留“新会话”），完成后由模型精炼
- 任务卡片当前步骤的实时输出跟随生成自动滚动到底部，并有打字光标与流光标签提示

**v0.3.2（文件可读命名）**

- `data/generated`（及 `data/uploads`）直接以**可读文件名**落盘：磁盘文件、产物卡片显示名、下载链接名三者一致（如 `报告.md`），方便直接在文件夹里翻阅查找
- 同名不覆盖，自动追加序号：`报告.md` → `报告 (2).md` → `报告 (3).md`
- 自动清洗 Windows 非法字符与保留设备名（`CON.txt` → `_CON.txt`），拒绝路径穿越但保留 `a..b.md` 这类合法名
- 历史 uuid 命名的旧文件不受影响，旧链接照常可下载

**v0.4（三级记忆系统）**

- **全局记忆**：存数据库 `memories` 表（系统级真记忆，可查/编/删/启停，非 CLAUDE.md 式静态文档）。
  每轮对话结束由模型自动提炼原子化记忆并自行归类（用户信息 / 用户偏好 / 项目 / 领域知识 / 其他）；
  用户说“请记住…”的内容以更高优先级落库并标记来源“用户要求记住”；同标题自动合并更新，不堆重复
- **项目记忆**：左侧新增项目栏——新建、重命名、置顶、删除（会话退回未分组、不删会话）；
  会话归属所选项目，构建上下文时“全局记忆 + 当前项目记忆”一并注入系统提示词（有字符预算）
- **会话记忆（自动压缩）**：上下文超过阈值（默认 9000 字）时，用模型总结能力把早期消息滚动压缩为摘要
  （`conversations.summary`），上下文 = 摘要 + 最近若干条原样消息；前端思考面板会提示“已压缩 n 条”
- **设置 → 记忆**：记忆可视化管理界面——按作用域切换、按类别分组、来源徽章、编辑/启停/两步确认删除、手动添加；
  “自动记忆”开关（关闭后停止提炼与注入，仍可手动管理）
- 记忆与压缩事件并入“思考过程”面板：`context_compressed`、`memory_saved`
- 新增迁移 `0006_memory`（projects / memories 表 + 会话摘要列）；任务执行器同样注入记忆

**v0.4.1（工作台重组：搜索 · 项目 · 分组 · 任务界面）**

- **侧栏自上而下改为“新聊天 / 搜索 / 项目”三个动作**：搜索与项目各自弹出独立窗口，会话列表区改为分组分区
- **搜索弹窗**：支持按“全部 / 对话 / 任务 / 项目 / 分组”筛选（`GET /api/search`）；命中会话的标题与消息正文、任务目标、项目与分组名称；
  每条结果带最近的相关信息（会话取最后一条消息摘要，任务带状态与步骤进度）；范围内没有命中时显示“「xx」中无结果”
- **项目弹窗**：双栏卡片网格展示全部项目（名称、描述、会话/任务数、最近活动）；新建、重命名、置顶、删除与“选中筛选”都在弹窗内完成
- **分组体系**：除用户**自定义分组**（新表 `conv_groups` + `conversations.group_id`，`/api/groups` CRUD）外，
  设置**默认分组**：项目、任务、未分组；归类由代码完成，优先级为 自定义分组 → 项目 → 任务 → 未分组，
  其中“任务”自动收纳任务模式产生的会话（由任务表派生 `kind=task`，无需手工归类）
- 会话“⋯”菜单新增**添加至项目 / 添加至分组**（子菜单只列自定义分组与项目，不含默认分组；移出同样在此操作）
- **任务模式升级为独立界面**：输入框的“任务模式”开关移除，顶栏提供“聊天 / 任务”切换；
  任务界面 = 左侧任务列表（状态筛选）+ 右侧计划审阅/执行/结果 + 底部目标输入；执行结果仍写回会话，可一键“在对话中查看”；
  聊天与任务来回切换时，左侧信息栏（会话与分组列表）保持不变
- 配套接口与迁移：新增 `0007_conv_groups`、`GET /api/tasks`（缺省返回全部任务）、`DELETE /api/tasks/{id}`、
  `PATCH /api/conversations/{id}` 支持显式 `project_id` / `group_id`（含 null=移出）；无 Key 时前端演示模式行为不变

**v0.4.2（分组体系细化：项目/任务子组别 · 菜单越界修复 · 分区全选）**

- “项目”分区下**每个具体项目是可展开/收起的子组别**（顶栏“项目”入口保留，用于查看全部项目）；“任务”分区支持挂
  `kind=task` 的**任务子分组**（`conv_groups.kind`，迁移 `0008_group_kind`）
- 菜单项“添加至分组”改为**移至分组**；归类互斥规则：
  - 任何会话都可**添加至/更换项目**，项目中的会话有**从项目中移除**；移入分组即离开项目，反之亦然
  - **任务会话不能移至普通自定义分组**，只能移至“任务”及其子分组（含“任务（直接归类）”一键退回）；普通会话不能移至任务分组
  - “移至分组”子菜单内可直接 **＋ 新建分组**并移入（按会话类型自动建 task 子分组或根级分组）
- 会话“⋯”菜单与子菜单改用 fixed 定位，可越出侧栏显示，**修复子菜单被侧栏裁切出屏的 bug**
- **多选**：每个分区（含项目子组别、任务子分组）头部新增全选复选框（部分选中显示半选态），一键勾选整组

**v0.4.3（多选右键批量 · 分组顺序固定 · 回到底部）**

- **右键批量菜单**：多选时对已选中会话右键弹出自定义应用内菜单（置顶 / 取消置顶 / 添加至项目 / 移至分组 / 删除），
  屏蔽浏览器原生右键菜单；单选右键同样可用。为避免过度分类，“添加至项目 / 移至分组”仅在**所有选中项位于同一（子）分组
  且同属一类（任务/普通）**时出现，右键子菜单同样遵循任务↔任务子分组、普通↔根级分组的互斥规则，并可就地新建分组批量移入
- 顶部多选条精简为“已选 N / 清空 + 右键提示”，原批量动作按钮全部迁移到右键菜单
- **分组顺序固定**：项目 → 任务 → 自定义分组（名称 A~Z）→ 未分组；新建自定义分组插在任务与未分组之间，不再出现在最上方；
  任务子分组同样按名称排序
- 聊天界面输入框上方新增**“回到底部”圆形按钮**（下箭头、居中、无文字），滚动离开底部约 120px 即出现，点击平滑回到底部

当前开发用户 ID 仅用于本地单用户开发，不是身份认证；公网部署前必须实现真实认证和服务端权限校验。

## 环境要求

| 组件 | 版本 |
| --- | --- |
| Windows | 10/11 |
| Python | **3.11 及以上（当前 `.venv` 为 3.12）** |
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
2. `LLM_API_KEY=` 填入 DeepSeek API Key（https://platform.deepseek.com 申请）。**不填也能跑**，聊天与任务都会退回本地演示文本。
3. （可选）联网搜索：默认 `SEARCH_PROVIDER=auto` 零配置，见下文「联网搜索」。
4. （可选）API Key、模型、视觉模型也可以启动后在「设置」界面里改，优先级高于 `.env`（存于 `data/settings.json`）。

`.env` 已被 `.gitignore` 忽略，**不要提交**。

## 6. 初始化数据库并启动后端

```powershell
cd backend
python -m alembic upgrade head
python ..\scripts\init_db.py
python run.py
```

- `alembic upgrade head` 创建 `users` / `conversations` / `messages` / `tasks` / `task_steps` / `projects` / `memories` / `conv_groups` 八张表（消息版本链、任务、记忆与分组表由迁移补齐）。
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
3. 前端打开即是主界面（不自动选中会话）；输入一句话发送后，侧边栏才会出现该会话；刷新后会话与消息仍在（已写 MySQL）。
4. 填了 `LLM_API_KEY` 后重启后端，回复来自真实模型。
5. 工具调用：发送「帮我查一下今天的热点新闻」应触发联网搜索；发送「写一份周报并导出成 PDF」应触发文件生成并出现下载卡片。
6. 重新生成：对最后一轮回复点「重新生成」，旧回答保留，气泡上出现 `‹ 2/2 ›` 可翻页回看。
7. 任务界面（v0.4.1）：点顶栏「任务」切到任务界面，在底部输入一个多步目标（如「调研三款 AI 搜索产品，对比功能并写成 Word 报告」），先出现可编辑的步骤计划，点「执行计划」后逐步点亮状态，完成后可看到最终总结，点「在对话中查看」回到会话继续追问；期间左侧信息栏不变。
8. 记忆（v0.4）：对话里说「请记住我以后都用中文写注释」，思考面板应提示写入记忆；打开「设置 → 记忆」能看到该条（来源=用户要求记住）；新开一个会话提问时，模型应表现出已知该偏好。在侧栏「项目」弹窗新建项目并选中后，新会话与新任务归属该项目，其项目记忆只在选中时生效。
9. 分组与搜索（v0.4.1）：会话“⋯”→ 添加至分组，先在「分组」标题旁 ＋ 新建自定义分组再选择它，会话行应移入该分组分区；「添加至项目」子菜单只列项目、分组子菜单不出现“项目/任务/未分组”默认分组；任务模式产生的会话自动出现在「任务」分区；侧栏「搜索」输入关键词验证各筛选标签与“「xx」中无结果”提示。

## 联网搜索

默认 `SEARCH_PROVIDER=auto`：走 DuckDuckGo，失败时自动回退 Bing 网页抓取，零配置、国内多数网络可用。也可显式指定：

```env
SEARCH_PROVIDER=duckduckgo   # 仅 DuckDuckGo
SEARCH_PROVIDER=bing_scrape  # 仅 Bing 网页抓取
SEARCH_PROVIDER=bing         # Bing 官方 API（需 SEARCH_API_KEY，Azure 申请）
SEARCH_PROVIDER=tavily       # Tavily（面向 LLM 的搜索 API，需 SEARCH_API_KEY）
```

切换只改 `.env`，无需改代码。

## 目录结构（关键部分）

```text
backend/
  apps/api/                  FastAPI 入口与路由（chat / tasks / projects / groups / search / memories / files / settings / auth / health）
  src/agent_platform/        核心库
    core/                    agent.py 工具循环 · planner.py 任务规划 · runner.py 任务执行 · events.py 事件词汇表 · context.py 上下文(摘要+记忆注入)
    memory/                  v0.4 三级记忆：manager 门面 · conversation 历史压缩 · long_term 提炼/归类/注入
    models/                  大模型适配层（供应商登记表）
    tools/                   工具注册表 + 内置工具（web_search / fetch_url / generate_file）
    services/                业务用例层（chat_service · task_service · project_service · group_service · search_service · memory_service · settings_service）
    repositories/            数据访问层（conversations · messages(版本链) · tasks · projects · groups · memories）
    infrastructure/          database / storage(可读命名+去重) / search / generation / attachments
  migrations/                Alembic 迁移（0001–0007）
  pyproject.toml             后端依赖（pip install -e ".[dev]"）
frontend/
  src/
    components/              Sidebar 侧栏（动作区+分组分区） · SearchModal 搜索弹窗 · ProjectsModal 项目弹窗 · TaskWorkspace 任务界面 · TaskCard 任务卡 · Markdown 富渲染 · ThinkingTicker 思考面板 · MemoryPanel 记忆管理 · ConfirmDialog 确认弹窗 · SettingsModal
    services/                api / chat(SSE) / tasks / projects / groups / search / memories / settings
    styles/                  设计令牌（浅色/深色）
    types/                   类型定义
scripts/                     check_db.py / init_db.py
docs/                        architecture / database / api
data/                        上传与生成的文件、settings.json（gitignored）
.env.example                 环境变量模板
```

## 版本规划

| 版本 | 功能 | 主要目标 | 状态 |
| --- | --- | --- | --- |
| v0.1 | 基础聊天、流式输出 | 打通前后端与模型 | ✅ |
| v0.2 | 工具调用 | 让模型能够使用外部工具 | ✅ |
| v0.3 | 任务规划与执行 | 支持多步骤任务 | ✅ |
| v0.4 | 记忆系统 | 保存和检索长期记忆 | ✅ |
| v0.5 | 知识库 | 支持文档上传、切块和检索 | 下一步 |
| v0.6 | 多模型管理 | 支持不同模型切换 | |
| v0.7 | 账号体系 | 注册、登录、权限管理 | |
| v0.8 | 云端部署 | 多用户在线服务 | |
| v0.9 | 桌面启动器 | Windows 双击启动与云端连接 | |
| v1.0 | 完整 Agent 平台 | 安全、稳定、可扩展 | |

版本只是开发里程碑，不意味着每个版本必须严格按编号发布。

## 重要架构约束

- React 不直接连接 MySQL；只通过 HTTP/SSE 调用 FastAPI。
- FastAPI 路由负责输入输出；业务逻辑放 Service。
- Repository 封装数据库读写；Session 按请求创建和关闭。
- Agent Core 不依赖 FastAPI Request/Response，保持可独立演进；Planner / Runner 同样只依赖模型协议。
- 任务执行开始（生成阶段）即绑定会话并写入目标消息，完成或失败都写回结果；删除会话会级联删除其任务与步骤。
- 记忆持久化≠作用域：memories 按 scope（global/project）检索注入；会话摘要只是临时记忆，随会话删除；删除项目只清其项目记忆，会话退回未分组。
- 分组归类由代码完成（v0.4.1）：优先级 自定义分组 → 项目 → 任务（由任务表派生 kind）→ 未分组；默认分组不落库，自定义分组删除后会话退回默认归类；“添加至分组”菜单只列自定义分组。
- 云端版本必须替换开发身份依赖，增加认证、权限、限流、HTTPS 和密钥管理。
