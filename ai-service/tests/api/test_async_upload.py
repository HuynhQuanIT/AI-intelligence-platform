"""Upload bất đồng bộ: processing -> processed/failed, ẩn với người dùng cho tới khi xong, thử lại, dọn tài liệu kẹt."""
import uuid

import pytest

from app.core.db import query
from app.rag import documents as docs
from auth_helpers import make_user

pytestmark = pytest.mark.integration


def row(client, did):
    return next((d for d in client.get("/documents").json() if d["id"] == did), None)


def txt(name="a.txt"):
    return {"file": (name, f"Nội dung bất đồng bộ {uuid.uuid4()} để kiểm tra.".encode(), "text/plain")}


def test_upload_ends_processed_with_chunks(client):
    r = client.post("/documents/upload", files=txt())
    assert r.status_code == 202 and r.json()["status"] == "processing"
    did = r.json()["id"]
    try:
        d = row(client, did)
        assert d["status"] == "processed" and d["error"] is None
        assert client.get(f"/documents/{did}").json()["chunks"]
    finally:
        client.delete(f"/documents/{did}")


def test_processing_document_hidden_from_users_until_done(client):
    h, c, uid, _ = (lambda t: (t[1], t[3], t[2], None))(make_user())
    info = docs.start_upload("cho.txt", None, f"nội dung chờ {uuid.uuid4()}".encode())  # chưa chạy nền
    did = info["id"]
    try:
        assert row(client, did)["status"] == "processing"                      # admin thấy đang xử lý
        assert did not in {d["id"] for d in c.get("/documents", headers=h).json()}
        assert c.get(f"/documents/{did}", headers=h).status_code == 404
        assert c.get(f"/documents/{did}/file", headers=h).status_code == 404
        docs.process_document(did)
        assert row(client, did)["status"] == "processed"
        assert did in {d["id"] for d in c.get("/documents", headers=h).json()}
    finally:
        client.delete(f"/documents/{did}")


def test_corrupt_file_fails_with_message_and_retry(client):
    files = {"file": ("hong.pdf", b"%PDF-1.4 khong phai pdf that " + uuid.uuid4().bytes, "application/pdf")}
    r = client.post("/documents/upload", files=files)
    assert r.status_code == 202
    did = r.json()["id"]
    try:
        d = row(client, did)
        assert d["status"] == "failed" and d["error"]
        again = client.post(f"/documents/{did}/retry")                          # thử lại: vẫn lỗi vì file hỏng
        assert again.status_code == 202 and again.json()["status"] == "processing"
        assert row(client, did)["status"] == "failed"
    finally:
        client.delete(f"/documents/{did}")


def test_retry_only_for_failed_and_admin_only(client):
    r = client.post("/documents/upload", files=txt())
    did = r.json()["id"]
    try:
        assert client.post(f"/documents/{did}/retry").status_code == 409        # đã processed
        h, c = (lambda t: (t[1], t[3]))(make_user())
        assert c.post(f"/documents/{did}/retry", headers=h).status_code == 403
        assert client.post(f"/documents/{uuid.uuid4()}/retry").status_code == 409
    finally:
        client.delete(f"/documents/{did}")


def test_stale_processing_is_marked_failed(client):
    info = docs.start_upload("treo.txt", None, f"treo {uuid.uuid4()}".encode())
    did = info["id"]
    try:
        assert docs.fail_stale(60) == 0                                         # mới tạo: chưa quá hạn
        query("UPDATE documents SET created_at = NOW() - interval '1 hour' WHERE id = %s", (did,), False)
        assert docs.fail_stale(60) >= 1
        d = row(client, did)
        assert d["status"] == "failed" and "gián đoạn" in d["error"]
        assert client.post(f"/documents/{did}/retry").status_code == 202        # retry chạy lại và thành công
        assert row(client, did)["status"] == "processed"
    finally:
        client.delete(f"/documents/{did}")


def test_xlsx_and_pptx_upload_end_to_end_and_are_searchable(client):
    import sys
    sys.path.insert(0, "tests")
    from test_extract_formats import make_pptx
    from openpyxl import Workbook
    import io
    token = uuid.uuid4().hex[:8]
    wb = Workbook(); ws = wb.active
    ws.append(["Sản phẩm", "Mã hàng"]); ws.append(["Máy bơm", f"MH{token}"])
    buf = io.BytesIO(); wb.save(buf)
    ids = []
    try:
        for name, data, mime in [
            (f"bang-{token}.xlsx", buf.getvalue(), "application/octet-stream"),
            (f"slide-{token}.pptx", make_pptx(), "application/octet-stream"),
        ]:
            r = client.post("/documents/upload", files={"file": (name, data, mime)})
            assert r.status_code == 202, r.text
            ids.append(r.json()["id"])
        assert row(client, ids[0])["status"] == "processed"
        hit = client.get("/search", params={"q": f"MH{token}", "mode": "keyword"}).json()
        assert ids[0] in {d["document_id"] for d in hit["results"]}
        assert row(client, ids[1])["status"] == "processed"
    finally:
        for did in ids:
            client.delete(f"/documents/{did}")
