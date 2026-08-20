"""管理端认证路由 + 鉴权依赖

- POST /api/admin/auth/login — 管理员登录（admin/123456，账户密码从 .env 读取）
- POST /api/admin/auth/change-password — 修改管理员密码（写入数据库 system_settings 表）
- get_current_admin — 管理端接口的鉴权依赖

与员工端 portal_auth 的区别：
- 员工端：账户在 employees 表，多账号，工号+密码
- 管理端：单一管理员账号，账户名从 .env 读取（ADMIN_USERNAME），
  密码哈希优先从数据库 system_settings.admin_password_hash 读取，
  数据库为空时回退到 .env 的 ADMIN_PASSWORD_HASH

token 隔离：管理端 token payload 含 role=admin，与员工端 portal_token 物理隔离
（前端 localStorage 用 admin_token 字段，员工端用 portal_token 字段）
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.settings import SystemSettings
from app.services.auth_service import (
    verify_password,
    hash_password,
    create_access_token,
    decode_access_token,
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class AdminLoginRequest(BaseModel):
    """管理员登录请求"""
    username: str
    password: str


class AdminChangePasswordRequest(BaseModel):
    """管理员改密请求"""
    old_password: str = Field(..., description="当前密码")
    new_password: str = Field(..., min_length=6, description="新密码，至少6位")


async def _get_admin_credentials(db: AsyncSession) -> tuple[str, str]:
    """读取管理员账户名和密码哈希

    密码哈希优先级：
    1. 数据库 system_settings.admin_password_hash（改密后写入）
    2. .env ADMIN_PASSWORD_HASH（初始默认值）

    Returns:
        (username, password_hash)
    """
    username = settings.admin_username
    if not username:
        raise RuntimeError("ADMIN_USERNAME 未配置，请在 .env 设置 ADMIN_USERNAME=admin")

    # 优先从数据库读取改密后的哈希
    row = (await db.execute(select(SystemSettings).where(SystemSettings.id == 1))).scalar_one_or_none()
    if row and row.admin_password_hash:
        return username, row.admin_password_hash

    # 数据库无记录 → 回退到 .env
    password_hash = settings.admin_password_hash
    if not password_hash:
        raise RuntimeError(
            "ADMIN_PASSWORD_HASH 未配置。"
            "请在 .env 设置 ADMIN_PASSWORD_HASH=<bcrypt哈希值>。"
            "生成哈希：python -c \"from app.services.auth_service import hash_password; print(hash_password('123456'))\""
        )
    return username, password_hash


async def get_current_admin(authorization: str = Header(None)) -> dict[str, Any]:
    """管理端接口鉴权依赖

    校验 Authorization: Bearer <token>，token 必须含 role=admin。
    与员工端 get_current_employee_async 完全独立，互不通用。
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    token = authorization[7:]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="非管理员账号，无权访问管理端")

    return {
        "username": payload.get("sub"),
        "name": payload.get("name", "管理员"),
        "role": "admin",
    }


