"""LLM Vision 解析服务（多 Provider 支持）

参考项目: stone16/Invoice-Manager llm_service.py
技术路线: OpenAI兼容API + 多Provider适配
"""

import base64
import json
import logging
import threading
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from app.config import settings, LLM_PROVIDERS
from app.prompts.invoice_prompts import INVOICE_VISION_SYSTEM_PROMPT, INVOICE_VISION_PROMPT

logger = logging.getLogger(__name__)

_llm_lock = threading.Lock()
_llm_instance: Optional["LLMService"] = None
_llm_executor: Optional[ThreadPoolExecutor] = None


class LLMService:
    """多 LLM 提供商的发票解析服务

    支持: Qwen-VL / GPT-4o / Claude / DeepSeek / 智谱GLM
    所有 Provider 统一走 OpenAI 兼容接口

    参考: Invoice-Manager llm_service.py BaseLLMProvider
    """

    def __init__(self):
        self._client = None
        self._lock = threading.Lock()

    @property
    def client(self):
        """懒加载 OpenAI 客户端"""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    from openai import AsyncOpenAI
                    provider_cfg = LLM_PROVIDERS.get(settings.llm_provider, {})
                    base_url = settings.llm_base_url or provider_cfg.get("base_url", "")
                    self._client = AsyncOpenAI(
                        api_key=settings.llm_api_key or "dummy",
                        base_url=base_url,
                    )
                    logger.info(f"LLM client initialized: provider={settings.llm_provider}, model={settings.llm_model}")
        return self._client

    def is_available(self) -> bool:
        return bool(settings.llm_api_key)

    def _supports_vision(self, model_name: str = None) -> bool:
        """检查当前模型是否支持 Vision"""
        model = model_name or settings.llm_model
        provider_cfg = LLM_PROVIDERS.get(settings.llm_provider, {})
        vision_prefixes = provider_cfg.get("vision_prefixes", [])
        for prefix in vision_prefixes:
            if model == prefix or model.startswith(prefix + "-") or model.startswith(prefix + "."):
                return True
        return False

    async def parse_invoice_from_image(self, file_data: bytes, mime_type: str = "image/png") -> dict:
        """用 Vision 模型直接解析发票图片

        参考: Invoice-Manager llm_service.py parse_invoice_from_image
        """
        if not self.is_available():
            logger.warning("LLM API key not configured, skipping LLM parsing")
            return {}

        if not self._supports_vision():
            logger.warning(f"Model {settings.llm_model} does not support vision, skipping")
            return {}

        # PDF 转图片
        if mime_type == "application/pdf":
            try:
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(file_data, dpi=300, first_page=1, last_page=1)
                if images:
                    buf = BytesIO()
                    images[0].save(buf, format="PNG")
                    file_data = buf.getvalue()
                    mime_type = "image/png"
            except Exception as e:
                logger.error(f"PDF to image conversion failed: {e}")
                return {}

        # OFD：纯 Python 解析优先，无矢量文字才回落图片 Vision
        elif mime_type == "application/ofd":
            from app.services.ofd_parser import get_ofd_parser
            parsed = get_ofd_parser().parse(file_data)
            fields = parsed.get("fields", {})
            # OFD 结构化字段精度 100%，直接返回，跳过 Vision（省钱、稳定、精准）
            if any(v for v in fields.values()):
                logger.info(
                    f"OFD 结构化解析成功，跳过 LLM Vision: "
                    f"invoice_number={fields.get('invoice_number')}"
                )
                # 返回 LLM schema 的 12 字段（去掉 check_code）
                return {k: v for k, v in fields.items() if k != "check_code"}
            # 无结构化字段 → 尝试内嵌图片走 Vision 兜底（扫描件式 OFD）
            img_bytes = parsed.get("image_bytes")
            if img_bytes:
                logger.info("OFD 无矢量文字，回落内嵌图片 LLM Vision")
                file_data = img_bytes
                mime_type = "image/png"
            else:
                logger.warning("OFD 无可识别内容")
                return {}

        b64_image = base64.b64encode(file_data).decode()

        try:
            response = await self.client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": INVOICE_VISION_SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": INVOICE_VISION_PROMPT},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime_type};base64,{b64_image}"
                        }}
                    ]}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,  # 低温度保证稳定输出
                max_tokens=2000,
            )

            content = response.choices[0].message.content
            result = json.loads(content)
            logger.info(f"LLM parsing completed: {len(result)} fields extracted")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"LLM returned invalid JSON: {e}")
            return {}
        except Exception as e:
            logger.error(f"LLM parsing failed: {e}")
            return {}

    async def classify_fee(self, receipt_type: str, seller_name: str, amount: str, user_desc: str) -> dict:
        """LLM 费用分类（文本模型即可）"""
        if not self.is_available():
            return {}

        from app.prompts.invoice_prompts import CLASSIFY_PROMPT
        prompt = CLASSIFY_PROMPT.format(
            receipt_type=receipt_type or "未知",
            seller_name=seller_name or "未知",
            amount=amount or "未知",
            user_description=user_desc or "无",
        )

        try:
            response = await self.client.chat.completions.create(
                model=settings.text_model,  # 分类用文本模型
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=200,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            return {}

    async def extract_project_name(self, description: str, project_names: list[str]) -> str | None:
        """从用户描述中提取项目名"""
        if not self.is_available() or not description:
            return None

        from app.prompts.invoice_prompts import PROJECT_EXTRACT_PROMPT
        prompt = PROJECT_EXTRACT_PROMPT.format(
            project_names=json.dumps(project_names, ensure_ascii=False),
            description=description,
        )

        try:
            response = await self.client.chat.completions.create(
                model=settings.text_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=100,
            )
            result = response.choices[0].message.content.strip()
            if result and result != "null":
                return result
            return None
        except Exception as e:
            logger.error(f"LLM project extraction failed: {e}")
            return None


from io import BytesIO  # noqa: E402


def get_llm_service() -> LLMService:
    global _llm_instance
    if _llm_instance is None:
        with _llm_lock:
            if _llm_instance is None:
                _llm_instance = LLMService()
    return _llm_instance


def get_llm_executor(max_workers: int = 4) -> ThreadPoolExecutor:
    """获取 LLM 专用线程池（I/O密集型）"""
    global _llm_executor
    if _llm_executor is None:
        _llm_executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="llm")
    return _llm_executor
