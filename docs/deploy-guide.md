# 部署指南（手把手版）：从本机到"朋友可以注册使用"

> 配套 `README.md`「云端部署」小节与 `docs/design-v0.7-v0.8.md` §4。本文假设你从零开始，
> 把每一步"为什么/做什么/怎么验证"写清楚。三句话总览：
> **① 装 Docker Desktop（给电脑装一个"集装箱码头"）→ ② `docker compose up` 在本机把整套线上服务跑一遍（彩排）→
> ③ Cloudflare Tunnel（把彩排舞台从你家接到公网，不用公网 IP、不开路由器端口、免费）。**

---

## 0. 先分清三个概念（迷茫解除）

| 概念 | 是什么 | 在哪做 |
|---|---|---|
| **本地开发** | `python run.py` 起的单进程（你现在每天用的） | 不变，跟部署无关 |
| **本地演练（彩排）** | 用 Docker 把"线上该有的样子"（Caddy+应用+数据库三个容器）在你电脑上整套跑一遍，**用的是全新空数据库**，跟你 3307 端口的开发库完全无关 | 你的电脑 |
| **上线** | 彩排没问题后，用 Cloudflare Tunnel 把本机的服务暴露成一个公网网址 | 你的电脑 + Cloudflare |

**担心数据安全？** 演练/上线的数据库是 Docker 卷里的全新 MySQL，你现有的会话/文件/配置一概不会被碰；
`.env` 也不会被改（只有两个新增变量），不满意随时 `docker compose down` 一键消失。

---

## 1. 安装 Docker Desktop（约 10 分钟，一次性）

Windows 上 Docker 不是一个 pip 命令能装的包——它是一个**桌面应用**，底层依赖 WSL2（Windows 的 Linux 子系统）。

### 第 1 步：启用 WSL2（管理员 PowerShell，执行一次）

```powershell
wsl --install
```

装完**重启电脑**。重启后验证：`wsl --status` 显示版本 2 即可（会自带一个 Ubuntu 子系统，不用管它）。

### 第 2 步：安装 Docker Desktop（两种方式任选其一）

- **命令行（推荐）**：`winget install -e --id Docker.DockerDesktop`
- **官网下载**：<https://www.docker.com/products/docker-desktop/> → Download for Windows → 双击安装包，
  勾选 "Use WSL 2 based engine"（默认勾着）→ 完成。

装完**启动一次 Docker Desktop**（开始菜单点它），等右下角状态变成绿色 "Engine running"。

### 第 3 步：验证（任意终端）

```powershell
docker --version          # Docker version 2x.x
docker compose version    # Docker Compose version v2.x
```

> 个人使用免费（Docker Desktop 对小型企业/个人免费）。开机它会自启动，占一些内存（2-3GB），
> 不想常驻可在 Docker Desktop 设置里关掉 "Start when you log in"。

---

## 2. 本地演练（彩排，约 5 分钟）

### 第 1 步：`.env` 追加两个部署专用变量

打开仓库根目录 `.env`，追加（值自己定，随机长串即可；**与你现有的 DATABASE_URL 口令无关**）：

```ini
MYSQL_PASSWORD=<给容器 MySQL 设一个口令>
MYSQL_ROOT_PASSWORD=<给容器 MySQL root 设一个口令>
# 有域名后再设 SITE_ADDRESS=你的域名；演练阶段不用
```

### 第 2 步：一条命令起全套

```powershell
cd D:\My_Project\GitHub_repositories\Agent-Platform
docker compose up -d --build
```

首次构建要下载镜像+构建前端（几分钟）。它做了什么：
- **app 容器**：装后端依赖 → `alembic upgrade head`（全新库自动建表）→ uvicorn 起服务 → 托管前端页面；
- **mysql 容器**：全新 MySQL 8（数据存 Docker 卷 `mysql_data`，不对公网开放端口）；
- **caddy 容器**：对外 80/443，反向代理到 app（SSE 不缓冲）。

### 第 3 步：验证彩排成功

```powershell
docker compose ps                     # 三个容器都是 running / healthy
curl http://localhost/api/health      # {"status":"ok"}（或用浏览器开 http://localhost/api/health）
```

