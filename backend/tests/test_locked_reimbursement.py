"""封账后禁止操作测试 — assert_not_locked helper"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.models.reimbursement import Reimbursement, ReimbursementStatus
from app.services.reimbursement_service import assert_not_locked


def _make_reimb(locked: bool) -> Reimbursement:
    """构造测试用 reimbursement 对象"""
    r = MagicMock(spec=Reimbursement)
    r.id = 1
    r.is_cycle_locked = locked
    r.locked_at = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc) if locked else None
    r.status = ReimbursementStatus.draft
    return r


class TestAssertNotLocked:
    async def test_not_locked_passes(self):
        """未封账 → 不抛异常"""
        reimb = _make_reimb(locked=False)
        # 不抛异常即通过
        await assert_not_locked(reimb)

    async def test_locked_raises_409(self):
        """已封账 → 抛 409"""
        reimb = _make_reimb(locked=True)
        with pytest.raises(HTTPException) as exc_info:
            await assert_not_locked(reimb)
        assert exc_info.value.status_code == 409
        assert "已封账" in exc_info.value.detail
        assert "2026-09-20" in exc_info.value.detail  # locked_at 格式化

    async def test_locked_without_locked_at(self):
        """已封账但 locked_at 为空 → 409 详情含「未知时间」"""
        reimb = _make_reimb(locked=True)
        reimb.locked_at = None
        with pytest.raises(HTTPException) as exc_info:
            await assert_not_locked(reimb)
        assert "未知时间" in exc_info.value.detail
