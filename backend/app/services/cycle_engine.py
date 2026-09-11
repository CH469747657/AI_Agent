"""报销单周期引擎

可配置 cutoff 日（1-31），替代硬编码的 21-20 制。
cutoff 日不存在时（如 2/29、2/30、2/31）取该月最后一日。

设计依据：周期以结算月（结束月）为标识，上月 cutoff 日到本月 (cutoff-1) 日。
"""

import calendar
from datetime import date
from dateutil.relativedelta import relativedelta

# 时区：遵循中国习惯 UTC+8
TZ_OFFSET = 8


def _actual_cutoff(year: int, month: int, cutoff_day: int) -> int:
    """该月实际 cutoff 日（cutoff_day 超过月末日时取月末日）

    例：cutoff_day=31 在2月（非闰年）→ 28
        cutoff_day=31 在1月 → 31
    """
    last_day = calendar.monthrange(year, month)[1]
    return min(cutoff_day, last_day)


def billing_cycle(cycle_key: str, cutoff_day: int = 21) -> tuple[date, date]:
    """cycle_key(结束月YYYY-MM) → (周期起, 周期末)

    例: billing_cycle("2026-07") → (date(2026,6,21), date(2026,7,20))
    例: billing_cycle("2026-07", cutoff_day=1) → (date(2026,6,1), date(2026,6,30))
    """
    y, m = map(int, cycle_key.split("-"))
    # 本月 (cutoff-1) 日；如果 cutoff=1，cutoff-1=0 → 上月最后一天
    if cutoff_day == 1:
        end = date(y, m, 1) - relativedelta(days=1)
    else:
        # 本月 (cutoff-1) 日，但 cutoff-1 可能超过月末日（如 cutoff=31，cutoff-1=30，2月无30日）
        last_day = calendar.monthrange(y, m)[1]
        end = date(y, m, min(cutoff_day - 1, last_day))
    # 上月 cutoff 日（cutoff 超过月末日时取月末日）
    prev_y, prev_m = (y, m - 1) if m > 1 else (y - 1, 12)
    start_actual = _actual_cutoff(prev_y, prev_m, cutoff_day)
    start = date(prev_y, prev_m, start_actual)
    return (start, end)


def cycle_display(cycle_key: str, cutoff_day: int = 21) -> str:
    """cycle_key → 显示名，如「2026年6月21日–7月20日」"""
    start, end = billing_cycle(cycle_key, cutoff_day)
    if start.year == end.year:
        return f"{start.year}年{start.month}月{start.day}日–{end.month}月{end.day}日"
    return f"{start.year}年{start.month}月{start.day}日–{end.year}年{end.month}月{end.day}日"


def cycle_key_of(d: date, cutoff_day: int = 21) -> str:
    """费用发生日 → 所属周期 cycle_key

    day >= actual_cutoff → 属下月周期（结束月）；day < actual_cutoff → 属当月周期

    例:
      cycle_key_of(date(2026,6,18))  → "2026-06"（5/21–6/20）
      cycle_key_of(date(2026,7,25))  → "2026-08"（7/21–8/20）
      cycle_key_of(date(2025,12,25)) → "2026-01"（12/21–1/20，跨年）
      cycle_key_of(date(2026,5,14), cutoff_day=15) → "2026-05"（4/15–5/14）
      cycle_key_of(date(2026,5,15), cutoff_day=15) → "2026-06"（5/15–6/14）
    """
    actual = _actual_cutoff(d.year, d.month, cutoff_day)
    if d.day >= actual:
        return (d + relativedelta(months=1)).strftime("%Y-%m")
    return d.strftime("%Y-%m")


def current_cycle_key(today: date | None = None, cutoff_day: int = 21) -> str:
    """今天 → 当前未封账周期 cycle_key

    周期每月 (cutoff-1) 日结束；cutoff 日（含）起属下一周期。

    例:
      current_cycle_key(date(2026,7,5))  → "2026-07"（6/21–7/20，cutoff=21）
      current_cycle_key(date(2026,7,25)) → "2026-08"（7/21–8/20，cutoff=21）
      current_cycle_key(date(2026,5,14), cutoff_day=15) → "2026-05"
      current_cycle_key(date(2026,5,15), cutoff_day=15) → "2026-06"
    """
    today = today or date.today()
    return cycle_key_of(today, cutoff_day)


def just_ended_cycle_key(on_date: date | None = None, cutoff_day: int = 21) -> str:
    """封账任务用：cutoff 日执行时，刚结束的周期 cycle_key

    cutoff=21 时 7月21日执行 → 锁定 cycle_key="2026-07"（6/21–7/20）
    cutoff=15 时 7月15日执行 → 锁定 cycle_key="2026-07"（6/15–7/14）
    """
    on_date = on_date or date.today()
    # cutoff 日执行，刚结束的周期 = 本月 cycle_key
    return on_date.strftime("%Y-%m")
