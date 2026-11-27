# v0.7 账号体系 与 v0.8 云端部署 · 设计方案（讨论稿 v1）

> 依据：《Agent项目开发思路.md》第五节版本规划与第六节部署原则（权重最高）、
> 《账号体系与云端部署想法.txt》（2026-11）、2026-11-25 全仓库多用户就绪度审计。
> 原则对齐：本地优先、云端同核心；云端继续用 MySQL；避免提前过度设计；
> **桌面端"连接云端"属 v0.9，本文不设计任何本地↔云端数据同步**（冲突解决复杂度高，明确不做）。

---

## 一、现状盘点（2026-11-25 审计结论）

### 1.1 已就绪（比预想的好）

| 事项 | 事实 |
|---|---|
| 归属字段 | 10 张表中 8 张有 `user_id`（conversations/projects/file_assets/knowledge_chunks/conv_groups/memories/tasks + users 本体）；`messages`/`task_steps` 经父表间接归属，隔离天然成立。0001 迁移即有 users 表与 conversations.user_id |
| 身份插点 | **唯一**：`apps/api/dependencies.py:13` `get_current_user_id()` → `settings.dev_user_id`；约 38 处路由全部经 `Depends` 注入。认证替换只动这一个函数，路由层零改动 |
| 进程内状态 | **无会话级进程状态**：SSE 全落库（任务取消/断开判定查 `tasks.status`，chat_service 落消息/摘要/标题），水平扩展无粘性障碍。仅三个无状态单例（storage/settings 服务/模型工厂注册表） |
| 文件架构 | "磁盘是事实来源 + file_assets 元数据索引"天然适配"文件不进数据库"——云端只需加 per-user 目录层 |
| Cookie 通路 | CORS 已 `allow_credentials=True`（main.py:25-31）；前端 fetch 默认 `same-origin` 自动带 cookie，dev 走 vite 代理同源、prod 静态托管同源——前端 API 层几乎零改动 |
| 静态托管 | main.py 已挂 `frontend/dist` 于 "/"，部署**不需要**单独的前端容器 |

### 1.2 缺口（v0.7 要还的债）

1. **身份是配置常量不是认证**：`dependencies.py:3` 自述"公网部署前必须替换"。
2. **约 10 个端点缺归属校验**：`chat.py:97-172`（PATCH/DELETE 会话、列消息、两个 SSE 流只查会话存在不查归属）、`files.py:48-67`（文件下载无 user 校验）、`routes/settings.py` 全文件（无 user 概念）。tasks/memories/projects/groups/library/knowledge 路由已带过滤。
3. **settings.json 是进程级全局单例**（`settings_service.py:316-323`，模块级 `_service`，无缓存每次读文件）：所有用户共享同一套模型配置与凭据——多用户必须上库。
4. **secret_store 非 Windows 透传**（architecture.md 记录在案的债）：云上 Linux 无 DPAPI，必须补真实加密。
5. **`(category, stored_name)` 全局唯一**（models.py:78）：per-user 目录后需改为 `(user_id, category, stored_name)`。
6. **users 表只有 id/username/created_at**：无 email/is_admin/status。
7. **前端零认证痕迹**：无登录页、从未调 `/auth/me`（好在 request() 不需要改，见 1.1）。
8. **磁盘 stored_name 写入无锁**（local.py:92-95，`exists()` 检查与写入非原子）：并发同名有竞态，目前靠 DB 唯一约束兜底；per-user 分目录后冲突面缩小，v0.7 顺手加锁或接受现状。

---

## 二、总体模式：一个代码库，两种运行模式

对应想法第 1 条（无账号本地模式）与"云端同核心"的既定架构：差异只在**配置与认证**，不在代码分叉。

