"""系统设置 API — LLM 配置的读取、保存和连通性测试"""

import logging
import time

from fastapi import APIRouter, Depends
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, LLM_PROVIDERS
from app.database import get_db
from app.models.settings import SystemSettings

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 请求/响应模型 ──────────────────────────────────────────

class LlmSettingsRead(BaseModel):
    llm_provider: str
    llm_api_key: str  # 前端拿到的是掩码后的 key
    llm_model: str
    llm_text_model: str
    llm_base_url: str


class LlmSettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_text_model: str | None = None
    llm_base_url: str | None = None


class LlmTestResult(BaseModel):
    success: bool
    message: str
    latency_ms: float | None = None


class ProviderInfo(BaseModel):
    """服务商信息（含可用模型列表）"""
    base_url: str
    models: list[str]
    vision_prefixes: list[str]


# ── 工具函数 ────────────────────────────────────────────────

def _mask_api_key(key: str) -> str:
    """对 API Key 进行掩码处理：sk-xxx...xxx"""
    if not key or len(key) < 8:
        return key or ""
    return f"{key[:4]}...{key[-4:]}"


def _apply_settings_to_config(row: SystemSettings) -> None:
    """将数据库配置覆写到运行时 settings 单例"""
    changed = False

    if row.llm_provider and row.llm_provider != settings.llm_provider:
        settings.llm_provider = row.llm_provider
        changed = True
    if row.llm_api_key and row.llm_api_key != settings.llm_api_key:
        settings.llm_api_key = row.llm_api_key
        changed = True
    if row.llm_model and row.llm_model != settings.llm_model:
        settings.llm_model = row.llm_model
        changed = True
    if row.llm_text_model != settings.llm_text_model:
        settings.llm_text_model = row.llm_text_model
        changed = True
    if row.llm_base_url != settings.llm_base_url:
        settings.llm_base_url = row.llm_base_url
        changed = True

    if changed:
        logger.info("Runtime config updated from DB: provider=%s model=%s", row.llm_provider, row.llm_model)
        # 重置 LLM NLU 客户端，下次请求时用新配置重建
        try:
            from app.dialog.llm_nlu import get_llm_nlu
            get_llm_nlu().reset_client()
        except Exception as e:
            logger.warning("Failed to reset LLM NLU client: %s", e)


async def load_settings_from_db(db: AsyncSession) -> None:
    """启动时从数据库加载配置覆写到运行时 settings"""
    row = (await db.execute(select(SystemSettings).where(SystemSettings.id == 1))).scalar_one_or_none()
    if row:
        _apply_settings_to_config(row)
        logger.info("Loaded LLM settings from DB on startup")
    else:
        logger.info("No system_settings row in DB, using .env defaults")


# ── API 端点 ────────────────────────────────────────────────

@router.get("/llm", response_model=LlmSettingsRead)
async def get_llm_settings(db: AsyncSession = Depends(get_db)):
    """读取当前 LLM 配置（API Key 返回掩码版）"""
    row = (await db.execute(select(SystemSettings).where(SystemSettings.id == 1))).scalar_one_or_none()

    if row:
        return LlmSettingsRead(
            llm_provider=row.llm_provider,
            llm_api_key=_mask_api_key(row.llm_api_key),
            llm_model=row.llm_model,
            llm_text_model=row.llm_text_model,
            llm_base_url=row.llm_base_url,
        )
    else:
        # 数据库无记录 → 返回 .env 默认值
        return LlmSettingsRead(
            llm_provider=settings.llm_provider,
            llm_api_key=_mask_api_key(settings.llm_api_key),
            llm_model=settings.llm_model,
            llm_text_model=settings.llm_text_model,
            llm_base_url=settings.llm_base_url,
        )


@router.put("/llm", response_model=LlmSettingsRead)
async def update_llm_settings(
    data: LlmSettingsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """保存 LLM 配置到数据库，并热更新到运行时"""
    row = (await db.execute(select(SystemSettings).where(SystemSettings.id == 1))).scalar_one_or_none()

    if row is None:
        # 首次保存，创建行
        row = SystemSettings(
            id=1,
            llm_provider=data.llm_provider or settings.llm_provider,
            llm_api_key=data.llm_api_key or settings.llm_api_key,
            llm_model=data.llm_model or settings.llm_model,
            llm_text_model=data.llm_text_model if data.llm_text_model is not None else settings.llm_text_model,
            llm_base_url=data.llm_base_url if data.llm_base_url is not None else settings.llm_base_url,
        )
        db.add(row)
    else:
        # 只更新非 None 字段
        if data.llm_provider is not None:
            row.llm_provider = data.llm_provider
        if data.llm_api_key is not None:
            row.llm_api_key = data.llm_api_key
        if data.llm_model is not None:
            row.llm_model = data.llm_model
        if data.llm_text_model is not None:
            row.llm_text_model = data.llm_text_model
        if data.llm_base_url is not None:
            row.llm_base_url = data.llm_base_url

    await db.commit()
    await db.refresh(row)

    # 热更新运行时配置
    _apply_settings_to_config(row)

    return LlmSettingsRead(
        llm_provider=row.llm_provider,
        llm_api_key=_mask_api_key(row.llm_api_key),
        llm_model=row.llm_model,
        llm_text_model=row.llm_text_model,
        llm_base_url=row.llm_base_url,
    )


@router.post("/llm/test", response_model=LlmTestResult)
async def test_llm_connection(data: LlmSettingsUpdate | None = None):
    """测试 LLM API 连通性

    如果传入 data，则用传入参数测试（用于保存前验证）；
    否则用当前运行时配置测试。
    """
    provider = (data.llm_provider if data and data.llm_provider else None) or settings.llm_provider
    api_key = (data.llm_api_key if data and data.llm_api_key else None) or settings.llm_api_key
    model = (data.llm_text_model if data and data.llm_text_model else None) or settings.text_model
    base_url = (data.llm_base_url if data and data.llm_base_url else None) or settings.llm_base_url

    if not base_url:
        provider_info = LLM_PROVIDERS.get(provider.lower(), {})
        base_url = provider_info.get("base_url", "")

    if not api_key:
        return LlmTestResult(success=False, message="API Key 未配置")
    if not base_url:
        return LlmTestResult(success=False, message=f"服务商 {provider} 的 Base URL 未找到")

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        start = time.monotonic()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
            timeout=10,
        )
        latency = round((time.monotonic() - start) * 1000)
        content = resp.choices[0].message.content if resp.choices else ""
        return LlmTestResult(
            success=True,
            message=f"连接成功：模型响应正常 ({latency}ms, 回复: {content[:20]})",
            latency_ms=latency,
        )
    except Exception as e:
        error_msg = str(e)[:200]
        return LlmTestResult(success=False, message=f"连接失败：{error_msg}")


@router.get("/llm/providers")
async def get_llm_providers():
    """返回所有支持的 LLM 服务商及其模型列表"""
    return {
        key: ProviderInfo(
            base_url=info["base_url"],
            models=info["models"],
            vision_prefixes=info["vision_prefixes"],
        )
        for key, info in LLM_PROVIDERS.items()
    }
