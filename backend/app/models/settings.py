"""系统设置模型 — 单行配置表（id=1）"""

from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampMixin
from app.database import Base


class SystemSettings(TimestampMixin, Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # LLM 配置
    llm_provider: Mapped[str] = mapped_column(String(32), default="qwen")
    llm_api_key: Mapped[str] = mapped_column(String(256), default="")
    llm_model: Mapped[str] = mapped_column(String(128), default="qwen3-vl-plus")
    llm_text_model: Mapped[str] = mapped_column(String(128), default="")
    llm_base_url: Mapped[str] = mapped_column(String(512), default="")
