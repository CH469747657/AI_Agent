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

    # 发票验真 API 配置（与 LLM 共表，复用单行配置模式）
    verify_provider: Mapped[str] = mapped_column(String(32), default="aliyun")
    verify_api_key: Mapped[str] = mapped_column(String(256), default="")
    verify_secret_key: Mapped[str] = mapped_column(String(256), default="")
    aliyun_verify_appcode: Mapped[str] = mapped_column(String(256), default="")
    aliyun_verify_appsecret: Mapped[str] = mapped_column(String(256), default="")

    # 管理员密码哈希（改密后写入此字段；为空时回退到 .env 的 ADMIN_PASSWORD_HASH）
    admin_password_hash: Mapped[str] = mapped_column(String(256), default="")

    # 老板端密码哈希（改密后写入此字段；为空时回退到 .env 的 BOSS_PASSWORD_HASH）
    boss_password_hash: Mapped[str] = mapped_column(String(256), default="")

    # 周期截止日（1-31）。该日为本周期最后一天（含）。
    # 例：cycle_end_day=25 → 8/26~9/25；cycle_end_day=20 → 7/21~8/20（默认 21-20 制）。
    # cycle_end_day 不存在时取该月最后一日。
    cycle_end_day: Mapped[int] = mapped_column(
        Integer, default=20,
        comment="周期截止日（1-31）。该日为本周期最后一天（含）。"
                "例：cycle_end_day=25 → 8/26~9/25；cycle_end_day=20 → 7/21~8/20（默认 21-20 制）。"
                "cycle_end_day 不存在时取该月最后一日。"
    )
