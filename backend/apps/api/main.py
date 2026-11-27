from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent_platform.config import settings
from apps.api.routes import (
    admin,
    auth,
    chat,
    files,
    groups,
    health,
    knowledge,
    library,
    search,
    tasks,
)
from apps.api.routes import local_projects as local_projects_route
from apps.api.routes import memories as memories_route
from apps.api.routes import projects as projects_route
from apps.api.routes import settings as settings_route


def _startup_maintenance() -> None:
    """启动维护（v0.7，幂等）：local 模式补种 dev 用户；存量文件搬入 per-user 目录；
    清理过期会话与验证码行。存储迁移失败只记日志不阻断启动（老布局在 local 下仍可读）。"""
    import logging

    from agent_platform.infrastructure.database.session import SessionLocal
    from agent_platform.infrastructure.storage.migrate import (
        migrate_root_files_to_user_dirs,
    )
    from agent_platform.repositories.users import UserRepository
    from agent_platform.services import auth_service

    logger = logging.getLogger("agent_platform.startup")
    with SessionLocal() as db:
        if settings.auth_mode == "local":
            UserRepository(db).ensure_user(settings.dev_user_id, "developer")
        auth_service.purge_expired(db)
    try:
        moved = migrate_root_files_to_user_dirs(settings.dev_user_id)
        if moved:
            logger.warning("v0.7 存量迁移：已把 %d 个根目录文件搬入 u%s/", moved, settings.dev_user_id)
    except OSError:
        logger.exception("存量文件目录迁移失败（可稍后手动执行 scripts/migrate_files_to_user_dirs.py）")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _startup_maintenance()
    yield


app = FastAPI(title=settings.app_name, version="0.7.6", lifespan=lifespan)

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
app.include_router(library.router, prefix=settings.api_v1_prefix)
app.include_router(projects_route.router, prefix=settings.api_v1_prefix)
app.include_router(memories_route.router, prefix=settings.api_v1_prefix)
app.include_router(groups.router, prefix=settings.api_v1_prefix)
app.include_router(search.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router, prefix=settings.api_v1_prefix)
# 本地项目（v0.7.4 伪编辑器）只在 local 模式存在：远程用户没有"本机磁盘"可言（路由层还有双保险）
if settings.auth_mode == "local":
    app.include_router(local_projects_route.router, prefix=settings.api_v1_prefix)


# 托管已构建的前端（frontend/dist），使 http://127.0.0.1:8000 直接打开页面。
# 静态挂载放在所有 API 路由之后，因此 /api/*、/docs 等仍优先命中路由。
FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
