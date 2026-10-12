"""Nhóm người dùng + quyền xem tài liệu theo nhóm (danh sách, xem, tải file, RAG, công cụ agent)."""
import uuid

import pytest

from app.agents import tools
from app.core.db import query
from app.rag import retrieval
from app.rag.access import ADMIN, PUBLIC_ONLY, viewer_of
from app.services import ratelimit
from auth_helpers import add_doc, make_user

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_limits(client):
    ratelimit.reset()
    yield


def group(client, name=None):
    r = client.post("/groups", json={"name": name or f"Nhóm {uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def ids(r):
    return {d["id"] for d in r.json()}


@pytest.fixture
def setup(client):
    """Tài liệu công khai + tài liệu của nhóm A (thành viên: member) + người ngoài nhóm."""
    tag = uuid.uuid4().hex[:8]
    gid = group(client)
    _, hm, uidm, cm = make_user()
    _, ho, uido, co = make_user()
    client.put(f"/groups/{gid}/members", json={"ids": [uidm]})
    pub = add_doc(client, f"Công khai {tag}", f"zebrafish{tag} nội dung công khai cho mọi người")
    sec = add_doc(client, f"Bí mật {tag}", f"zebrafish{tag} nội dung bí mật chỉ nhóm A được xem")
    assert client.put(f"/documents/{sec}/groups", json={"ids": [gid]}).status_code == 200
    return dict(tag=tag, gid=gid, pub=pub, sec=sec, member=(hm, cm, uidm), outsider=(ho, co, uido))


def test_document_without_group_is_visible_to_everyone(client, setup):
    hm, cm, _ = setup["member"]
    ho, co, _ = setup["outsider"]
    assert setup["pub"] in ids(cm.get("/documents", headers=hm))
    assert setup["pub"] in ids(co.get("/documents", headers=ho))


def test_grouped_document_only_for_members_and_admin(client, setup):
    hm, cm, _ = setup["member"]
    ho, co, _ = setup["outsider"]
    sec = setup["sec"]
    assert sec in ids(cm.get("/documents", headers=hm))
    assert sec not in ids(co.get("/documents", headers=ho))
    assert sec in ids(client.get("/documents"))
    assert co.get(f"/documents/{sec}", headers=ho).status_code == 404         # 404, không lộ là có tồn tại
    assert cm.get(f"/documents/{sec}", headers=hm).status_code == 200
    assert client.get(f"/documents/{sec}").status_code == 200


def test_file_download_respects_groups(client, setup):
    hm, cm, _ = setup["member"]
    ho, co, _ = setup["outsider"]
    files = {"file": ("bi-mat.txt", f"noi dung rieng {uuid.uuid4()}".encode(), "text/plain")}
    up = client.post("/documents/upload", files=files)
    assert up.status_code == 202, up.text
    did = up.json()["id"]
    client.put(f"/documents/{did}/groups", json={"ids": [setup["gid"]]})
    assert co.get(f"/documents/{did}/file", headers=ho).status_code == 404
    assert cm.get(f"/documents/{did}/file", headers=hm).status_code == 200


def test_admin_sees_all_groups_user_only_own_in_list(client, setup):
    hm, cm, _ = setup["member"]
    row = next(d for d in client.get("/documents").json() if d["id"] == setup["sec"])
    assert row["groups"][0]["id"] == setup["gid"]
    ho, co, _ = setup["outsider"]
    assert all(d["groups"] == [] for d in co.get("/documents", headers=ho).json())  # người ngoài nhóm không thấy tên nhóm


def test_rag_retrieval_filters_by_viewer(client, setup):
    tag, sec = setup["tag"], setup["sec"]
    q = f"zebrafish{tag}"
    seen = lambda viewer: {h["document_id"] for h in retrieval.retrieve(q, 10, viewer)}
    assert sec in seen(ADMIN)
    assert sec in seen(viewer_of({"id": setup["member"][2], "role": "user"}))
    assert sec not in seen(viewer_of({"id": setup["outsider"][2], "role": "user"}))
    assert sec not in seen(PUBLIC_ONLY)


def test_agent_tools_filter_by_viewer(client, setup):
    sec, tag = setup["sec"], setup["tag"]
    out = viewer_of({"id": setup["outsider"][2], "role": "user"})
    mem = viewer_of({"id": setup["member"][2], "role": "user"})
    listing = lambda v: {d["document_id"] for d in tools.run_tool("list_documents", {"limit": 20}, v)["documents"]}
    assert sec in listing(mem) and sec not in listing(out)
    found = lambda v: {r["document_id"] for r in tools.run_tool("search_documents", {"query": f"zebrafish{tag}"}, v)["results"]}
    assert sec in found(mem) and sec not in found(out)
    with pytest.raises(tools.ToolError):
        tools.run_tool("read_document", {"document_id": sec}, out)
    assert tools.run_tool("read_document", {"document_id": sec}, mem)["returned"]


def test_chat_never_leaks_hidden_document_sources(client, setup):
    ho, co, _ = setup["outsider"]
    hm, cm, _ = setup["member"]
    q = {"message": f"zebrafish{setup['tag']} nội dung bí mật"}
    out_sources = {s["document_id"] for s in co.post("/chat", headers=ho, json=q).json()["sources"]}
    mem_sources = {s["document_id"] for s in cm.post("/chat", headers=hm, json=q).json()["sources"]}
    assert setup["sec"] not in out_sources
    assert setup["sec"] in mem_sources


def test_removing_membership_removes_access(client, setup):
    hm, cm, uidm = setup["member"]
    client.put(f"/groups/{setup['gid']}/members", json={"ids": []})
    assert setup["sec"] not in ids(cm.get("/documents", headers=hm))


def test_clearing_groups_makes_document_public(client, setup):
    ho, co, _ = setup["outsider"]
    client.put(f"/documents/{setup['sec']}/groups", json={"ids": []})
    assert setup["sec"] in ids(co.get("/documents", headers=ho))


def test_multiple_groups_any_membership_grants_access(client, setup):
    ho, co, uido = setup["outsider"]
    g2 = group(client)
    client.put(f"/groups/{g2}/members", json={"ids": [uido]})
    client.put(f"/documents/{setup['sec']}/groups", json={"ids": [setup["gid"], g2]})
    assert setup["sec"] in ids(co.get("/documents", headers=ho))


def test_cannot_delete_group_that_is_the_only_group_of_a_document(client, setup):
    r = client.delete(f"/groups/{setup['gid']}")
    assert r.status_code == 409
    g2 = group(client)
    client.put(f"/documents/{setup['sec']}/groups", json={"ids": [setup['gid'], g2]})
    assert client.delete(f"/groups/{setup['gid']}").status_code == 200
    ho, co, _ = setup["outsider"]
    assert setup["sec"] not in ids(co.get("/documents", headers=ho))          # vẫn kín vì còn g2


def test_deleting_document_or_user_cleans_links(client, setup):
    client.delete(f"/documents/{setup['sec']}")
    assert query("SELECT 1 FROM document_groups WHERE document_id = %s", (setup["sec"],)) == []
    client.delete(f"/users/{setup['member'][2]}")
    assert query("SELECT 1 FROM user_groups WHERE user_id = %s", (setup["member"][2],)) == []


def test_group_crud_validation_and_admin_only(client, setup):
    hm, cm, uidm = setup["member"]
    assert cm.get("/groups", headers=hm).status_code == 403
    assert cm.put(f"/documents/{setup['pub']}/groups", headers=hm, json={"ids": []}).status_code == 403
    assert client.post("/groups", json={"name": "   "}).status_code == 422
    name = f"Trùng {uuid.uuid4().hex[:6]}"
    group(client, name)
    assert client.post("/groups", json={"name": name.upper()}).status_code == 409
    assert client.put(f"/groups/{setup['gid']}/members", json={"ids": [str(uuid.uuid4())]}).status_code == 404
    assert client.put(f"/documents/{setup['pub']}/groups", json={"ids": [str(uuid.uuid4())]}).status_code == 404
    assert client.get("/groups/khong-phai-uuid").status_code == 404
    detail = client.get(f"/groups/{setup['gid']}").json()
    assert detail["document_count"] == 1 and detail["members"][0]["id"] == uidm
    renamed = f"Đã đổi tên {uuid.uuid4().hex[:6]}"
    assert client.put(f"/groups/{setup['gid']}", json={"name": renamed, "description": "d"}).json()["name"] == renamed


def test_user_detail_lists_groups(client, setup):
    d = client.get(f"/users/{setup['member'][2]}").json()
    assert [g["id"] for g in d["groups"]] == [setup["gid"]]


# ---- người dùng biết mình thuộc nhóm nào ----

def test_me_shows_my_groups_and_visible_documents(client, setup):
    hm, cm, _ = setup["member"]
    ho, co, _ = setup["outsider"]
    mine = cm.get("/auth/me", headers=hm).json()["access"]
    assert [g["id"] for g in mine["groups"]] == [setup["gid"]]
    assert mine["groups"][0]["document_count"] == 1 and mine["group_documents"] == 1
    other = co.get("/auth/me", headers=ho).json()["access"]
    assert other["groups"] == []
    assert mine["visible_documents"] == other["visible_documents"] + 1  # thành viên xem thêm đúng 1 tài liệu nhóm


def test_user_document_list_labels_scope_and_only_own_groups(client, setup):
    hm, cm, _ = setup["member"]
    other_gid = group(client)
    client.put(f"/documents/{setup['sec']}/groups", json={"ids": [setup["gid"], other_gid]})
    rows = {d["id"]: d for d in cm.get("/documents", headers=hm).json()}
    assert rows[setup["pub"]]["scope"] == "public" and rows[setup["pub"]]["groups"] == []
    sec = rows[setup["sec"]]
    assert sec["scope"] == "group"
    assert [g["id"] for g in sec["groups"]] == [setup["gid"]]  # không lộ nhóm khác của tài liệu


def test_adding_member_sends_mail_only_to_new_people(client, setup, monkeypatch):
    from app.services import mailer
    monkeypatch.setenv("MAIL_BACKEND", "memory")
    mailer.OUTBOX.clear()
    _, hn, uidn, cn = make_user()
    emails = {u["email"]: u["id"] for u in client.get("/users").json()}
    new_email = next(e for e, i in emails.items() if i == uidn)
    old_id = setup["member"][2]
    r = client.put(f"/groups/{setup['gid']}/members", json={"ids": [old_id, uidn]})
    assert r.status_code == 200 and r.json()["added"] == [new_email]
    sent = [m for m in mailer.OUTBOX if "được thêm vào nhóm" in m["subject"]]
    assert [m["to"] for m in sent] == [new_email]
    # lưu lại cùng danh sách: không ai mới, không gửi thêm
    mailer.OUTBOX.clear()
    assert client.put(f"/groups/{setup['gid']}/members", json={"ids": [old_id, uidn]}).json()["added"] == []
    assert not [m for m in mailer.OUTBOX if "được thêm vào nhóm" in m["subject"]]


def test_member_added_at_is_kept_when_saving_again(client, setup):
    gid, uid = setup["gid"], setup["member"][2]
    first = query("SELECT added_at FROM user_groups WHERE group_id=%s AND user_id=%s", (gid, uid))[0]["added_at"]
    client.put(f"/groups/{gid}/members", json={"ids": [uid]})
    again = query("SELECT added_at FROM user_groups WHERE group_id=%s AND user_id=%s", (gid, uid))[0]["added_at"]
    assert first == again


# ---- nguồn trích dẫn có nhãn nhóm ----

def ask(c, h, tag):
    r = c.post("/chat", json={"message": f"zebrafish{tag} nội dung", "use_rag": True}, headers=h)
    assert r.status_code == 200, r.text
    return {s["document_id"]: s for s in r.json()["sources"]}


def test_chat_sources_carry_group_labels(client, setup):
    hm, cm, _ = setup["member"]
    ho, co, _ = setup["outsider"]
    other = group(client)
    client.put(f"/documents/{setup['sec']}/groups", json={"ids": [setup["gid"], other]})
    tag = setup["tag"]

    member = ask(cm, hm, tag)
    assert member[setup["pub"]]["scope"] == "public" and member[setup["pub"]]["groups"] == []
    sec = member[setup["sec"]]
    assert sec["scope"] == "group" and [g["id"] for g in sec["groups"]] == [setup["gid"]]  # chỉ nhóm của mình

    assert setup["sec"] not in ask(co, ho, tag)                                  # người ngoài không thấy nguồn nhóm

    admin_sec = {s["document_id"]: s for s in client.post(
        "/chat", json={"message": f"zebrafish{tag} nội dung", "use_rag": True}).json()["sources"]}[setup["sec"]]
    assert {g["id"] for g in admin_sec["groups"]} == {setup["gid"], other}      # admin thấy đủ nhóm