```
AUTH_MODE=local（默认，永远保留）          AUTH_MODE=cloud
├─ 无登录页，启动即用                      ├─ 登录页（邮箱+验证码）
├─ get_current_user_id() → DEV_USER_ID    ├─ get_current_user_id() → 解析会话 cookie，未登录 401
├─ 数据落本地 MySQL + data/ 目录           ├─ 数据落云端 MySQL + data/ 目录（同一结构，文件加 per-user 前缀）
├─ settings.json 单文件（现状）            ├─ settings 入库（user_settings 表，按用户隔离）
└─ secret_store: DPAPI（Windows）          └─ secret_store: Fernet（SERVICE_SECRET）
```

- `config.py` 新增 `auth_mode: str = "local"`（env `AUTH_MODE`），**local 模式行为必须零变化**：全部现有测试保持绿，v0.7 每个小步都以"local 不受影响"为验收线。
- 本地数据永不自动上云；桌面端（v0.9 启动器）默认 local 模式。
- `/auth/me` 返回 `{id, mode, email?, is_admin?}`，前端据此决定是否渲染登录页——local 模式用户永远看不到登录页。

---

## 三、v0.7 账号体系

### 3.1 账号到底要存什么（回答想法第 2 条前半）

云端模式下，一个"账号"= 下面六类记录，**没有多余的东西**：

| 数据 | 载体 | 内容 |
|---|---|---|
| 身份 | `users` 行 | email（唯一）、display_name、is_admin、status(active/disabled)、last_login_at、created_at |
| 登录态 | `sessions` 行 | token 哈希、user_id、expires_at（30 天滑动）、last_seen_at、revoked_at；**cookie 里只放随机 token，库里存其 SHA-256**（拖库不泄露可用令牌） |
| 验证码 | `auth_codes` 行（一次性） | email、code_hash(SHA-256)、purpose、expires_at(10 分钟)、attempts(≤5)、consumed_at、created_ip；定期清理过期行 |
| 个人设置 | `user_settings` 行 | JSON 一列（等价 settings.json v3 的 profiles+roles+memory_enabled），API Key 仍密文落库、永不回显 |
| 业务数据 | 现有 10 张表 | 会话/消息/项目/分组/任务/记忆/资料库/知识块——归属字段已备，无需新表 |
| 文件本体 | **不进任何数据库** | 见 3.2 |

无密码方案下**没有 password 列**；将来若补密码登录，届时一条迁移加 `password_hash` 可空列即可，现在不预留（避免过度设计）。

### 3.2 文件存哪——不进数据库（回答想法第 2 条后半）

**方案：服务器磁盘 per-user 目录，数据库只存元数据**（延续 v0.5 已验证的三层设计）：

```
data/
├── uploads/u{user_id}/报告.md          ← 磁盘：真实文件，stored_name 不变规则（可读名+序号）
├── generated/u{user_id}/xxx.pdf
file_assets：user_id + category + stored_name + filename + kind + size ...  ← 只是索引
下载链接：/api/files/{category}/{name}  ← URL 形状不变，服务端先按 user 过滤 file_assets
                                          再定位磁盘路径 ⇒ 历史链接承诺延续
```

**为什么不把文件存进数据库**（这是主流做法，理由具体到本项目）：
1. 备份膨胀：mysqldump 每晚全量会带上所有二进制；文件放磁盘后备份策略可以分开（DB 高频、文件低频）。
2. 查询被拖累：列表/搜索查询与 BLOB 同表时缓存与缓冲池都被大对象污染。
3. 流式下载困难：经 DB 中转要整块进出内存；磁盘可直接 FileResponse 流式。
4. 已有接口缝：`infrastructure/storage`（save/parse/delete/iter）是现成抽象，**规模大了把 LocalStorage 换成对象存储实现（OSS/S3/MinIO），file_assets 与下载链接一行不改**——这正是"磁盘是事实来源"设计的红利。

对应改动：`LocalStorage` 路径加 `u{user_id}` 层；唯一约束 `(category, stored_name)` → `(user_id, category, stored_name)`（迁移 0012 顺带）；存量文件一次性搬入 `u1/`（dev 用户，`scripts/` 提供迁移脚本）。

### 3.3 注册与登录：邮箱 + 无密码验证码（回答想法第 3 条）

