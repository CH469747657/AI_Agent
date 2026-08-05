"""员工管理路由

提供员工 CRUD 和企微通讯录同步功能。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.database import get_db
from app.models.employee import Employee, EmployeeStatus
from app.schemas import (
    EmployeeCreateRequest,
    EmployeeUpdateRequest,
    EmployeeResponse,
    EmployeeSyncResult,
)
from app.services.wecom_contact_service import get_contact_service
from app.services.auth_service import hash_password

router = APIRouter()


@router.get("", response_model=list[EmployeeResponse])
async def list_employees(
    keyword: str | None = Query(None, description="搜索姓名/工号/企微ID"),
    status: int | None = Query(None, description="状态: 1=在职 2=离职"),
    db: AsyncSession = Depends(get_db),
):
    """获取员工列表"""
    query = select(Employee).order_by(Employee.created_at.desc())
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            or_(
                Employee.name.ilike(pattern),
                Employee.employee_no.ilike(pattern),
                Employee.wecom_user_id.ilike(pattern),
                Employee.department.ilike(pattern),
            )
        )
    if status is not None:
        query = query.where(Employee.status == EmployeeStatus(status))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/sync", response_model=EmployeeSyncResult)
async def sync_from_wecom(db: AsyncSession = Depends(get_db)):
    """从企业微信通讯录同步员工信息

    前置条件：.env 中已配置 WECOM_CORP_ID 和 WECOM_SECRET，
    且企微管理后台为自建应用开通了通讯录读取权限。
    """
    service = get_contact_service()
    result = await service.sync(db)
    return result


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(employee_id: int, db: AsyncSession = Depends(get_db)):
    """获取员工详情"""
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = result.scalars().first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp


@router.post("", response_model=EmployeeResponse)
async def create_employee(
    request: EmployeeCreateRequest, db: AsyncSession = Depends(get_db)
):
    """手动添加员工"""
    # 手动创建时自动生成 wecom_user_id
    wecom_user_id = request.wecom_user_id
    if not wecom_user_id:
        prefix = f"manual_{request.employee_no}_" if request.employee_no else "manual_"
        wecom_user_id = f"{prefix}{uuid4().hex[:8]}"

    # 检查 wecom_user_id 唯一性
    existing = await db.execute(
        select(Employee).where(Employee.wecom_user_id == wecom_user_id)
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=409,
            detail=f"wecom_user_id '{wecom_user_id}' 已存在",
        )

    emp = Employee(
        wecom_user_id=wecom_user_id,
        name=request.name,
        employee_no=request.employee_no,
        department=request.department,
        department_id=request.department_id,
        position=request.position,
        mobile=request.mobile,
        email=request.email,
        status=EmployeeStatus(request.status),
    )

    # 如果请求中有密码字段，设置密码
    if request.password:
        emp.password_hash = hash_password(request.password)

    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


@router.put("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: int,
    request: EmployeeUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新员工信息"""
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = result.scalars().first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    update_data = request.model_dump(exclude_unset=True)
    # 处理密码更新
    password = update_data.pop('password', None)
    if password:
        emp.password_hash = hash_password(password)
    for field, value in update_data.items():
        if field == "status":
            emp.status = EmployeeStatus(value)
        else:
            setattr(emp, field, value)

    await db.commit()
    await db.refresh(emp)
    return emp


@router.delete("/{employee_id}")
async def delete_employee(employee_id: int, db: AsyncSession = Depends(get_db)):
    """删除员工"""
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    emp = result.scalars().first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    await db.delete(emp)
    await db.commit()
    return {"message": f"员工 {emp.name} 已删除", "deleted": True}
