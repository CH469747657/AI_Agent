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

    # 下个周期起生效的 cycle_end_day（管理员修改时写入，下个周期开始时切换到 cycle_end_day）
    # 设计原则：修改的永远是下个周期的截止日，当前周期不变。
    # 切换时机：每月 (cycle_end_day + 1) 0:00 封账后，由 _cycle_lock_job 检查并应用。
    pending_cycle_end_day: Mapped[int | None] = mapped_column(
        Integer, default=None, nullable=True,
        comment="下个周期起生效的 cycle_end_day（管理员修改时写入，下个周期开始时切换）"
    )

    # 过渡周期起点（仅用于 pending 切换后的下个周期）
    # 设计原则：方案A 消除周期切换时的日期重叠/真空期。
    # 切换 cycle_end_day 后的下个周期用此日期作为起点，而非公式（end+1day-1月）。
    # 例：cycle_end_day 25→21，9/26 0:00 封账后切换 → transition_start=9/26，新周期 9/26~10/21（26 天短周期）。
    # 该周期封账后清空 transition_start，后续周期恢复正常公式计算。
    cycle_transition_start: Mapped[None] = mapped_column(
        Date, default=None, nullable=True,
        comment="过渡周期起点（仅 pending 切换后的下个周期用）。"
                "例：pending 25→21，9/26 封账后切换，transition_start=9/26，新周期 9/26~10/21。"
                "该周期封账后清空 transition_start，后续周期恢复正常公式"
    )
