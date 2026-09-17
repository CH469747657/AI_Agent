"""pytest 公共 fixture

集中 mock LLM/VLM 外部依赖，避免单元测试触发真实网关调用。
"""

import asyncio
import base64
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 让 tests 能 import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# Settings 容忍额外环境变量
# pydantic-settings 2.6 默认禁止 extra，但 .env 含 Settings 类未声明的字段
# （WECOM_*、AGENT_*、DB_PASSWORD 等）。在 app.config 被 import 之前
# 修改 BaseSettings 的默认 model_config，让所有子类容忍 extra。
# ============================================================
def _patch_settings_extra_ignore():
    import pydantic_settings
    # BaseSettings 的 model_config 是一个 ConfigDict 实例，直接修改 extra 字段
    pydantic_settings.BaseSettings.model_config.setdefault("extra", "ignore")
    pydantic_settings.BaseSettings.model_config["extra"] = "ignore"


_patch_settings_extra_ignore()


# ============================================================
# Mock LLM Service
# ============================================================

@pytest.fixture
def mock_llm_service():
    """返回一个 mock 的 LlmService 实例，client.chat.completions.create 是 AsyncMock

    mock 同时支持流式（stream=True，返回 async iterator）和非流式（返回 response.choices[0]）
    两种调用方式，适配 _stream_chat_completion 和直接 create 调用。

    用法：
        def test_x(mock_llm_service):
            _set_stream_content(mock_llm_service, '{"key":"value"}')
    """
    svc = MagicMock()
    svc.is_available.return_value = True
    svc._supports_vision.return_value = True

    svc.client = MagicMock()
    svc.client.chat = MagicMock()
    svc.client.chat.completions = MagicMock()
    # 默认非流式返回空 response；流式返回空 chunks
    _set_llm_response(svc, "{}")

    with patch("app.services.llm_service.get_llm_service", return_value=svc):
        yield svc


def _make_stream_side_effect(content: str, finish_reason: str = "stop"):
    """构造流式 side_effect：被 await 后返回 async iterator of chunks。

    _stream_chat_completion 先 await create(...) 再 async for，所以 create
    必须返回 awaitable，await 后得到 async iterator。
    """
    async def _stream_factory(*args, **kwargs):
        chunk_size = 10
        chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)] or [""]
        async def _aiter():
            for i, c in enumerate(chunks):
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                chunk.choices[0].delta = MagicMock(content=c)
                chunk.choices[0].finish_reason = finish_reason if i == len(chunks) - 1 else None
                yield chunk
        return _aiter()
    return _stream_factory


def _make_non_stream_side_effect(content: str, finish_reason: str = "stop"):
    """构造非流式 side_effect：被 await 后返回含 choices[0].message.content 的 response。"""
    async def _non_stream_factory(*args, **kwargs):
        if kwargs.get("stream"):
            # 流式调用走流式分支
            stream_fn = _make_stream_side_effect(content, finish_reason)
            return await stream_fn(*args, **kwargs)
        choice = MagicMock()
        choice.message.content = content
        choice.finish_reason = finish_reason
        response = MagicMock()
        response.choices = [choice]
        return response
    return _non_stream_factory


def _set_llm_response(mock_svc: MagicMock, content: str, finish_reason: str = "stop"):
    """配置 mock_llm_service 让 create 返回指定 content（同时支持流式和非流式调用）"""
    mock_svc.client.chat.completions.create = AsyncMock(
        side_effect=_make_non_stream_side_effect(content, finish_reason)
    )


def _set_stream_content(mock_svc: MagicMock, content: str, finish_reason: str = "stop"):
    """配置 mock_llm_service 让流式 create 返回指定 content（_set_llm_response 的别名）"""
    _set_llm_response(mock_svc, content, finish_reason)


@pytest.fixture
def mock_llm_with_payment_screenshot(mock_llm_service):
    """配置 mock_llm_service 让 VLM detect_extract 返回「支付截图」类型 + 字段"""
    import json
    fake_response = {
        "receipt_type": "支付截图",
        "seller_name": "测试销售方",
        "total_with_tax": 540.0,
        "issue_date": "2025-10-10",
        "_confidence": 0.9,
    }
    _set_stream_content(mock_llm_service, json.dumps(fake_response, ensure_ascii=False))
    return mock_llm_service


@pytest.fixture
def mock_llm_with_purpose_date_split(mock_llm_service):
    """配置 mock_llm_service 让 _llm_split_purpose_date 返回拆分结果"""
    import json
    fake_response = {
        "purpose": "项目投标费",
        "expense_date": "2026-08-02",
    }
    _set_stream_content(mock_llm_service, json.dumps(fake_response, ensure_ascii=False))
    return mock_llm_service


# ============================================================
# Mock Invoice 对象
# ============================================================

@pytest.fixture
def fake_invoice():
    """返回未持久化的 Invoice 对象（避免 DB）"""
    from app.models.invoice import Invoice, ReceiptType, InvoiceStatus
    return Invoice(
        id=999,
        receipt_type=ReceiptType.unknown,
        user_description="",
        user_id="TEST_USER",
        file_type="jpg",
        status=InvoiceStatus.processing,
    )


@pytest.fixture
def fake_attachment_data():
    """返回 1x1 像素 PNG 的 attachment_data dict"""
    # 1x1 透明 PNG
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    return {
        "base64": base64.b64encode(png_bytes).decode(),
        "file_type": "jpg",
    }


# ============================================================
# Mock DialogContext
# ============================================================

@pytest.fixture
def empty_dialog_context():
    """返回空的 DialogContext（slots 都未填）"""
    from app.dialog.models import DialogContext, UserRole
    return DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)


# ============================================================
# Mock DB Session
# ============================================================

@pytest.fixture
def mock_db():
    """返回 mock AsyncSession（commit/refresh/execute 都是 AsyncMock）"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    # execute 是 AsyncMock，但返回值需支持 .scalars().all() 链
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    scalars_mock.first.return_value = None
    scalars_mock.scalar_one_or_none.return_value = None
    scalars_mock.scalars.return_value = scalars_mock
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=execute_result)
    db.add = MagicMock()
    return db


# ============================================================
# Mock sessionmaker（用于后台任务独立 session）
# ============================================================

@pytest.fixture
def mock_sessionmaker(mock_db):
    """mock get_async_sessionmaker，返回的 sm() async context manager yield mock_db"""
    class FakeSM:
        def __call__(self):
            class FakeCtx:
                async def __aenter__(self_inner):
                    return mock_db
                async def __aexit__(self_inner, *args):
                    pass
            return FakeCtx()

    with patch("app.database.get_async_sessionmaker", return_value=FakeSM()):
        yield mock_db
