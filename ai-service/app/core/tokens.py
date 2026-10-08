"""JWT (HS256) và mã OTP."""
import hashlib
import hmac
import secrets
import time

import jwt

from . import settings

ALGORITHM = "HS256"
FLOW_TOKEN_SECONDS = 10 * 60  # token ngắn hạn giữa bước xác thực OTP và bước đặt mật khẩu


class TokenError(Exception):
    pass


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret(), algorithm=ALGORITHM)


def _decode(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret(), algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("typ") != expected_type:
        raise TokenError("wrong token type")
    return payload


def create_access_token(user_id: str, role: str, token_version: int) -> tuple[str, int]:
    now = int(time.time())
    seconds = settings.access_token_minutes() * 60
    token = _encode({"sub": user_id, "role": role, "tv": token_version, "typ": "access",
                     "iat": now, "exp": now + seconds})
    return token, seconds


def decode_access_token(token: str) -> dict:
    return _decode(token, "access")


def create_flow_token(kind: str, email: str, token_version: int = 0) -> str:
    """kind: 'register' hoặc 'reset'. Token reset gắn token_version nên dùng được đúng một lần."""
    now = int(time.time())
    return _encode({"sub": email, "tv": token_version, "typ": kind,
                    "iat": now, "exp": now + FLOW_TOKEN_SECONDS})


def decode_flow_token(token: str, kind: str) -> dict:
    return _decode(token, kind)


# ------------------------------- OTP -------------------------------

def generate_otp() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def _otp_key() -> bytes:
    pepper = settings.env("OTP_PEPPER") or settings.jwt_secret()
    return hashlib.sha256(("otp-key:" + pepper).encode("utf-8")).digest()


def otp_digest(email: str, purpose: str, code: str) -> str:
    """HMAC-SHA256 có khóa bí mật: lộ database cũng không dò ngược được mã 6 số."""
    message = f"{email.lower()}|{purpose}|{code}".encode("utf-8")
    return hmac.new(_otp_key(), message, hashlib.sha256).hexdigest()


def otp_matches(email: str, purpose: str, code: str, stored_digest: str) -> bool:
    return hmac.compare_digest(otp_digest(email, purpose, code), stored_digest)
