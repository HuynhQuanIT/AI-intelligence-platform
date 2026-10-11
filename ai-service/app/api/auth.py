"""Đăng ký, đăng nhập, quên mật khẩu và quản lý người dùng."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ..core import settings
from ..schemas import (
    AdminPasswordBody, ChangeEmailBody, EmailBody, LoginBody, OtpBody, PasswordBody,
    PasswordChangeBody, QuotaBody, ResetBody, RoleBody,
)
from ..services import auth, mailer
from .deps import client_ip, current_user, raise_http, require_admin

router = APIRouter(tags=["auth"])

REFRESH_COOKIE = "aip_refresh"
CSRF_HEADER, CSRF_VALUE = "x-requested-with", "aip"

NEUTRAL_OTP_MESSAGE = "Nếu email hợp lệ, mã xác thực đã được gửi. Mã có hiệu lực 5 phút."


def _run(action, *args):
    try:
        return action(*args)
    except auth.AuthError as exc:
        raise_http(exc)


def _queue_mail(background: BackgroundTasks, mail):
    # Gửi nền để thời gian phản hồi không khác nhau giữa email có và không có tài khoản.
    if mail:
        background.add_task(mailer.send_safely, *mail)


# ------------------------------ đăng ký ------------------------------

@router.post("/auth/register/start")
def register_start(b: EmailBody, request: Request, background: BackgroundTasks):
    mail = _run(auth.register_start, b.email, client_ip(request))
    _queue_mail(background, mail)
    return {"message": NEUTRAL_OTP_MESSAGE}


@router.post("/auth/register/verify")
def register_verify(b: OtpBody):
    return {"registration_token": _run(auth.register_verify, b.email, b.code)}


@router.post("/auth/register/complete")
def register_complete(b: PasswordBody):
    return _run(auth.register_complete, b.token, b.password)


# ------------------------------ đăng nhập ------------------------------

def _set_cookie(response: Response, refresh_token: str) -> None:
    """Refresh token chỉ nằm trong cookie httpOnly (JavaScript không đọc được). SameSite=Strict + header
    X-Requested-With chặn CSRF; Path hẹp để cookie chỉ đi kèm các request /auth."""
    response.set_cookie(
        REFRESH_COOKIE, refresh_token, max_age=settings.refresh_token_days() * 86400,
        httponly=True, secure=settings.cookie_secure(), samesite="strict", path=settings.cookie_path(),
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=settings.cookie_path(),
                           httponly=True, secure=settings.cookie_secure(), samesite="strict")


def _issue(response: Response, session: dict) -> dict:
    """Đặt cookie refresh, trả phần còn lại cho client (access token giữ trong bộ nhớ)."""
    _set_cookie(response, session.pop("refresh_token"))
    session["user"] = _with_quota(session["user"])  # giao diện hiện hạn mức ngay sau đăng nhập/làm mới
    return session


def _require_csrf_header(request: Request) -> None:
    if request.headers.get(CSRF_HEADER, "") != CSRF_VALUE:
        raise HTTPException(status_code=403, detail="Thiếu header xác thực yêu cầu.")


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")


def _with_quota(user: dict) -> dict:
    row = auth._get(user["id"])
    return {**user, "quota": auth.quota_status(row)}


@router.post("/auth/login")
def login(b: LoginBody, request: Request, response: Response):
    session = _run(auth.login, b.email, b.password, client_ip(request), _user_agent(request))
    return _issue(response, session)


@router.post("/auth/refresh")
def refresh(request: Request, response: Response):
    _require_csrf_header(request)
    try:
        session = auth.refresh_session(request.cookies.get(REFRESH_COOKIE, ""), client_ip(request),
                                       _user_agent(request))
    except auth.AuthError as exc:
        # Cookie hỏng/hết hạn/bị thu hồi: xóa luôn để trình duyệt không gửi lại vô ích.
        failed = JSONResponse(status_code=exc.status, content={"detail": exc.message})
        _clear_cookie(failed)
        return failed
    return _issue(response, session)


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    _require_csrf_header(request)
    auth.logout_session(request.cookies.get(REFRESH_COOKIE, ""))
    _clear_cookie(response)
    return {"message": "Đã đăng xuất."}


@router.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return _with_quota(user)


@router.post("/auth/password")
def change_password(b: PasswordChangeBody, request: Request, response: Response, background: BackgroundTasks,
                    user: dict = Depends(current_user)):
    session, mail = _run(auth.change_password, user, b.current_password, b.new_password,
                         client_ip(request), _user_agent(request))
    _queue_mail(background, mail)
    return {**_issue(response, session), "message": "Đã đổi mật khẩu. Các thiết bị khác đã bị đăng xuất."}


# ----------------------------- quên mật khẩu -----------------------------

@router.post("/auth/forgot/start")
def forgot_start(b: EmailBody, request: Request, background: BackgroundTasks):
    mail = _run(auth.forgot_start, b.email, client_ip(request))
    _queue_mail(background, mail)
    return {"message": NEUTRAL_OTP_MESSAGE}


@router.post("/auth/forgot/verify")
def forgot_verify(b: OtpBody):
    return {"reset_token": _run(auth.forgot_verify, b.email, b.code)}


@router.post("/auth/forgot/reset")
def forgot_reset(b: ResetBody):
    _run(auth.reset_password, b.token, b.password)
    return {"message": "Đã đặt lại mật khẩu. Hãy đăng nhập bằng mật khẩu mới."}


# --------------------------- quản lý người dùng ---------------------------

@router.get("/users")
def list_users(_: dict = Depends(require_admin)):
    return auth.list_users()


@router.post("/users/{user_id}/approve")
def approve_user(user_id: str, admin: dict = Depends(require_admin)):
    return _run(auth.set_active, admin["id"], user_id, True)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: str, admin: dict = Depends(require_admin)):
    return _run(auth.set_active, admin["id"], user_id, False)


@router.post("/users/{user_id}/role")
def change_role(user_id: str, b: RoleBody, admin: dict = Depends(require_admin)):
    return _run(auth.set_role, admin["id"], user_id, b.role)


@router.get("/users/{user_id}")
def user_detail(user_id: str, _: dict = Depends(require_admin)):
    return _run(auth.get_user_detail, user_id)


@router.post("/users/{user_id}/password")
def set_user_password(user_id: str, b: AdminPasswordBody, background: BackgroundTasks,
                      admin: dict = Depends(require_admin)):
    mail = _run(auth.admin_set_password, admin, user_id, b.password)
    _queue_mail(background, mail)
    return {"message": "Đã đặt lại mật khẩu. Người dùng bị đăng xuất khỏi mọi thiết bị."}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    _run(auth.delete_user, admin, user_id)
    return {"deleted": user_id}


@router.post("/users/{user_id}/email")
def change_user_email(user_id: str, b: ChangeEmailBody, background: BackgroundTasks,
                      admin: dict = Depends(require_admin)):
    user, mails = _run(auth.change_email, admin, user_id, b.email)
    for mail in mails:
        _queue_mail(background, mail)
    return user


@router.post("/users/{user_id}/quota")
def set_user_quota(user_id: str, b: QuotaBody, admin: dict = Depends(require_admin)):
    return _run(auth.set_quota, admin, user_id, b.limit)
