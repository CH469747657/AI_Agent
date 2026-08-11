"""补贴计算引擎单元测试 — 节假日判定 + 补贴标准

覆盖：
- day_type：工作日/周末/法定假日/调休补班
- subsidy_rate：60/80 元判定
- 跨年、调休补班等边界场景
"""

import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.subsidy_engine import day_type, subsidy_rate, WORKDAY_RATE, RESTDAY_RATE
from decimal import Decimal


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
