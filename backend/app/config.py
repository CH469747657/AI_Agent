"""应用配置管理"""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://reimburse:reimburse123@localhost:15432/reimbursement")

    # Redis
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # LLM 配置
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

    # 阿里云 OCR（保留兼容）
    aliyun_ocr_key: str = os.getenv("ALIYUN_OCR_KEY", "")

    # 在线发票验真配置
    verify_provider: str = os.getenv("VERIFY_PROVIDER", "aliyun")
    verify_api_key: str = os.getenv("VERIFY_API_KEY", "")       # 百度 AI 的 API Key (AK)
    verify_secret_key: str = os.getenv("VERIFY_SECRET_KEY", "")  # 百度 AI 的 Secret Key (SK)
    aliyun_verify_appcode: str = os.getenv("ALIYUN_VERIFY_APPCODE", "")    # 阿里云云市场 AppCode
    aliyun_verify_appsecret: str = os.getenv("ALIYUN_VERIFY_APPSECRET", "")  # 阿里云云市场 AppSecret

    # CORS 配置 — 多个域名用逗号分隔
    cors_allow_origins: str = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173")

    @property
    def cors_origins(self) -> list[str]:
        """解析 CORS 允许的域名列表"""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

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

    class Config:
        env_file = ".env"


settings = Settings()

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
        "vision_prefixes": ["gpt-4o", "gpt-4-turbo", "gpt-4-vision"],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-3-5-sonnet", "claude-3-opus"],
        "vision_prefixes": ["claude-3"],
    },
}