**验证码即凭证，登录注册合一**——邮箱没注册过，验证通过就是注册；注册过就是登录。全程只有"收验证码"一个难题，与想法判断一致。

```
① POST /api/auth/request-code {email}
    频控检查（见下） → 生成 6 位数字码（secrets）→ 存 SHA-256 哈希进 auth_codes（10 分钟有效）
    → MailProvider 发信
    响应统一 204，文案不区分"邮箱是否存在"（防邮箱枚举探测）

② POST /api/auth/verify {email, code}
    校验：哈希一致 + 未过期 + 未消费 + attempts<5（错误 5 次该码作废）
    → 消费（UPDATE consumed_at）→ 无账号则建号（display_name 取邮箱 @ 前段，可改名）
    → 签发 session：token = secrets.token_urlsafe(32)，库存其 SHA-256
    → Set-Cookie: ap_session（HttpOnly + Secure(云端) + SameSite=Lax + 30 天滑动续期）

③ GET /api/auth/me / POST /api/auth/logout（撤销 session 行 + 清 cookie）
```

**会话方案选服务端 session 表 + cookie，不选 JWT**：可撤销（封号/踢设备即时生效）、不用管密钥轮换与刷新令牌；JWT 的无状态优势要到多域名/多实例时才用得上，个人规模部署用不到。SSE 是同源 fetch（自带 cookie），无障碍。

**发邮件怎么解决（零成本起步）**：抽象 `MailProvider` 协议，与 SearchProvider 同款模式——

```
infrastructure/mail/base.py     MailProvider 协议：send(to, subject, text)
infrastructure/mail/smtp.py     SMTPProvider：smtplib 标准库 + SSL，QQ/163 邮箱授权码即可（免费、零新依赖）
infrastructure/mail/console.py  ConsoleProvider：app_env=dev 时把验证码打到控制台（本地调试 cloud 模式用）
infrastructure/mail/factory.py  按 .env 的 MAIL_PROVIDER 组装；后续可加阿里云 DirectMail / Resend 分支
```

- SMTP 用 QQ 邮箱（smtp.qq.com:465）或 163（smtp.163.com:465）+ 授权码，个人规模（每天几十封）完全够，**不花钱**。
- 到达率或量级有要求时再切阿里云邮件推送/腾讯云 SES（约 ¥1-2/千封，自定义域名需备案）；海外 Resend 免费层国内到达率一般，不作首选。
- 配置全走 `.env`：`MAIL_PROVIDER / SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / MAIL_FROM`。

**防滥用**（auth_codes 表 count 查询即可，不引入限流依赖）：每邮箱 1 次/分钟、5 次/小时、10 次/天；每 IP 20 次/天；验证码 5 次错误作废。（注册邀请码 v0.7.0 曾按决策点 #2 实现，v0.7.3 移除：个人规模不需要，开放注册即可，公网防灌注册依赖上述频控足够。）

### 3.4 数据隔离（回答想法第 5 条）

隔离不是"记得传 user_id"，是三条纪律 + 一张清单：

1. **身份只来自服务端**：`get_current_user_id()` 是全系统唯一身份来源（cloud 模式=解析 cookie，local=DEV_USER_ID）；任何请求体/查询参数里的 user_id 一律忽略。
2. **所有读写经 Repository 且带 user 过滤**：现有大部分路由已如此；审计发现的漏点按下表收口。
3. **文件两级校验**：file_assets 按 user 过滤定位 + 磁盘路径 per-user 前缀，下载前校验归属。

**0.7.2 收口清单**（审计逐行确认过的漏洞点）：

| 位置 | 问题 | 修法 |
|---|---|---|
| chat.py:97-117 / 120-126 | PATCH/DELETE 会话只查 id | 查询加 user_id 条件（查不到=404，不回 403，避免暴露存在性） |
| chat.py:129-134 | 列消息不查归属 | 同上 |
| chat.py:137-172 | 两个 SSE 流只查会话存在 | 同上（这是最要紧的一个——能读别人的对话流） |
| files.py:48-67 | 下载无 user 校验 | file_assets 按 user 过滤 |
| routes/settings.py 全文件 | 全局设置无 user 概念 | settings 入库（3.5），按当前用户读写 |
| knowledge 检索 | chunks 有 user_id，检索入口复核一遍 | 确认搜索闭包带 user 过滤 |

