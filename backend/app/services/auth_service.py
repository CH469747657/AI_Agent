"""员工端 JWT 认证服务

- 工号+密码登录
- JWT token 生成与验证
- 数据隔离：token 中携带 employee_no，portal 接口自动注入查询条件
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

logger = logging.getLogger(__name__)

# JWT 配置
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
JWT_SECRET = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET 未配置。请在 .env 中设置强随机字符串（推荐 openssl rand -hex 32 生成）。"
    )


def hash_password(password: str) -> str:
    """密码哈希（bcrypt）"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(employee_id: int, employee_no: str, name: str) -> str:
    """生成 JWT token"""
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": employee_no,       # 主题 = 工号
        "emp_id": employee_id,
        "name": name,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码并验证 JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError:
        logger.warning("Invalid JWT token")
        return None
