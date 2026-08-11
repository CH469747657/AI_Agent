"""报销单周期引擎

自然月滚动制（21-20）核心算法：
- billing_cycle: cycle_key → (周期起, 周期末)
- current_cycle_key: 今天 → 当前未封账周期 cycle_key
- cycle_key_of: 费用发生日 → 所属周期 cycle_key

设计依据：周期以结算月（结束月）为标识，上月21日至本月20日。
"""

from datetime import date
from dateutil.relativedelta import relativedelta

# 时区：遵循中国习惯 UTC+8
TZ_OFFSET = 8


def billing_cycle(cycle_key: str) -> tuple[date, date]:
    """cycle_key(结束月YYYY-MM) → (周期起, 周期末)

    例: billing_cycle("2026-07") → (date(2026,6,21), date(2026,7,20))
    """
    y, m = map(int, cycle_key.split("-"))
    end = date(y, m, 20)
    start = date(y, m, 1) - relativedelta(months=1) + relativedelta(days=20)
    return (start, end)


def cycle_display(cycle_key: str) -> str:
    """cycle_key → 显示名，如「2026年6月21日–7月20日」"""
    start, end = billing_cycle(cycle_key)
    if start.year == end.year:
        return f"{start.year}年{start.month}月{start.day}日–{end.month}月{end.day}日"
    return f"{start.year}年{start.month}月{start.day}日–{end.year}年{end.month}月{end.day}日"


def cycle_key_of(d: date) -> str:
    """费用发生日 → 所属周期 cycle_key

    day >= 21 → 属下月周期（结束月）；day < 21 → 属当月周期（结束月）

    例:
      cycle_key_of(date(2026,6,18))  → "2026-06"（5/21–6/20）
      cycle_key_of(date(2026,7,25))  → "2026-08"（7/21–8/20）
      cycle_key_of(date(2025,12,25)) → "2026-01"（12/21–1/20，跨年）
    """
    if d.day >= 21:
        return (d + relativedelta(months=1)).strftime("%Y-%m")
    return d.strftime("%Y-%m")


def current_cycle_key(today: date | None = None) -> str:
    """今天 → 当前未封账周期 cycle_key

    周期每月20日结束；21日起属下一周期。

    例:
      current_cycle_key(date(2026,7,5))  → "2026-07"（6/21–7/20）
      current_cycle_key(date(2026,7,25)) → "2026-08"（7/21–8/20）
    """
    today = today or date.today()
    anchor = today.replace(day=1)
    if today.day >= 21:
        anchor = anchor + relativedelta(months=1)
    return anchor.strftime("%Y-%m")


def just_ended_cycle_key(on_21th: date | None = None) -> str:
    """封账任务用：每月21日执行时，刚结束的周期 cycle_key

    7月21日执行 → 锁定 cycle_key="2026-07"（6/21–7/20）
    """
    on_21th = on_21th or date.today()
    return on_21th.strftime("%Y-%m")