配套**隔离测试套件**（`tests/test_isolation.py`）：两个用户 fixture，A 访问 B 的会话/消息/文件/记忆/设置/检索一律 404；此后凡是新路由 PR 都跑这套。

### 3.5 设置上云与 Key 加密（还 architecture.md 记录的债）

- `user_settings` 表（user_id PK、data JSON、updated_at）；`settings_service` 抽出 `SettingsStore` 协议：local=FileStore（现状 settings.json）、cloud=DbStore，**PRESETS/roles/保存语义（缺省=保留、空串=清除、非空=替换）原样复用**。
- `secret_store` 加后端开关：Windows→DPAPI（现状）、cloud→**Fernet**（`cryptography` 包，SERVICE_SECRET 来自 .env）。唯一新增的 Python 依赖。
- "HTTP 响应与前端状态永不出现明文 Key"的红利照旧成立。

### 3.6 Key 归属：BYOK（用户自带 Key）【建议 v0.7 就定死】

云端模式每个用户在设置页填**自己的**各家 Key（现有 profiles/roles 双层结构整体复用，工程量≈0）。平台不内置 Key、不做计费系统。

- 理由：平台统一 Key ⇒ 必须做配额/计费/防刷 ⇒ 复杂度爆炸，且"可能租不起服务器"的预算现实下补贴不了他人 Token；BYOK 把成本问题在产品层面消解。
- 代价：使用者要自己有 DeepSeek/百炼/智谱的 Key（注册即送额度，门槛可接受）。
- 将来可加"平台免费额度"作为增值项，不属于 v0.7/v0.8。

### 3.7 管理员：保留，但做最小（回答想法第 4 条）

**结论：做一个 `is_admin` 布尔列，不做角色表/RBAC**——它不是象征性的，公网服务哪怕只给朋友用，也需要清理手段：

- `GET /api/admin/users`（列表/搜索/分页）、`PATCH /api/admin/users/{id}`（停用/启用——停用即撤销全部 session）、`GET /api/admin/stats`（用户数、磁盘占用、各表行数）。
- **admin 不获得读取他人业务数据的权限**（会话/文件/记忆仍严格隔离）——只管账号生命周期与聚合统计。这样"权限管理"有真实内容，又不破坏隔离原则。
- 首个 admin 由 `.env` 的 `ADMIN_EMAIL` 指定（该邮箱注册时自动 is_admin=1）。
- 想法里"我们甚至没必要设计账号体系"的疑虑：BYOK + 本地模式下，账号体系确实很薄——但它买到的是三样实打实的东西：多用户数据隔离、服务可公开部署的最小安全、以及 v0.9"云端连接"的地基。

### 3.8 前端改动（很小）

- 新增 `LoginView`（邮箱 → 验证码两步卡片）；App 启动先调 `/auth/me`：401 且 cloud 模式 → 渲染登录页；local 模式照旧直进。
- 顶栏/设置弹窗加账号区（邮箱、退出登录）。
- `api.ts`/SSE **无需改动**（fetch 默认 same-origin 已带 cookie；dev 走 vite 代理同源）。

### 3.9 v0.7 不做的事（明确划界）

本地↔云端数据同步、密码登录、多租户/组织、RBAC、计费、第三方 OAuth（微信/Google）——全部不做。前两项属于 v0.9+ 或"有真实需求再议"。

---

## 四、v0.8 云端部署

### 4.1 托管选项（回答想法第 6 条"租不起服务器"）