@router.post("/login")
async def admin_login(request: AdminLoginRequest, db: AsyncSession = Depends(get_db)):
    """管理员登录 — 用户名+密码，返回 JWT

    账户密码从 .env 读取（ADMIN_USERNAME / ADMIN_PASSWORD_HASH），
    默认 admin / 123456（生产环境请修改）。
    """
    username, password_hash = await _get_admin_credentials(db)

    if request.username != username:
        logger.warning(f"Admin login failed: wrong username={request.username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(request.password, password_hash):
        logger.warning(f"Admin login failed: wrong password for username={request.username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 生成管理员 token — payload 含 role=admin，与员工 token 区分
    import jwt
    from app.services.auth_service import JWT_SECRET, JWT_ALGORITHM
    from datetime import timedelta
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": username,
        "emp_id": 0,
        "name": "管理员",
        "role": "admin",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    logger.info(f"Admin {username} logged in")

    return {
        "access_token": token,
        "token_type": "bearer",
        "admin": {
            "username": username,
            "name": "管理员",
            "role": "admin",
        },
    }


@router.post("/change-password")
async def admin_change_password(
    request: AdminChangePasswordRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """修改管理员密码

    校验旧密码后，把新密码的 bcrypt 哈希写入 system_settings.admin_password_hash。
    下次登录时 _get_admin_credentials 会优先从数据库读取新哈希。
    """
    username, old_hash = await _get_admin_credentials(db)

    if not verify_password(request.old_password, old_hash):
        raise HTTPException(status_code=400, detail="当前密码错误")

    if request.old_password == request.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    new_hash = hash_password(request.new_password)

    # 写入数据库（首次改密时创建 system_settings 行）
    row = (await db.execute(select(SystemSettings).where(SystemSettings.id == 1))).scalar_one_or_none()
    if row is None:
        row = SystemSettings(id=1, admin_password_hash=new_hash)
        db.add(row)
    else:
        row.admin_password_hash = new_hash

    await db.commit()
    logger.info(f"Admin {username} changed password")

    return {"message": "密码修改成功，下次登录请使用新密码"}


# ============================================================
# 老板端认证（BOSS）— 复用 admin_auth 的 JWT 机制，独立路由前缀
# ============================================================

boss_router = APIRouter()


class BossLoginRequest(BaseModel):
    """老板端登录请求"""
    username: str
    password: str


class BossChangePasswordRequest(BaseModel):
    """老板端改密请求"""
    old_password: str = Field(..., description="当前密码")
    new_password: str = Field(..., min_length=6, description="新密码，至少6位")


async def _get_boss_credentials(db: AsyncSession) -> tuple[str, str]:
    """读取老板账户名和密码哈希

    密码哈希优先级：
    1. 数据库 system_settings.boss_password_hash（改密后写入）
    2. .env BOSS_PASSWORD_HASH（初始默认值）

    Returns: (username, password_hash)
    """
    username = settings.boss_username
    if not username:
        raise RuntimeError("BOSS_USERNAME 未配置")

    row = (await db.execute(select(SystemSettings).where(SystemSettings.id == 1))).scalar_one_or_none()
    if row and row.boss_password_hash:
        return username, row.boss_password_hash

    password_hash = settings.boss_password_hash
    if not password_hash:
        raise RuntimeError("BOSS_PASSWORD_HASH 未配置")
    return username, password_hash


@boss_router.post("/login")
async def boss_login(
    request: BossLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """老板端登录 — 用户名+密码，返回 JWT (role=boss)

    凭证优先从数据库读取（改密后），回退到 .env。
    """
    try:
        username, password_hash = await _get_boss_credentials(db)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail="老板账号未配置")

    if request.username != username:
        logger.warning(f"Boss login failed: wrong username={request.username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(request.password, password_hash):
        logger.warning(f"Boss login failed: wrong password for username={request.username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    import jwt
    from app.services.auth_service import JWT_SECRET, JWT_ALGORITHM
    from datetime import timedelta
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": username,
        "emp_id": 0,
        "name": "老板",
        "role": "boss",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    logger.info(f"Boss {username} logged in")

    return {
        "access_token": token,
        "token_type": "bearer",
        "profile": {
            "username": username,
            "name": "老板",
            "role": "boss",
        },
    }


async def get_current_boss(authorization: str = Header(None)) -> dict[str, Any]:
    """老板端接口鉴权依赖 — token 必须含 role=boss"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    token = authorization[7:]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    if payload.get("role") != "boss":
        raise HTTPException(status_code=403, detail="非老板账号，无权访问老板端")

    return {
        "username": payload.get("sub"),
        "name": payload.get("name", "老板"),
        "role": "boss",
    }


@boss_router.post("/change-password")
async def boss_change_password(
    request: BossChangePasswordRequest,
    boss: dict = Depends(get_current_boss),
    db: AsyncSession = Depends(get_db),
):
    """修改老板端密码

    校验旧密码后，把新密码的 bcrypt 哈希写入 system_settings.boss_password_hash。
    下次登录时 _get_boss_credentials 会优先从数据库读取新哈希。
    """
    _, old_hash = await _get_boss_credentials(db)

    if not verify_password(request.old_password, old_hash):
        raise HTTPException(status_code=400, detail="当前密码错误")

    if request.old_password == request.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    new_hash = hash_password(request.new_password)

    row = (await db.execute(select(SystemSettings).where(SystemSettings.id == 1))).scalar_one_or_none()
    if row is None:
        row = SystemSettings(id=1, boss_password_hash=new_hash)
        db.add(row)
    else:
        row.boss_password_hash = new_hash

    await db.commit()
    logger.info(f"Boss {boss['username']} changed password")

    return {"message": "密码修改成功，下次登录请使用新密码"}


async def get_current_admin_or_boss(authorization: str = Header(None)) -> dict[str, Any]:
    """管理端/老板端通用鉴权依赖

    允许 admin 或 boss JWT 通过，返回 {"sub","name","role"}。
    用于在 GET 路由上放宽权限让 BOSS 也能读，写路由仍用 get_current_admin。
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    token = authorization[7:]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    role = payload.get("role")
    if role not in ("admin", "boss"):
        raise HTTPException(status_code=403, detail="需要管理员或老板权限")

    return {
        "username": payload.get("sub"),
        "name": payload.get("name", ""),
        "role": role,
    }
