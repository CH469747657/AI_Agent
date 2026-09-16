"""cycle_engine cycle_end_day 算法测试（新语义：cycle_end_day 是本月最后一天含）"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from app.services.cycle_engine import (
    billing_cycle, cycle_key_of, current_cycle_key, just_ended_cycle_key,
)


class TestBillingCycle:
    def test_default_20_keeps_21_20_semantics(self):
        """cycle_end_day=20 → 21-20 制（21 号属下月，20 号是本月最后一天）"""
        start, end = billing_cycle("2026-09")
        assert start == date(2026, 8, 21)
        assert end == date(2026, 9, 20)

    def test_cycle_end_day_25(self):
        """cycle_end_day=25 → 8/26 ~ 9/25"""
        start, end = billing_cycle("2026-09", cycle_end_day=25)
        assert start == date(2026, 8, 26)
        assert end == date(2026, 9, 25)

    def test_cycle_end_day_1_natural_month(self):
        """cycle_end_day=1 → 上月 2 日到本月 1 日（自然月偏移）"""
        start, end = billing_cycle("2026-09", cycle_end_day=1)
        assert start == date(2026, 8, 2)
        assert end == date(2026, 9, 1)

    def test_cycle_end_day_31_in_february_non_leap(self):
        """cycle_end_day=31 在 2 月（非闰年 2026）→ 实际取 2/28"""
        start, end = billing_cycle("2026-02", cycle_end_day=31)
        # end_actual = min(31, 28) = 28，end=2/28
        # start = 2/28 + 1 day - 1 month = 3/1 - 1 month = 2/1
        assert end == date(2026, 2, 28)
        assert start == date(2026, 2, 1)

    def test_cycle_end_day_31_in_february_leap_year(self):
        """cycle_end_day=31 在 2 月（闰年 2024）→ 实际取 2/29"""
        start, end = billing_cycle("2024-02", cycle_end_day=31)
        # start = 2/29 + 1 day - 1 month = 3/1 - 1 month = 2/1
        assert end == date(2024, 2, 29)
        assert start == date(2024, 2, 1)

    def test_start_override_for_short_cycle(self):
        """简化方案：start_override 覆盖公式起点，用于下个周期短周期场景

        例：当前周期 9/25 结束，下个周期截止日设为 20
        新周期 2026-10 应为 9/26~10/20（26 天短周期，而非公式算的 9/21~10/20）
        """
        start, end = billing_cycle("2026-10", cycle_end_day=20, start_override=date(2026, 9, 26))
        assert start == date(2026, 9, 26)  # 显式起点覆盖公式
        assert end == date(2026, 10, 20)   # end 仍按 cycle_end_day 算

    def test_no_start_override_uses_formula(self):
        """无 start_override 时用公式（end+1day-1月）"""
        start, end = billing_cycle("2026-10", cycle_end_day=21)
        assert start == date(2026, 9, 22)
        assert end == date(2026, 10, 21)


class TestComputeNextCycleRange:
    def test_short_cycle_25_to_20(self):
        """当前周期 9/25 结束，下个截止日 20 → 9/26~10/20（26 天短周期）"""
        from app.services.cycle_engine import compute_next_cycle_range
        start, end = compute_next_cycle_range(date(2026, 9, 25), 20)
        assert start == date(2026, 9, 26)
        assert end == date(2026, 10, 20)

    def test_normal_cycle_25_to_25(self):
        """当前周期 9/25 结束，下个截止日 25 → 9/26~10/25（30 天正常周期）"""
        from app.services.cycle_engine import compute_next_cycle_range
        start, end = compute_next_cycle_range(date(2026, 9, 25), 25)
        assert start == date(2026, 9, 26)
        assert end == date(2026, 10, 25)

    def test_long_cycle_20_to_25(self):
        """当前周期 9/20 结束，下个截止日 25 → 9/21~10/25（35 天长周期）"""
        from app.services.cycle_engine import compute_next_cycle_range
        start, end = compute_next_cycle_range(date(2026, 9, 20), 25)
        assert start == date(2026, 9, 21)
        assert end == date(2026, 10, 25)


class TestCycleKeyOf:
    def test_default_20_boundary(self):
        """cycle_end_day=20 时 day=20 属当月，day=21 属下月"""
        assert cycle_key_of(date(2026, 9, 20)) == "2026-09"
        assert cycle_key_of(date(2026, 9, 21)) == "2026-10"

    def test_cycle_end_day_25_boundary(self):
        """cycle_end_day=25 时 day=25 属当月，day=26 属下月"""
        assert cycle_key_of(date(2026, 9, 25), cycle_end_day=25) == "2026-09"
        assert cycle_key_of(date(2026, 9, 26), cycle_end_day=25) == "2026-10"

    def test_cycle_end_day_31_in_february_short_month(self):
        """cycle_end_day=31 时 2 月（28 天）实际 end_day=28"""
        # 2/28 <= 28 → 属当月周期 2026-02
        assert cycle_key_of(date(2026, 2, 28), cycle_end_day=31) == "2026-02"
        # 2/27 <= 28 → 属当月周期
        assert cycle_key_of(date(2026, 2, 27), cycle_end_day=31) == "2026-02"
        # 3/1 <= 31 (3 月 end_actual) → 3 月属当月周期
        assert cycle_key_of(date(2026, 3, 1), cycle_end_day=31) == "2026-03"


class TestCurrentCycleKey:
    def test_default_20(self):
        """cycle_end_day=20 时 9/5 属 2026-09（8/21–9/20）"""
        assert current_cycle_key(date(2026, 9, 5)) == "2026-09"

    def test_cycle_end_day_25(self):
        """cycle_end_day=25 时 9/25 属 2026-09（8/26–9/25），9/26 属 2026-10"""
        assert current_cycle_key(date(2026, 9, 25), cycle_end_day=25) == "2026-09"
        assert current_cycle_key(date(2026, 9, 26), cycle_end_day=25) == "2026-10"


class TestJustEndedCycleKey:
    def test_default_20_on_20th(self):
        """cycle_end_day=20 时 9/20 执行 → 锁定 2026-09（8/21–9/20）"""
        assert just_ended_cycle_key(date(2026, 9, 20)) == "2026-09"

    def test_cycle_end_day_25_on_25th(self):
        """cycle_end_day=25 时 9/25 执行 → 锁定 2026-09（8/26–9/25）"""
        assert just_ended_cycle_key(date(2026, 9, 25), cycle_end_day=25) == "2026-09"