| 方案 | 成本 | 优点 | 缺点 | 判断 |
|---|---|---|---|---|
| **家用机 + Cloudflare Tunnel** | **0 元** | 免备案、自带 HTTPS 与域名、数据全在自己手里，与"本地优先"哲学一致；Tunnel 是出站连接，**无需公网 IP、不开端口** | 家宽上行与稳定性、断电断网即下线；CF 边缘节点国内速度一般 | **v0.8 正式路线**：先 0 成本真上线 |
| 腾讯云/阿里云轻量服务器（2C2G~4G） | ¥30-100/月（新购特价更低） | 真公网、稳定、全程可控 | 国内节点绑域名需 ICP 备案（个人可办，约 1-2 周）；香港节点免备案但延迟略高 | 用户多了/要稳定 SLA 时的升级路线 |
| Oracle Cloud Always Free（ARM 4C/24G） | 免费 | 性能离谱够用 | 注册需外卡验证、开通难抢、国内延迟不稳、有回收风险 | 可折腾，不作主线 |
| 免费 PaaS（Render/Fly/Railway） | ~0 | 零运维 | 免费层休眠会杀 SSE 长连接；MySQL 需外挂；国内访问差 | **不推荐**——SSE+长任务+MySQL 的组合天然不合免费 PaaS |
| Vercel/Netlify | 免费 | 前端托管极佳 | 只解决静态层，FastAPI+SSE 后端仍要自管 | 不需要——main.py 已托管 dist |

推荐节奏：**v0.8.1 家机 + Cloudflare Tunnel 零成本上线**（验证整套部署物），运行顺手后再决定是否花轻量服务器的钱。两路线用的是同一套 Docker 交付物，切换只是换个宿主机。

### 4.2 部署物：docker compose 三件套

```
caddy        ← 唯一对外：80/443，自动 Let's Encrypt 证书；/api/*/stream 反代超时调大
  │            （SSE 长连接必须：proxy_read_timeout ≥ 3600s，否则 60s 就被掐断）
  ├─ app      ← backend 镜像（uvicorn，容器内 0.0.0.0:8000）；同时托管 frontend/dist（现状能力，无前端容器）
  └─ mysql    ← mysql:8，数据卷；**不对外暴露端口**（仅 compose 内网可达）
```

- `run.py` 保持本地开发入口不动；容器用 `uvicorn` 直接启动（run.py 的开浏览器/reload 是开发行为）。
- 环境差异全部收敛在 `.env`（AUTH_MODE=cloud、DATABASE_URL、SERVICE_SECRET、MAIL_* 等）——这正是"差异只在配置"的落地。

### 4.3 高并发：这个项目的真实瓶颈画像

先纠正直觉：这个应用的并发模型**不是 QPS 型**（电商秒杀那种），而是**长连接型**——瓶颈是"同时活跃的 Agent 会话数"（每路 SSE 挂着 10-60 秒的 LLM 往返 + 工具循环）。

| 措施 | 说明 | 何时做 |
|---|---|---|
| 异步框架（现状已具备） | FastAPI + StreamingResponse 天然 async，单 worker 也能挂住大量空闲/等待中的 SSE 连接 | 已有 |
| **SSE 心跳** | 每 ~30s 发 comment 帧，防僵尸连接占满 worker、防中间层超时断连 | 0.8.1 必做（现有 events.py 无心跳） |
| MySQL 连接池调参 | 请求级 Session，池默认偏小；按 worker 数调 pool_size/max_overflow | 0.8.1 |
| 模型客户端复用 | 现状每请求 new ChatService 即重建 LLM 客户端（chat_service.py:63），加实例级缓存减握手开销 | 0.8.x 优化项 |
| uvicorn workers=2 | 单机 2C4G 起步够用；worker 数 × 连接池要一起算 | 部署时 |
| 限流 | 全站 429（自写计数即可，auth 频控同款机制） | 0.8.1 |
| 横向扩展（Redis 广播/多实例） | **明确不做**——无进程内状态（审计证实）意味着哪天真要多实例，加起来也不难，但个人规模永远到不了那一步（避免过度设计） | 永不，除非真出现 |