然后浏览器开 **<http://localhost>**——你会看到熟悉的登录页。此时它就是"云端模式"：
`.env` 的 `AUTH_MODE` 在 compose 里默认按 cloud 注入，所以**注册要用验证码**。
验证码在哪看？邮件通道还没配 → 设置 → 平台页签里配 SMTP（或先用 console 通道看 `docker compose logs -f app`
里的 `[console-mail]` 行）。**注册一个自己的账号、发消息、传文件、跑一个任务**——全部通过 = 彩排完成。

### 常用操作

```powershell
docker compose logs -f app    # 看应用日志
docker compose down           # 停掉并删容器（数据卷保留，再 up 数据还在）
docker compose down -v        # 连数据卷一起删（彻底重来）
```

---

## 3. 上线：Cloudflare Tunnel（让朋友访问你家的服务器）

**原理一句话**：`cloudflared` 从你家主动连向 Cloudflare（出站连接），朋友访问 Cloudflare 的网址，
流量从隧道流回来。所以：**不需要公网 IP、不开路由器端口、不碰防火墙，且 Cloudflare 免费版自带 HTTPS。**

### 路线 A：快速隧道（10 分钟见效，零账号零域名，适合先让朋友试用）

```powershell
winget install -e --id Cloudflare.cloudflared     # 装 cloudflared（或官网下载 exe）
cloudflared tunnel --url http://localhost:80
```

它会打印一个临时网址（形如 `https://random-words.trycloudflare.com`）——发给朋友就能注册使用。
**限制**：网址随机且重启就变、无 SLA；适合 0.8.2 的"朋友真实使用一个周期"验证阶段。

### 路线 B：正式隧道（需要你有一个域名，网址固定）

1. **买域名**：腾讯云/阿里云万网 ¥10-50/年 随便挑一个（不需要备案——流量走 Cloudflare 海外节点）。
2. **域名接入 Cloudflare**：注册 [cloudflare.com](https://www.cloudflare.com)（免费版够用）→ Add a site
   → 输入你的域名 → 选 Free 套餐 → 它给你两个 NS 服务器地址 → 回域名注册商处把 DNS 服务器改成这两个。
   （生效要几分钟到几小时。）
3. **创建隧道并绑定域名**（本机执行）：
   ```powershell
   cloudflared tunnel login                     # 浏览器授权
   cloudflared tunnel create agent-platform     # 生成凭证
   cloudflared tunnel route dns agent-platform 你的域名.com
   ```
4. **写配置并常驻**：建 `%USERPROFILE%\.cloudflared\config.yml`：
   ```yaml
   tunnel: agent-platform
   credentials-file: C:\Users\<你>\.cloudflared\<隧道ID>.json
   ```
   然后 `cloudflared tunnel run agent-platform` 验证 → 注册成 Windows 服务开机自启：
   `cloudflared service install`。
5. 朋友访问 `https://你的域名.com` → Cloudflare 边缘（HTTPS 终结）→ 隧道 → 你的 caddy(:80) → app。
   Caddy 的自动 HTTPS 在这条链路里不需要（TLS 由 Cloudflare 终结），`.env` 的 `SITE_ADDRESS` 可以不设。

### 上线后必做（设计文档 §4.5 运维清单，0.8.2 逐项落地）

- **Windows 电源设置：禁止睡眠**（否则朋友半夜发现网站挂了）；`cloudflared` 与 Docker Desktop 设为自启；
- **备份**：每晚 `mysqldump --single-transaction`（容器内执行）+ `data/` 目录打包，存到另一块盘/网盘；
- **拨测**：UptimeRobot 免费版盯 `https://你的域名/api/health`；
- **安全**：`.env` 权限保持私有、MySQL 端口不对公网（compose 已保证）。

---

## 常见问题

- **`docker compose up` 报端口占用**：80 被 IIS/其它服务占了？改 `docker-compose.yml` 里 caddy 的
  `"80:80"` 为 `"8080:80"`，演练时访问 http://localhost:8080。
- **构建很慢/失败**：npm 下载慢可给 Docker Desktop 设置代理，或先 `npm run build`（仓库根已有 dist 时
  Dockerfile 的前端阶段仍会重跑，属正常）。
- **压测**：`deploy/locustfile.py`，用法见文件头注释。注意 SSE 流式压测默认关闭——流的瓶颈在上游
  LLM 供应商并发限速（实测证实），且会产生真实费用。
- **演练库想彻底重置**：`docker compose down -v && docker compose up -d --build`。
