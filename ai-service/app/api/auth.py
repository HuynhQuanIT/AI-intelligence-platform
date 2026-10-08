"""Đăng ký, đăng nhập, quên mật khẩu và quản lý người dùng."""
from fastapi import APIRouter, BackgroundTasks, Depends, Request

from ..schemas import (
    AdminPasswordBody, EmailBody, LoginBody, OtpBody, PasswordBody, ResetBody, RoleBody,
)
from ..services import auth, mailer
from .deps import client_ip, current_user, raise_http, require_admin

router = APIRouter(tags=["auth"])

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

@router.post("/auth/login")
def login(b: LoginBody, request: Request):
    return _run(auth.login, b.email, b.password, client_ip(request))


@router.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return user


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
