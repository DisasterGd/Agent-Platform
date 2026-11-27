# Agent Platform 生产镜像（v0.8.1）
# 三阶段：前端构建（node）→ 后端运行时（python-slim）。本地开发不使用本文件（run.py 不变）。
# 上游基础镜像版本固定在当前主流大版本（2026-11）。

# ---- Stage 1: 前端构建 ----
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: 后端运行时 ----
FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    PIP_NO_CACHE_DIR=1

# 先只拷 pyproject 装依赖？——src 布局需要包体，这里整目录拷贝（个人规模镜像体积不敏感）
COPY backend/ ./
# cryptography 的 wheel 在 slim 上可用；无需额外系统依赖（PyMySQL 纯 Python）
RUN pip install --no-cache-dir .

# main.py 的静态托管路径 = apps/api/main.py 往上三级 + frontend/dist；
# 容器里等价位置是 /frontend/dist（与仓库布局解耦，开发链路零改动）
COPY --from=web /web/dist /frontend/dist

EXPOSE 8000
# 启动前先跑迁移（容器生命周期内只执行一次，之后 uvicorn 拉起 worker）
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --workers 2 --app-dir ."]
