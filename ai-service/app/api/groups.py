"""Quản lý nhóm người dùng (chỉ admin). Gán nhóm cho tài liệu nằm ở PUT /documents/{id}/groups."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..schemas import GroupBody, IdsBody
from ..services import groups, mailer
from .deps import require_admin

router = APIRouter(tags=["groups"], dependencies=[Depends(require_admin)])


def _run(action, *args):
    try:
        return action(*args)
    except groups.GroupError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)


@router.get("/groups")
def list_groups():
    return groups.list_groups()


@router.post("/groups")
def create_group(b: GroupBody):
    return _run(groups.create_group, b.name, b.description)


@router.get("/groups/{group_id}")
def get_group(group_id: str):
    return _run(groups.get_group, group_id)


@router.put("/groups/{group_id}")
def update_group(group_id: str, b: GroupBody):
    return _run(groups.update_group, group_id, b.name, b.description)


@router.delete("/groups/{group_id}")
def delete_group(group_id: str):
    _run(groups.delete_group, group_id)
    return {"deleted": group_id}


@router.put("/groups/{group_id}/members")
def set_members(group_id: str, b: IdsBody, background: BackgroundTasks):
    group, added = _run(groups.apply_members, group_id, b.ids)
    for u in added:  # báo cho người MỚI được thêm; gửi nền, lỗi thư không làm hỏng thao tác
        background.add_task(mailer.send_safely, *groups.membership_mail(u["email"], group))
    return {**group, "added": [u["email"] for u in added]}
