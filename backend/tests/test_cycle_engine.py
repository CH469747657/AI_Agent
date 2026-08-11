"""周期引擎单元测试 — 自然月滚动制 21-20

覆盖：
- billing_cycle（cycle_key → 周期起末）
- cycle_key_of（费用发生日 → 所属周期）
- current_cycle_key（今天 → 当前未封账周期）
- 跨年、边界日期、刚好21日/20日
"""

import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.cycle_engine import (
    billing_cycle,
    cycle_key_of,
    current_cycle_key,
    just_ended_cycle_key,
    cycle_display,
)


class TestBillingCycle:
    def test_normal_month(self):
        """2026-07 周期 → 6月21日~7月20日"""
        start, end = billing_cycle("2026-07")
        assert start == date(2026, 6, 21)
        assert end == date(2026, 7, 20)

    def test_january_cycle_cross_year(self):
        """2026-01 周期跨年 → 2025年12月21日~2026年1月20日"""
        start, end = billing_cycle("2026-01")
        assert start == date(2025, 12, 21)
        assert end == date(2026, 1, 20)

    def test_december_cycle(self):
        """2026-12 周期 → 11月21日~12月20日"""
        start, end = billing_cycle("2026-12")
        assert start == date(2026, 11, 21)
        assert end == date(2026, 12, 20)

    def test_february_short_month(self):
        """2026-02 周期（2月20日结束）→ 1月21日~2月20日"""
        start, end = billing_cycle("2026-02")
        assert start == date(2026, 1, 21)
        assert end == date(2026, 2, 20)

    def test_display_name(self):
        assert cycle_display("2026-07") == "2026年6月21日–7月20日"
        assert cycle_display("2026-01") == "2025年12月21日–2026年1月20日"


class TestCycleKeyOf:
    def test_day_before_21_belongs_current_month(self):
        """6月18日 → 2026-06 周期（5/21-6/20）"""
        assert cycle_key_of(date(2026, 6, 18)) == "2026-06"

    def test_day_21_belongs_next_month(self):
        """6月21日 → 2026-07 周期（6/21-7/20）"""
        assert cycle_key_of(date(2026, 6, 21)) == "2026-07"

    def test_day_20_belongs_current_month(self):
        """7月20日 → 2026-07 周期（6/21-7/20）"""
        assert cycle_key_of(date(2026, 7, 20)) == "2026-07"

    def test_cross_year_december_25(self):
        """12月25日 → 2026-01 周期（12/21-1/20）跨年"""
        assert cycle_key_of(date(2025, 12, 25)) == "2026-01"

    def test_january_1_cross_year(self):
        """1月1日 → 2026-01 周期（12/21-1/20）"""
        assert cycle_key_of(date(2026, 1, 1)) == "2026-01"

    def test_january_20_end_of_cycle(self):
        """1月20日 → 2026-01 周期末"""
        assert cycle_key_of(date(2026, 1, 20)) == "2026-01"

    def test_january_21_start_next_cycle(self):
        """1月21日 → 2026-02 周期（1/21-2/20）"""
        assert cycle_key_of(date(2026, 1, 21)) == "2026-02"


class TestCurrentCycleKey:
    def test_mid_month(self):
        """7月5日 → 当前周期 2026-07"""
        assert current_cycle_key(date(2026, 7, 5)) == "2026-07"

    def test_end_of_cycle(self):
        """7月20日（周期末日）→ 仍属当前 2026-07"""
        assert current_cycle_key(date(2026, 7, 20)) == "2026-07"

    def test_start_of_new_cycle(self):
        """7月21日（新周期起始）→ 2026-08"""
        assert current_cycle_key(date(2026, 7, 21)) == "2026-08"

    def test_first_day_of_month(self):
        """8月1日 → 2026-08"""
        assert current_cycle_key(date(2026, 8, 1)) == "2026-08"


class TestJustEndedCycleKey:
    def test_21th_locks_same_month(self):
        """7月21日执行 → 锁定 cycle_key=2026-07"""
        assert just_ended_cycle_key(date(2026, 7, 21)) == "2026-07"
