"""Cấu hình xác thực đọc từ biến môi trường (đọc lại mỗi lần gọi để test đổi được)."""
import os

# Giá trị mẫu trong .env.example: không bao giờ được dùng thật.
_SAMPLE_PREFIXES = ("change-me", "changeme", "replace", "your-", "secret", "example")
MIN_SECRET_LENGTH = 32
MIN_PASSWORD_LENGTH = 10


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def jwt_secret() -> str:
    return env("JWT_SECRET")


def access_token_minutes() -> int:
    return env_int("ACCESS_TOKEN_MINUTES", 60)


def registration_mode() -> str:
    """approval: đăng ký xong chờ admin duyệt | domain: chỉ email thuộc ALLOWED_EMAIL_DOMAINS | open | closed."""
    mode = env("REGISTRATION_MODE", "approval").lower()
    return mode if mode in {"approval", "domain", "open", "closed"} else "approval"


def allowed_email_domains() -> set[str]:
    return {d.strip().lower().lstrip("@") for d in env("ALLOWED_EMAIL_DOMAINS").split(",") if d.strip()}


def chat_rate_per_minute() -> int:
    return env_int("CHAT_RATE_LIMIT_PER_MIN", 20)


def cors_origins() -> list[str]:
    raw = env("CORS_ORIGINS", "http://localhost:5173,http://localhost:5000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def validate() -> None:
    """Dịch vụ từ chối chạy nếu JWT_SECRET thiếu, quá ngắn hoặc là giá trị mẫu."""
    secret = jwt_secret()
    if len(secret) < MIN_SECRET_LENGTH or secret.lower().startswith(_SAMPLE_PREFIXES):
        raise RuntimeError(
            "JWT_SECRET chưa được đặt đúng: cần chuỗi ngẫu nhiên >= 32 ký tự và không phải giá trị mẫu. "
            "Tạo bằng: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
