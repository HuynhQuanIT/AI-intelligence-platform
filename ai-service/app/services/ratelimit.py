"""Giới hạn tốc độ trong bộ nhớ (cửa sổ trượt).

Giới hạn: mất khi khởi động lại và không chia sẻ giữa nhiều instance. Khi chạy nhiều bản
ai-service cần chuyển sang Redis. Khóa tài khoản và giới hạn gửi OTP không dùng module này
mà lưu trong database.
"""
import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_events: dict[str, deque] = defaultdict(deque)


def hit(key: str, limit: int, window_seconds: int) -> int:
    """Ghi một sự kiện. Trả 0 nếu còn trong hạn mức, ngược lại số giây phải chờ."""
    now = time.monotonic()
    with _lock:
        q = _events[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            return max(1, int(window_seconds - (now - q[0])) + 1)
        q.append(now)
        return 0


def count(key: str, window_seconds: int) -> int:
    now = time.monotonic()
    with _lock:
        q = _events.get(key)
        if not q:
            return 0
        while q and now - q[0] > window_seconds:
            q.popleft()
        return len(q)


def reset(key: str | None = None) -> None:
    with _lock:
        if key is None:
            _events.clear()
        else:
            _events.pop(key, None)
