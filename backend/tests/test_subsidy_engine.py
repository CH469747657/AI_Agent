"""补贴计算引擎单元测试 — 节假日判定 + 补贴标准

覆盖：
- day_type：工作日/周末/法定假日/调休补班
- subsidy_rate：60/80 元判定
- 跨年、调休补班等边界场景
- recompute_subsidies 数据源切换为 travel_days（新规则）
"""

import sys
import os
import asyncio
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.subsidy_engine import (
    day_type,
    subsidy_rate,
    recompute_subsidies,
    WORKDAY_RATE,
    RESTDAY_RATE,
)
from app.database import get_async_sessionmaker, get_engine
from app.models.reimbursement import (
    Reimbursement,
    ReimbursementItem,
    ReimbursementTravelDay,
    ReimbursementDaySubsidy,
    ReimbursementStatus,
)
from app.models.invoice import Invoice, InvoiceStatus, ReceiptType
from sqlalchemy import select, func, delete
from decimal import Decimal


def _clear_engine_cache():
    """每个 async 测试后清缓存，避免 pool 跨 event loop 复用导致 'Event loop is closed'"""
    try:
        get_engine.cache_clear()
        get_async_sessionmaker.cache_clear()
    except Exception:
        pass


class TestDayType:
    def test_monday_is_workday(self):
        """2026-07-06（周一）→ workday"""
        assert day_type(date(2026, 7, 6), {}) == "workday"

    def test_saturday_is_weekend(self):
        """2026-07-04（周六）→ weekend"""
        assert day_type(date(2026, 7, 4), {}) == "weekend"

    def test_sunday_is_weekend(self):
        """2026-07-05（周日）→ weekend"""
        assert day_type(date(2026, 7, 5), {}) == "weekend"

    def test_holiday_overrides_weekday(self):
        """法定假日（落在工作日）→ holiday"""
        # 假设 2026-10-01 国庆
        holidays = {date(2026, 10, 1): "holiday"}
        assert day_type(date(2026, 10, 1), holidays) == "holiday"

    def test_holiday_overrides_weekend(self):
        """法定假日（落在周末）→ holiday"""
        holidays = {date(2026, 10, 3): "holiday"}  # 假设国庆假期含周末
        assert day_type(date(2026, 10, 3), holidays) == "holiday"

    def test_makeup_workday_overrides_weekend(self):
        """调休补班日（周末但上班）→ workday"""
        # 2026-10-10 是周六，但调休补班
        holidays = {date(2026, 10, 10): "workday"}
        assert day_type(date(2026, 10, 10), holidays) == "workday"


class TestSubsidyRate:
    def test_workday_rate(self):
        assert subsidy_rate(date(2026, 7, 6), {}) == WORKDAY_RATE  # 60

    def test_weekend_rate(self):
        assert subsidy_rate(date(2026, 7, 4), {}) == RESTDAY_RATE  # 80

    def test_holiday_rate(self):
        """法定假日 → 80"""
        holidays = {date(2026, 10, 1): "holiday"}
        assert subsidy_rate(date(2026, 10, 1), holidays) == RESTDAY_RATE  # 80

    def test_makeup_workday_rate(self):
        """调休补班日 → 60（虽然是周末但补班）"""
        holidays = {date(2026, 10, 10): "workday"}
        assert subsidy_rate(date(2026, 10, 10), holidays) == WORKDAY_RATE  # 60

    def test_normal_friday_rate(self):
        """普通周五 → 60"""
        assert subsidy_rate(date(2026, 7, 3), {}) == WORKDAY_RATE  # 周五


class TestSubsidyRateValues:
    """补贴标准值验证"""

    def test_workday_is_60(self):
        assert WORKDAY_RATE == Decimal("60")

    def test_restday_is_80(self):
        assert RESTDAY_RATE == Decimal("80")


# ============================================================
# 新规则验证：补贴触发源从 items 改为 travel_days
# ============================================================

async def _create_test_reimbursement(db) -> Reimbursement:
    """在事务里造一个测试用报销单（cycle_key=2026-08）"""
    from app.services.cycle_engine import billing_cycle
    cycle_key = "2026-08"
    cycle_start, cycle_end = billing_cycle(cycle_key)
    reimb = Reimbursement(
        applicant_id="TEST_SUBSIDY_ENGINE",
        applicant_name="测试用户",
        department="测试部门",
        period=cycle_key,
        cycle_key=cycle_key,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        status=ReimbursementStatus.draft,
        auto_generated=False,
    )
    db.add(reimb)
    await db.flush()
    return reimb


