"""节假日维护模型

用于补贴计算中的工作日/休息日/法定节假日判定。
每年依据国务院放假安排导入；调休补班日标记为 workday。
"""

from datetime import date
from sqlalchemy import String, Integer, SmallInteger, Enum, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.models.base import TimestampMixin


class Holiday(Base, TimestampMixin):
    """节假日/调休日维护表"""

    __tablename__ = "holidays"
    __table_args__ = (
        UniqueConstraint("holiday_date", name="uq_holiday_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, comment="日期")
    holiday_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="元旦/春节/国庆…")
    day_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="holiday=放假, workday=调休补班")
    year: Mapped[int] = mapped_column(SmallInteger, nullable=True, comment="年份")
    source: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="manual/cn_calendar_sync")
