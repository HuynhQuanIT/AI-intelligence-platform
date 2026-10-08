"""Phụ thuộc dùng chung của các router: xác thực và phân quyền."""
from fastapi import Depends, HTTPException, Request

from ..services import auth


def client_ip(request: Request) -> str:
    """IP người dùng: gateway/nginx chuyển qua X-Real-IP hoặc X-Forwarded-For.
    Chỉ đáng tin khi ai-service không bị truy cập trực tiếp từ ngoài."""
    forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip()
    return ip or (request.client.host if request.client else "unknown")


def raise_http(exc: auth.AuthError):
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    if exc.status == 401:
        headers = {**(headers or {}), "WWW-Authenticate": "Bearer"}
    raise HTTPException(status_code=exc.status, detail=exc.message, headers=headers)


def current_user(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise_http(auth.AuthError(401, "Cần đăng nhập."))
    try:
        return auth.authenticate(token.strip())
    except auth.AuthError as exc:
        raise_http(exc)


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên mới có quyền này.")
    return user
