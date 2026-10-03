import io
import os
import threading
from pathlib import Path

# local: ghi vào thư mục (docker volume), không cần dịch vụ nào khác.
# s3:    dùng bất kỳ kho tương thích S3 (MinIO, SeaweedFS, Garage...).
BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))

ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "platform")
SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio_dev_password")
BUCKET = os.getenv("MINIO_BUCKET", "documents")

_client = None
_bucket_ready = False
_lock = threading.Lock()


def _local_path(key: str) -> Path:
    base = UPLOAD_DIR.resolve()
    path = (base / key).resolve()
    if base not in path.parents:
        raise ValueError("Invalid storage key")
    return path


def _get_client():
    global _client
    if _client is None:
        from minio import Minio

        _client = Minio(ENDPOINT, access_key=ACCESS_KEY, secret_key=SECRET_KEY, secure=False)
    return _client


def _ensure_bucket(client):
    global _bucket_ready
    with _lock:
        if not _bucket_ready:
            if not client.bucket_exists(BUCKET):
                client.make_bucket(BUCKET)
            _bucket_ready = True


def put_object(key: str, data: bytes, content_type: str) -> None:
    """Đồng bộ (gọi trong thread). Ném lỗi nếu kho lưu trữ không sẵn sàng."""
    if BACKEND == "s3":
        client = _get_client()
        _ensure_bucket(client)
        client.put_object(BUCKET, key, io.BytesIO(data), len(data), content_type=content_type)
        return

    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    temp.write_bytes(data)
    os.replace(temp, path)  # ghi nguyên tử: không để lại file dở dang


def remove_object(key: str) -> None:
    try:
        if BACKEND == "s3":
            _get_client().remove_object(BUCKET, key)
        else:
            path = _local_path(key)
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass
    except Exception:
        pass
