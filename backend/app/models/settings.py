"""系统设置模型 — 单行配置表（id=1）"""

from sqlalchemy import String, Integer, Date, Boolean
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

    # 是否开启发票验真功能（True=开启，发票必须验真通过才能归集；False=关闭，忽略验真状态）
    # 场景：验真账户欠费时关闭，发票可正常上传归集，由管理员人工审核
    verify_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True,
        comment="是否开启发票验真（True=开启，发票必须验真通过才能归集；False=关闭，忽略验真状态）"
    )

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

    # 下个周期截止日（1-31）。管理员可设，下个周期开始时（封账任务触发后）切换为 cycle_end_day。
    # 设计原则：一次只设一个下个周期。下个周期起点 = 上个周期截止的次日（自动算）。
    # 例：当前 cycle_end_day=25（8/26~9/25），设 next_cycle_end_day=20 → 下个周期 9/26~10/20（26 天短周期）。
    # 封账后 cycle_end_day=20，next_cycle_end_day=None，后续周期按公式算。
    next_cycle_end_day: Mapped[int | None] = mapped_column(
        Integer, default=None, nullable=True,
        comment="下个周期截止日（仅下个周期用，封账后切换到 cycle_end_day 并清空）"
    )
