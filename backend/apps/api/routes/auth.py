"""认证接口（v0.7）：邮箱验证码登录/注册合一 + 会话 cookie。

- POST /auth/request-code：发码，返回 {channel: "console"|"smtp"}（不区分邮箱是否存在——防枚举；
  channel 供前端如实提示验证码去向，console 通道即"码在后端控制台"）
- POST /auth/verify：验码 + 建号（未注册过）+ 签发 ap_session cookie（HttpOnly + SameSite=Lax，cloud 加 Secure）
- GET  /auth/me：当前身份（local 模式永远 200，前端据此决定是否渲染登录页）
- POST /auth/logout：撤销会话行 + 清 cookie
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.services import auth_service
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["auth"])

SESSION_MAX_AGE = int(timedelta(days=settings.session_ttl_days).total_seconds())


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=auth_service.SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.auth_mode == "cloud",
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=auth_service.SESSION_COOKIE, path="/")


class EmailIn(BaseModel):
    email: str


class VerifyIn(BaseModel):
    email: str
    code: str


@router.post("/auth/request-code")
def request_code(body: EmailIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """发码。响应只含邮件通道类型，不含邮箱存在性信息——防枚举语义不变。"""
    ip = request.client.host if request.client else ""
    try:
        auth_service.request_code(db, body.email, ip=ip)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    from agent_platform.infrastructure.mail.factory import get_mail_provider

    return {"channel": get_mail_provider().channel}


@router.post("/auth/verify")
def verify(body: VerifyIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    ip = request.client.host if request.client else ""
    try:
        user, token = auth_service.verify_code(db, body.email, body.code, ip=ip)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    _set_session_cookie(response, token)
    return _me_payload(user, via_session=True)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if token:
        auth_service.revoke_session(db, token)
    _clear_session_cookie(response)
    return Response(status_code=204)


def _me_payload(user, via_session: bool) -> dict:
    """身份视图（v0.7 决策：/auth/me 返回 {id, mode, email?, is_admin?}，前端据此决定登录页）。

    v0.7.2 增加 via_session：当前身份是否来自已登录会话（local 模式 False=本地默认身份未登录）。
    """
    return {
        "id": user.id,
        "mode": settings.auth_mode,
        "email": user.email,
        "display_name": user.display_name or "",
        "is_admin": bool(user.is_admin),
        "via_session": via_session,
    }


@router.get("/auth/me")
def me(
    request: Request,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """当前身份。local 模式恒 200（dev 用户或已登录账号）；cloud 未登录由依赖层抛 401。"""
    from agent_platform.repositories.users import UserRepository

    user = UserRepository(db).get(user_id)
    if user is None:
        # local 模式下 dev 用户缺失（理论上启动时已补种）：按占位返回，避免前端卡死
        return {"id": user_id, "mode": settings.auth_mode, "email": None,
                "display_name": "", "is_admin": False, "via_session": False}
    via_session = auth_service.resolve_session(
        db, request.cookies.get(auth_service.SESSION_COOKIE) or ""
    ) is not None
    return _me_payload(user, via_session)
