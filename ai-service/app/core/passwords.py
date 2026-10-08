"""Băm và kiểm tra mật khẩu bằng scrypt (thư viện chuẩn, không cần cài thêm)."""
import base64
import hashlib
import hmac
import os

from .settings import MIN_PASSWORD_LENGTH

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
MAX_PASSWORD_LENGTH = 128


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
            dklen=len(base64.b64decode(expected)),
        )
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except Exception:
        return False


# Băm cố định dùng khi email không tồn tại, để thời gian phản hồi không lộ email có tồn tại hay không.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def burn_time(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def password_problem(password: str, email: str = "") -> str | None:
    """Trả thông báo lỗi nếu mật khẩu không đạt, ngược lại None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Mật khẩu cần ít nhất {MIN_PASSWORD_LENGTH} ký tự."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Mật khẩu tối đa {MAX_PASSWORD_LENGTH} ký tự."
    if email and password.lower() == email.lower():
        return "Mật khẩu không được trùng với email."
    if password.isdigit() or len(set(password)) < 4:
        return "Mật khẩu quá đơn giản."
    return None
