"""cycle_engine cutoff 参数测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from app.services.cycle_engine import (
    billing_cycle, cycle_key_of, current_cycle_key, just_ended_cycle_key,
)


class TestBillingCycle:
    def test_default_21_keeps_current_behavior(self):
        """cutoff=21 时跟现状一致（21-20制）"""
        start, end = billing_cycle("2026-07")
        assert start == date(2026, 6, 21)
        assert end == date(2026, 7, 20)

    def test_cutoff_1_natural_month(self):
        """cutoff=1 = 自然月（1日到月末）"""
        start, end = billing_cycle("2026-07", cutoff_day=1)
        assert start == date(2026, 6, 1)
        assert end == date(2026, 6, 30)

    def test_cutoff_31_in_february_non_leap(self):
        """cutoff=31 在2月（非闰年2026）→ start=1/31，end=2/28（2月无30日，取月末）"""
        start, end = billing_cycle("2026-02", cutoff_day=31)
        assert start == date(2026, 1, 31)
        assert end == date(2026, 2, 28)

    def test_cutoff_31_in_february_leap_year(self):
        """cutoff=31 在2月（闰年2024）"""
        # 2024 是闰年，2月有29天
        start, end = billing_cycle("2024-02", cutoff_day=31)
        # 上月 cutoff（1/31）到本月 (cutoff-1=30)，2月没30日取月末2/29
        assert start == date(2024, 1, 31)
        assert end == date(2024, 2, 29)


class TestCycleKeyOf:
    def test_default_21_boundary(self):
        """cutoff=21 时 day=20 属当月，day=21 属下月"""
        assert cycle_key_of(date(2026, 6, 20)) == "2026-06"
        assert cycle_key_of(date(2026, 6, 21)) == "2026-07"

    def test_cutoff_1_natural_month_boundary(self):
        """cutoff=1 时 actual_cutoff=1，day>=1 即属下月周期（settlement month 约定）

        cycle "2026-07" 覆盖 6/1–6/30（7/1 cutoff 日封账），所以 6 月任意日 → "2026-07"
        cycle "2026-06" 覆盖 5/1–5/31（6/1 cutoff 日封账），所以 5/31 → "2026-06"
        """
        assert cycle_key_of(date(2026, 6, 1), cutoff_day=1) == "2026-07"
        assert cycle_key_of(date(2026, 6, 30), cutoff_day=1) == "2026-07"
        assert cycle_key_of(date(2026, 5, 31), cutoff_day=1) == "2026-06"

    def test_cutoff_15_boundary(self):
        """cutoff=15 时 5/14 属上月周期（4/15-5/14），5/15 属当月周期（5/15-6/14）"""
        assert cycle_key_of(date(2026, 5, 14), cutoff_day=15) == "2026-05"
        assert cycle_key_of(date(2026, 5, 15), cutoff_day=15) == "2026-06"

    def test_cutoff_31_in_february_short_month(self):
        """cutoff=31 时 2月（28天）的 cutoff 实际是2/28，2/28属下月周期"""
        # 2月实际 cutoff = min(31, 28) = 28
        # 2/27 < 28 → 属当月周期 2026-02
        # 2/28 >= 28 → 属下月周期 2026-03
        assert cycle_key_of(date(2026, 2, 27), cutoff_day=31) == "2026-02"
        assert cycle_key_of(date(2026, 2, 28), cutoff_day=31) == "2026-03"


class TestCurrentCycleKey:
    def test_default_21(self):
        """cutoff=21 时 7/5 属 2026-07（6/21-7/20）"""
        assert current_cycle_key(date(2026, 7, 5)) == "2026-07"

    def test_cutoff_15(self):
        """cutoff=15 时 5/14 属 2026-05（4/15-5/14），5/15 属 2026-06（5/15-6/14）"""
        assert current_cycle_key(date(2026, 5, 14), cutoff_day=15) == "2026-05"
        assert current_cycle_key(date(2026, 5, 15), cutoff_day=15) == "2026-06"


class TestJustEndedCycleKey:
    def test_default_21_on_21st(self):
        """cutoff=21 时 7/21 执行 → 锁定 2026-07（刚结束的6/21-7/20周期）"""
        assert just_ended_cycle_key(date(2026, 7, 21)) == "2026-07"

    def test_cutoff_15_on_15th(self):
        """cutoff=15 时 7/15 执行 → 锁定 2026-07（刚结束的6/15-7/14周期）"""
        assert just_ended_cycle_key(date(2026, 7, 15), cutoff_day=15) == "2026-07"
