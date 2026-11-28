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


app = FastAPI(title=settings.app_name, version="0.9.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RateLimiter:
    """全站 API 限流（v0.8.1）：内存滑动窗口按 IP 计数（与 auth 频控同款自写计数，零新依赖）。

    只防单点刷爆（429），不是防滥用体系；进程内内存态——多实例时各自计数
    （个人规模永远用不到多实例，见设计文档 4.3）。/api/health 拨测豁免。
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        import threading
        from collections import deque

        self._deque = deque
        self._limit = max(limit, 0)
        self._window = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        if self._limit <= 0:
            return True
        import time

        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, self._deque())
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # 防长期膨胀：顺手清掉空壳 IP
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True


_limiter = RateLimiter(settings.rate_limit_per_minute)


@app.middleware("http")
async def api_rate_limit(request, call_next):
    path = request.url.path
    if (
        path.startswith(f"{settings.api_v1_prefix}/")
        and not path.startswith(f"{settings.api_v1_prefix}/health")
    ):
        client_ip = request.client.host if request.client else "unknown"
        if not _limiter.allow(client_ip):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "请求太频繁，请稍后再试"}, status_code=429)
    return await call_next(request)

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
