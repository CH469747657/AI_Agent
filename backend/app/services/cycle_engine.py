"""报销单周期引擎

可配置 cycle_end_day（1-31），该日为本周期最后一天（含）。
cycle_end_day 不存在时（如 2/29、2/30、2/31）取该月最后一日。

设计依据：周期以结算月（结束月）为标识，上月 (cycle_end_day+1) 日到本月 cycle_end_day 日。
默认 cycle_end_day=20 → 21-20 制（21 号属下月，20 号是本月最后一天）。
"""

import calendar
from datetime import date
from dateutil.relativedelta import relativedelta

# 时区：遵循中国习惯 UTC+8
TZ_OFFSET = 8


def _actual_end_day(year: int, month: int, cycle_end_day: int) -> int:
    """该月实际 cycle_end_day（cycle_end_day 超过月末日时取月末日）

    例：cycle_end_day=31 在2月（非闰年）→ 28
        cycle_end_day=31 在1月 → 31
    """
    last_day = calendar.monthrange(year, month)[1]
    return min(cycle_end_day, last_day)


def billing_cycle(cycle_key: str, cycle_end_day: int = 20) -> tuple[date, date]:
    """cycle_key(结束月YYYY-MM) → (周期起, 周期末)

    cycle_end_day 是本周期最后一天（含）。
    例：
      billing_cycle("2026-09") → (date(2026,8,21), date(2026,9,20))  # 默认 21-20 制
      billing_cycle("2026-09", cycle_end_day=25) → (date(2026,8,26), date(2026,9,25))
      billing_cycle("2026-09", cycle_end_day=1) → (date(2026,8,2), date(2026,9,1))
    """
    y, m = map(int, cycle_key.split("-"))
    # 周期末 = 本月 cycle_end_day（如果该月没有这天，取月末）
    end_actual = _actual_end_day(y, m, cycle_end_day)
    end = date(y, m, end_actual)
    # 周期起 = end + 1 day - 1 month（用 relativedelta 安全处理跨月/2月）
    start = end + relativedelta(days=1) - relativedelta(months=1)
    return (start, end)


def cycle_display(cycle_key: str, cycle_end_day: int = 20) -> str:
    """cycle_key → 显示名，如「2026年8月21日–9月20日」"""
    start, end = billing_cycle(cycle_key, cycle_end_day)
    if start.year == end.year:
        return f"{start.year}年{start.month}月{start.day}日–{end.month}月{end.day}日"
    return f"{start.year}年{start.month}月{start.day}日–{end.year}年{end.month}月{end.day}日"


def cycle_key_of(d: date, cycle_end_day: int = 20) -> str:
    """费用发生日 → 所属周期 cycle_key（结束月YYYY-MM）

    规则：d.day > actual_end_day → 属下月周期；d.day <= actual_end_day → 属当月周期

    例：
      cycle_key_of(date(2026,9,20)) → "2026-09"（20 <= 20，属当月）
      cycle_key_of(date(2026,9,21)) → "2026-10"（21 > 20，属下月）
      cycle_key_of(date(2026,9,25), cycle_end_day=25) → "2026-09"（25 <= 25，属当月）
      cycle_key_of(date(2026,9,26), cycle_end_day=25) → "2026-10"（26 > 25，属下月）
      cycle_key_of(date(2025,12,25)) → "2026-01"（25 > 20，跨年属下月）
    """
    actual = _actual_end_day(d.year, d.month, cycle_end_day)
    if d.day > actual:
        return (d + relativedelta(months=1)).strftime("%Y-%m")
    return d.strftime("%Y-%m")


def current_cycle_key(today: date | None = None, cycle_end_day: int = 20) -> str:
    """今天 → 当前未封账周期 cycle_key

    例：
      current_cycle_key(date(2026,9,5)) → "2026-09"（8/21–9/20，cycle_end_day=20）
      current_cycle_key(date(2026,9,25), cycle_end_day=25) → "2026-09"
    """
    today = today or date.today()
    return cycle_key_of(today, cycle_end_day)


def just_ended_cycle_key(on_date: date | None = None, cycle_end_day: int = 20) -> str:
    """封账任务用：cycle_end_day 次日 00:00 执行，刚结束的周期 cycle_key

    cycle_end_day=20 时 9月21日 00:00 执行 → 锁定 cycle_key="2026-09"（8/21–9/20）
    cycle_end_day=25 时 9月26日 00:00 执行 → 锁定 cycle_key="2026-09"（8/26–9/25）

    实现说明：on_date 是触发日期（次日 0:00），刚结束的周期最后一天 = on_date - 1。
    用 cycle_key_of(on_date - 1) 算周期 cycle_key，正确处理跨月。
    """
    on_date = on_date or date.today()
    from datetime import timedelta
    yesterday = on_date - timedelta(days=1)
    return cycle_key_of(yesterday, cycle_end_day=cycle_end_day)
