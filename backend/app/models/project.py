"""项目数据模型"""

import enum
from datetime import datetime
from sqlalchemy import String, Text, Integer, Enum, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.base import TimestampMixin


class ProjectStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True, comment="项目名称")
    code: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="项目编号")
    member_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="关联人员ID列表")
    supplier_names: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="关联供应商名称列表")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(Enum(ProjectStatus), default=ProjectStatus.active)

    def __repr__(self):
        return f"<Project {self.name}>"