容量直觉：2C4G 单机 + async，撑 20-50 路并发流式会话没有压力（实际更先撞到上游 LLM 的并发限速）；给几十个朋友用绰绰有余。确切数字 0.8.1 用 locust 压一轮说话。

### 4.4 状态管理：答案已经内建于架构

想法里问"如何做好状态管理"——审计结论是**本项目几乎无状态可管**：会话/消息/任务/文件全部落库，登录态是 DB 里的 session 行，SSE 断线重连靠前端重发请求、服务端从库里续。"状态在 MySQL，进程随时可死可重生"——这是当初选 SSE+全落库换来的红利，v0.8 不需要为此做任何新设计。

### 4.5 运维清单（0.8.2 逐项落地）

- **备份**：每晚 `mysqldump --single-transaction` + `data/` 打包，异地存放（另一块盘/网盘）；恢复演练一次才算数。
- **监控**：UptimeRobot 免费层 HTTP 拨测 + Caddy 访问日志。
- **安全**：防火墙只开 80/443/SSH；`.env` 权限 0600 且不入 git（现状已满足）；MySQL 端口不对公网；HTTPS 由 Caddy 自动管。
- **限制**：上传上限、请求体上限、auth 频控（3.3）。
- 家机路线额外：Tunnel 断线自愈检查、电费/休眠设置（Windows 禁止睡眠）。

---

## 五、里程碑切分（每步都可运行、local 模式零影响）

| 步 | 内容 | 验收 |
|---|---|---|
| 0.7.1 认证骨架 | 迁移 0012（users 扩列 + auth_codes + sessions + user_settings + 唯一约束改造）→ MailProvider 三件套 → /auth/request-code、/auth/verify、/auth/me、/auth/logout → AUTH_MODE 切换 + dependencies 替换 | local 模式全测试绿；cloud 模式 curl 全流程（console 邮箱 provider 可本地调试） |
| 0.7.2 隔离收口 | 3.4 清单逐项 + 文件 per-user 目录与存量迁移脚本 + 隔离测试套件 | test_isolation 全绿；老消息下载链接仍有效 |
| 0.7.3 设置上云 + 前端 | SettingsStore 双后端 + secret_store Fernet（新增 cryptography）+ LoginView/账号区/401 处理 | cloud 模式两用户各自配各自的角色互不可见 |
| 0.7.4 管理员 + 文档 | is_admin 三端点 + ADMIN_EMAIL 引导 + README/架构文档更新 | 停用用户立即踢下线 |
| 0.8.1 Docker 化 | compose 三件套 + SSE 心跳 + 连接池/限流 + 本地 compose 演练 | `docker compose up` 一条命令起全套；locust 简单压测出数 |
| 0.8.2 上线 | Cloudflare Tunnel（或轻量服务器）+ 域名/HTTPS + 备份 cron + 拨测 | 朋友从外网真实注册使用一个周期 |

---

## 六、待拍板决策点

| # | 决策 | 我的建议 |
|---|---|---|
| 1 | 云端 Key 归属：BYOK 还是平台统一 | **BYOK**（3.6），v0.7 就定死——它决定要不要做计费，是最重的决策 |
| 2 | ~~开放注册是否加邀请码~~ | ~~加~~ **v0.7.3 移除**：个人规模用不上，频控已够；若公网被灌再议（届时优先升级限流而非邀请码） |
| 3 | 邮箱通道起步选家 | **QQ 或 163 SMTP 授权码**（零成本、零依赖），DirectMail 等留作 factory 分支 |
| 4 | 只验证码 or 补密码 | **先只验证码**；若实践中邮件不稳，届时一条迁移加密码列作备用通道，现在不预留 |
| 5 | v0.8 宿主 | **家机 + Cloudflare Tunnel 先行**（0 元），轻量服务器作升级路线 |
| 6 | admin 范围 | 用户列表/停用/统计三件套，不做 RBAC，admin 不读他人业务数据 |
| 7 | 命名小项 | 模式名 `AUTH_MODE=local|cloud`；cookie 名 `ap_session` |
