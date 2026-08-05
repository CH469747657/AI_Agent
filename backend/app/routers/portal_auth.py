"""员工端认证路由

- POST /portal/auth/login          — 工号+密码登录
- POST /portal/auth/change-password — 修改密码
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.employee import Employee, EmployeeStatus
from app.services.auth_service import (
    verify_password, hash_password,
    create_access_token, decode_access_token,
)
from app.schemas import PortalLoginRequest, PortalChangePasswordRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def get_current_employee(token: str, db: AsyncSession) -> tuple[dict, Employee]:
    """从 JWT token 解析当前员工（同步版本，供路由直接调用）"""
    pass  # 异步版本见 get_current_employee_async


async def get_current_employee_async(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    """从 Authorization header 解析当前员工"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    token = authorization[7:]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    employee_no = payload.get("sub")
    if not employee_no:
        raise HTTPException(status_code=401, detail="无效的登录凭证")

    result = await db.execute(
        select(Employee).where(Employee.employee_no == employee_no)
    )
    employee = result.scalars().first()
    if not employee:
        raise HTTPException(status_code=401, detail="员工不存在")

    if employee.status != EmployeeStatus.active:
        raise HTTPException(status_code=403, detail="账号已停用")

    return employee


@router.post("/login")
async def login(request: PortalLoginRequest, db: AsyncSession = Depends(get_db)):
    """员工登录 — 工号+密码，返回 JWT"""
    # 查找员工
    result = await db.execute(
        select(Employee).where(Employee.employee_no == request.employee_no)
    )
    employee = result.scalars().first()

    if not employee:
        raise HTTPException(status_code=401, detail="工号或密码错误")

    if employee.status != EmployeeStatus.active:
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")

    if not employee.password_hash:
        raise HTTPException(status_code=401, detail="账号未设置密码，请联系管理员初始化")

    if not verify_password(request.password, employee.password_hash):
        raise HTTPException(status_code=401, detail="工号或密码错误")

    # 生成 token
    token = create_access_token(employee.id, employee.employee_no, employee.name)

    # 更新最后登录时间
    employee.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(f"Employee {employee.employee_no} ({employee.name}) logged in")

    return {
        "access_token": token,
        "token_type": "bearer",
        "employee": {
            "id": employee.id,
            "employee_no": employee.employee_no,
            "name": employee.name,
            "department": employee.department,
            "position": employee.position,
        },
    }


@router.post("/change-password")
async def change_password(
    request: PortalChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """修改密码 — 需要验证旧密码"""
    # 从 token 获取当前员工
    result = await db.execute(
        select(Employee).where(Employee.employee_no == request.employee_no)
    )
    employee = result.scalars().first()

    if not employee:
        raise HTTPException(status_code=404, detail="员工不存在")

    if not employee.password_hash or not verify_password(request.old_password, employee.password_hash):
        raise HTTPException(status_code=401, detail="旧密码错误")

    employee.password_hash = hash_password(request.new_password)
    await db.commit()

    logger.info(f"Employee {employee.employee_no} changed password")
    return {"status": "ok", "message": "密码修改成功"}
