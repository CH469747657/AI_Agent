"""员工数据模型

独立员工表，支持企微通讯录同步和手动管理。
与 reimbursements.applicant_id 通过 wecom_user_id 关联。
"""

import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Enum, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.models.base import TimestampMixin


class EmployeeStatus(int, enum.Enum):
    active = 1   # 在职
    resigned = 2  # 离职


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wecom_user_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, comment="企微UserID"
    )
    name: Mapped[str] = mapped_column(String(100), comment="员工姓名")
    employee_no: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True, comment="工号"
    )
    department: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="部门名称"
    )
    department_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="企微部门ID"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="职务"
    )
    mobile: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="手机号"
    )
    email: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="邮箱"
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="密码哈希(bcrypt)"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后登录时间"
    )
    status: Mapped[EmployeeStatus] = mapped_column(
        Enum(EmployeeStatus), default=EmployeeStatus.active, comment="状态: 1=在职 2=离职"
    )

    @property
    def has_password(self) -> bool:
        """是否已设置登录密码"""
        return bool(self.password_hash)
