"""应用配置管理"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库 — 支持 DATABASE_URL 直接指定，或通过 DB_PASSWORD 组装
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"postgresql+asyncpg://reimburse:{os.getenv('DB_PASSWORD', 'reimburse123')}@localhost:15432/reimbursement"
    )

    # Redis
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # LLM 配置（运行时可通过数据库热更新，需允许 mutable）
    llm_provider: str = os.getenv("LLM_PROVIDER", "qwen")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "qwen3-vl-plus")
    llm_text_model: str = os.getenv("LLM_TEXT_MODEL", "")  # 文本模型（分类/项目提取），留空则自动推导
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")

    # OCR 配置
    ocr_max_workers: int = int(os.getenv("OCR_MAX_WORKERS", "2"))
    llm_max_workers: int = int(os.getenv("LLM_MAX_WORKERS", "4"))

    # 文件存储
    upload_dir: str = os.getenv("UPLOAD_DIR", "/app/uploads")
    report_dir: str = os.getenv("REPORT_DIR", "/app/reports")

    # 报销单公司名称（用于 Excel/PDF 报表抬头）
    company_name: str = os.getenv("COMPANY_NAME", "常州华一防静电活动地板有限公司")

    # 阿里云 OCR（保留兼容）
    aliyun_ocr_key: str = os.getenv("ALIYUN_OCR_KEY", "")

    # 在线发票验真配置
    verify_provider: str = os.getenv("VERIFY_PROVIDER", "aliyun")
    verify_api_key: str = os.getenv("VERIFY_API_KEY", "")       # 百度 AI 的 API Key (AK)
    verify_secret_key: str = os.getenv("VERIFY_SECRET_KEY", "")  # 百度 AI 的 Secret Key (SK)
    aliyun_verify_appcode: str = os.getenv("ALIYUN_VERIFY_APPCODE", "")    # 阿里云云市场 AppCode
    aliyun_verify_appsecret: str = os.getenv("ALIYUN_VERIFY_APPSECRET", "")  # 阿里云云市场 AppSecret

    # JWT 配置
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_expire_hours: int = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

    # 管理端账号 — 单一管理员账户，账户名/密码哈希从 .env 读取
    # 与员工端 employees 表完全分离，避免越权混淆
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")

    # CORS 配置 — 多个域名用逗号分隔
    cors_allow_origins: str = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173")

    @property
    def cors_origins(self) -> list[str]:
        """解析 CORS 允许的域名列表"""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def is_jwt_configured(self) -> bool:
        """JWT_SECRET 是否已正确配置（非空且非弱值）"""
        return bool(self.jwt_secret) and self.jwt_secret not in ("change-me", "")

    @property
    def text_model(self) -> str:
        """获取文本模型名称（用于分类、项目提取等非视觉任务）

        优先使用 LLM_TEXT_MODEL 环境变量；
        否则从视觉模型名自动推导：qwen3-vl-plus → qwen-plus，qwen-vl-max → qwen-max
        """
        if self.llm_text_model:
            return self.llm_text_model
        # 自动推导：移除 -vl 或 3-vl 等视觉标记
        model = self.llm_model
        for pattern in ["3-vl", "-vl"]:
            if pattern in model:
                return model.replace(pattern, "")
        return model

    def get_model_for_task(self, task_type: str) -> str:
        """根据任务类型获取对应模型名（分层模型路由）

        优先级：
        1. 环境变量 LLM_<SHORT>_MODEL（如 LLM_NLU_MODEL）— 最高优先级，便于灰度切换
        2. MODEL_ROUTING[task_type] — 默认路由表
        3. 兜底：invoice_ocr 用 llm_model（Vision），其他用 text_model
        """
        env_var = _TASK_ENV_MAP.get(task_type)
        if env_var:
            env_val = os.getenv(env_var, "").strip()
            if env_val:
                return env_val
        routing = MODEL_ROUTING.get(task_type)
        if routing:
            return routing
        return self.llm_model if task_type == "invoice_ocr" else self.text_model

    class Config:
        env_file = Path(__file__).resolve().parent.parent.parent / ".env"
        env_file_encoding = "utf-8"
        # 允许运行时通过数据库配置覆写 LLM 字段
        validate_assignment = True


settings = Settings()

# 任务类型 → 默认模型映射（可被环境变量 LLM_<SHORT>_MODEL 覆盖）
# 适配自建网关 https://aigw.telecomjs.com/v1 的可用模型列表
# - qwen3-max：文本模型，适合 NLU/分类/叙述
# - vlt_mm_31_vis：视觉模型，适合 OCR
MODEL_ROUTING: dict[str, str] = {
    "nlu_classify":    "qwen3-max",
    "fee_classify":    "qwen3-max",
    "project_extract": "qwen3-max",
    "invoice_ocr":     "vlt_mm_31_vis",
    "insight_narrate": "qwen3-max",
    "batch_describe":  "qwen3-max",
}

# 任务类型 → 环境变量名映射（用于灰度覆盖 MODEL_ROUTING）
# 命名约定：LLM_<语义短名>_MODEL，避免 task_type 直接 upper() 产生歧义（如 nlu_classify → LLM_NLU_CLASSIFY_MODEL）
_TASK_ENV_MAP: dict[str, str] = {
    "nlu_classify":    "LLM_NLU_MODEL",
    "fee_classify":    "LLM_FEE_CLASSIFY_MODEL",
    "project_extract": "LLM_PROJECT_EXTRACT_MODEL",
    "invoice_ocr":     "LLM_OCR_MODEL",
    "insight_narrate": "LLM_NARRATE_MODEL",
    "batch_describe":  "LLM_BATCH_MODEL",
}

# LLM Provider 配置映射
LLM_PROVIDERS = {
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3-vl-plus", "qwen-vl-plus", "qwen-vl-max", "qwen-plus", "qwen-turbo"],
        "vision_prefixes": ["qwen-vl", "qwen3-vl"],
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "vision_prefixes": [],
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "vision_prefixes": ["gpt-4o", "gpt-4-turbo", "gpt-4-vision", "vlt_mm", "orb_base"],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-3-5-sonnet", "claude-3-opus"],
        "vision_prefixes": ["claude-3"],
    },
}
