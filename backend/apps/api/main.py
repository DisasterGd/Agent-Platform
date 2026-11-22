from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent_platform.config import settings
from apps.api.routes import auth, chat, files, groups, health, knowledge, search, tasks
from apps.api.routes import memories as memories_route
from apps.api.routes import projects as projects_route
from apps.api.routes import settings as settings_route

app = FastAPI(title=settings.app_name, version="0.4.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=settings.api_v1_prefix)
app.include_router(settings_route.router, prefix=settings.api_v1_prefix)
app.include_router(chat.router, prefix=settings.api_v1_prefix)
app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(tasks.router, prefix=settings.api_v1_prefix)
app.include_router(knowledge.router, prefix=settings.api_v1_prefix)
app.include_router(files.router, prefix=settings.api_v1_prefix)
app.include_router(projects_route.router, prefix=settings.api_v1_prefix)
app.include_router(memories_route.router, prefix=settings.api_v1_prefix)
app.include_router(groups.router, prefix=settings.api_v1_prefix)
app.include_router(search.router, prefix=settings.api_v1_prefix)


# 托管已构建的前端（frontend/dist），使 http://127.0.0.1:8000 直接打开页面。
# 静态挂载放在所有 API 路由之后，因此 /api/*、/docs 等仍优先命中路由。
FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