async def _subsidy_only_counts_travel_days_scenario():
    """场景：报销单有发票 + item 但无 travel_day → subsidy_total 应=0（新规则）"""
    async with get_async_sessionmaker()() as db:
        reimb = await _create_test_reimbursement(db)
        applicant_id = reimb.applicant_id

        # 选周期内一个日期
        test_date = reimb.cycle_start + (reimb.cycle_end - reimb.cycle_start) // 2

        # 插入一个 item（带日期）— 旧规则会触发补贴，新规则不触发
        inv = Invoice(
            receipt_type=ReceiptType.receipt,
            file_path="/tmp/test_subsidy_only.pdf",
            file_type="pdf",
            user_id=applicant_id,
            amount="100.00",
            total_with_tax="100.00",
            status=InvoiceStatus.confirmed,
        )
        db.add(inv)
        await db.flush()
        item = ReimbursementItem(
            reimbursement_id=reimb.id,
            invoice_id=inv.id,
            item_date=test_date,
            weekday=test_date.weekday(),
            fee_category="personal",
            fee_subcategory="差旅-交通",
            amount=100.0,
            is_late_charge=False,
            sort_order=0,
        )
        db.add(item)
        await db.flush()

        # 跑重算（新规则：读 travel_days，无 → 不应生成 day_subsidy）
        subsidy_total = await recompute_subsidies(db, reimb)

        # 断言：无 travel_day → subsidy_total=0
        assert subsidy_total == 0, f"无 travel_day 时补贴应=0，实际 {subsidy_total}"

        # 进一步：day_subsidies 表里也不该有 test_date 这行
        ds_count = (
            await db.execute(
                select(func.count(ReimbursementDaySubsidy.id)).where(
                    ReimbursementDaySubsidy.reimbursement_id == reimb.id,
                    ReimbursementDaySubsidy.subsidy_date == test_date,
                )
            )
        ).scalar() or 0
        assert ds_count == 0, f"无 travel_day 时 day_subsidies 不应有该天行，实际 {ds_count} 行"

        # rollback：保护真实数据
        await db.rollback()
        _clear_engine_cache()
        return True


async def test_subsidy_only_counts_travel_days():
    """新规则：有发票但无 travel_days → subsidy_total=0"""
    result = await _subsidy_only_counts_travel_days_scenario()
    assert result is True


async def _subsidy_counts_travel_days_scenario():
    async with get_async_sessionmaker()() as db:
        reimb = await _create_test_reimbursement(db)
        applicant_id = reimb.applicant_id
        test_date = reimb.cycle_start + (reimb.cycle_end - reimb.cycle_start) // 2

        # 标一个 travel_day
        td = ReimbursementTravelDay(
            reimbursement_id=reimb.id,
            travel_date=test_date,
            note=None,
            weekday=test_date.weekday(),
            day_type="workday",
            base_rate=60.0,
            applicant_id=applicant_id,
        )
        db.add(td)
        await db.flush()

        # 重算
        subsidy_total = await recompute_subsidies(db, reimb)

        # 断言：subsidy_total > 0
        assert subsidy_total > 0, f"标了 travel_day 后补贴应>0，实际 {subsidy_total}"

        # 断言：day_subsidies 表有该天行
        ds_count = (
            await db.execute(
                select(func.count(ReimbursementDaySubsidy.id)).where(
                    ReimbursementDaySubsidy.reimbursement_id == reimb.id,
                    ReimbursementDaySubsidy.subsidy_date == test_date,
                )
            )
        ).scalar() or 0
        assert ds_count == 1, f"标了 travel_day 后 day_subsidies 应有 1 行该天，实际 {ds_count} 行"

        await db.rollback()
        _clear_engine_cache()
        return True


async def test_subsidy_counts_travel_days():
    """新规则：标了 travel_day → day_subsidy 出现 + subsidy_total>0"""
    result = await _subsidy_counts_travel_days_scenario()
    assert result is True
