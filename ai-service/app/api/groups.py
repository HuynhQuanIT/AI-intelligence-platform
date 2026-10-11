"""Quản lý nhóm người dùng (chỉ admin). Gán nhóm cho tài liệu nằm ở PUT /documents/{id}/groups."""
from fastapi import APIRouter, Depends, HTTPException

from ..schemas import GroupBody, IdsBody
from ..services import groups
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
def set_members(group_id: str, b: IdsBody):
    return _run(groups.set_members, group_id, b.ids)
