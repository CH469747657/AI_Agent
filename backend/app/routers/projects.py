"""项目管理路由"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project, ProjectStatus
from app.routers.admin_auth import get_current_admin, get_current_admin_or_boss
from app.schemas import ProjectCreateRequest, ProjectResponse

router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])


@router.post("", response_model=ProjectResponse)
async def create_project(
    request: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """创建项目"""
    project = Project(
        name=request.name,
        code=request.code,
        member_ids=request.member_ids,
        supplier_names=request.supplier_names,
        description=request.description,
        status=ProjectStatus.active,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectResponse])
async def list_projects(status: str = None, db: AsyncSession = Depends(get_db)):
    """获取项目列表"""
    query = select(Project).order_by(Project.created_at.desc())
    if status:
        query = query.where(Project.status == ProjectStatus(status))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}/members")
async def update_members(
    project_id: int,
    member_ids: list[str],
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """更新项目关联人员"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.member_ids = member_ids
    await db.commit()
    return {"status": "ok", "member_ids": member_ids}
