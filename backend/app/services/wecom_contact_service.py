"""企业微信通讯录同步服务

从企业微信通讯录 API 拉取成员信息，upsert 到 employees 表。

前置条件：
  1. docker-compose.yml 中 backend 传入 WECOM_CORP_ID 和 WECOM_SECRET
  2. 企微管理后台为自建应用开通「通讯录」读取权限
  3. 如果 secret 是自建应用的 secret，需确保该应用可见范围覆盖全部部门

API 流程：
  1. 获取 access_token (corp_id + secret)
  2. 获取部门列表 /cgi-bin/department/list
  3. 对根部门调用 /cgi-bin/user/list?department_id=X&fetch_child=1 递归获取全部成员
"""

import os
import time
import logging
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee, EmployeeStatus

logger = logging.getLogger(__name__)

WECOM_CONTACT_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
WECOM_DEPT_LIST_URL = "https://qyapi.weixin.qq.com/cgi-bin/department/list"
WECOM_USER_LIST_URL = "https://qyapi.weixin.qq.com/cgi-bin/user/list"

# 进程级 access_token 缓存
_token_cache: dict = {"token": None, "expires_at": 0.0}


class WeComContactService:
    """企微通讯录同步服务"""

    def __init__(self):
        self.corp_id = os.getenv("WECOM_CORP_ID", "")
        self.secret = os.getenv("WECOM_SECRET", "")
        self.enabled = bool(self.corp_id and self.secret)

    def _get_access_token(self) -> str:
        """获取企微 access_token（带缓存，有效期 7200s，提前 5 分钟刷新）"""
        if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
            return _token_cache["token"]

        if not self.enabled:
            raise RuntimeError("企微通讯录同步未配置（WECOM_CORP_ID / WECOM_SECRET 为空）")

        params = {"corpid": self.corp_id, "corpsecret": self.secret}
        resp = httpx.get(WECOM_CONTACT_TOKEN_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        errcode = data.get("errcode", 0)
        if errcode != 0:
            raise RuntimeError(f"企微获取 access_token 失败: [{errcode}] {data.get('errmsg')}")

        token = data["access_token"]
        expires_in = data.get("expires_in", 7200)
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + expires_in - 300

        logger.info(f"企微 access_token 已刷新，有效期 {expires_in}s")
        return token

    def _invalidate_token(self):
        _token_cache["token"] = None
        _token_cache["expires_at"] = 0.0

    async def sync(self, db: AsyncSession) -> dict:
        """拉取企微通讯录并 upsert 到 employees 表

        Returns:
            {"total": 拉取到的成员数, "created": 新增数, "updated": 更新数, "errors": 错误列表}
        """
        if not self.enabled:
            return {
                "total": 0, "created": 0, "updated": 0,
                "errors": ["企微通讯录同步未配置（WECOM_CORP_ID / WECOM_SECRET 为空），请在 .env 中配置后重启"],
            }

        token = self._get_access_token()

        # 1. 获取部门列表
        try:
            resp = httpx.get(
                WECOM_DEPT_LIST_URL,
                params={"access_token": token},
                timeout=10,
            )
            resp.raise_for_status()
            dept_data = resp.json()
        except Exception as e:
            logger.error(f"获取部门列表失败: {e}")
            return {"total": 0, "created": 0, "updated": 0, "errors": [f"获取部门列表失败: {e}"]}

        if dept_data.get("errcode", 0) != 0:
            err = f"[{dept_data.get('errcode')}] {dept_data.get('errmsg')}"
            logger.error(f"企微部门列表 API 错误: {err}")
            # token 过期
            if dept_data.get("errcode") in (40014, 42001):
                self._invalidate_token()
            return {"total": 0, "created": 0, "updated": 0, "errors": [f"部门列表 API 错误: {err}"]}

        departments = dept_data.get("department", [])
        # 建立部门 ID → 名称映射
        dept_map = {d["id"]: d.get("name", "") for d in departments}

        # 2. 对每个部门获取成员（同时追踪已处理过的 userid 避免重复）
        seen_userids: set[str] = set()
        created = 0
        updated = 0
        errors = []

        async with httpx.AsyncClient(timeout=15) as client:
            for dept in departments:
                dept_id = dept["id"]
                dept_name = dept.get("name", "")
                cursor = 0
                while True:
                    try:
                        resp = await client.get(
                            WECOM_USER_LIST_URL,
                            params={
                                "access_token": token,
                                "department_id": dept_id,
                                "fetch_child": 0,  # 逐部门获取以避免超时
                            },
                        )
                        resp.raise_for_status()
                        user_data = resp.json()
                    except Exception as e:
                        errors.append(f"部门 {dept_name}({dept_id}) 成员列表获取失败: {e}")
                        logger.error(f"部门 {dept_id} 成员列表获取失败: {e}")
                        break

                    if user_data.get("errcode", 0) != 0:
                        err = f"部门 {dept_name}: [{user_data.get('errcode')}] {user_data.get('errmsg')}"
                        errors.append(err)
                        logger.error(err)
                        break

                    members = user_data.get("userlist", [])
                    for m in members:
                        userid = m.get("userid", "")
                        if not userid or userid in seen_userids:
                            continue
                        seen_userids.add(userid)

                        # upsert
                        result = await db.execute(
                            select(Employee).where(Employee.wecom_user_id == userid)
                        )
                        emp = result.scalars().first()

                        # 部门名称：取成员主部门名
                        main_dept_id = (m.get("department") or [dept_id])
                        main_dept_id = main_dept_id[0] if main_dept_id else dept_id
                        main_dept_name = dept_map.get(main_dept_id, dept_name)

                        if emp is None:
                            # 新增
                            emp = Employee(
                                wecom_user_id=userid,
                                name=m.get("name", userid),
                                department=main_dept_name,
                                department_id=main_dept_id,
                                position=m.get("position"),
                                mobile=m.get("mobile"),
                                email=m.get("email"),
                                status=EmployeeStatus.active if m.get("status", 1) == 1 else EmployeeStatus.resigned,
                            )
                            db.add(emp)
                            created += 1
                        else:
                            # 更新
                            emp.name = m.get("name", emp.name)
                            emp.department = main_dept_name or emp.department
                            emp.department_id = main_dept_id or emp.department_id
                            emp.position = m.get("position") or emp.position
                            emp.mobile = m.get("mobile") or emp.mobile
                            emp.email = m.get("email") or emp.email
                            emp.status = EmployeeStatus.active if m.get("status", 1) == 1 else EmployeeStatus.resigned
                            updated += 1

                    # fetch_child=0 一次返回所有成员，无需分页
                    break

        await db.commit()

        total = len(seen_userids)
        logger.info(f"企微通讯录同步完成: total={total}, created={created}, updated={updated}, errors={len(errors)}")
        return {"total": total, "created": created, "updated": updated, "errors": errors}


_contact_service: Optional[WeComContactService] = None


def get_contact_service() -> WeComContactService:
    global _contact_service
    if _contact_service is None:
        _contact_service = WeComContactService()
    return _contact_service
