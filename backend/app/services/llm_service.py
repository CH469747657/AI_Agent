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
from app.prompts.invoice_prompts import INVOICE_VISION_SYSTEM_PROMPT, INVOICE_VISION_PROMPT, INVOICE_JSON_SCHEMA

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
        """检查当前模型是否支持 Vision

        匹配规则：
        - 精确匹配 prefix
        - 前缀 + 任意分隔符（- _ .）+ 后缀
        - 兜底：vision_prefixes 为空时，认为支持（自建网关默认多模态）
        """
        model = model_name or settings.llm_model
        provider_cfg = LLM_PROVIDERS.get(settings.llm_provider, {})
        vision_prefixes = provider_cfg.get("vision_prefixes", [])
        # 兜底：provider 没配 vision_prefixes → 默认所有模型支持 vision
        if not vision_prefixes:
            return True
        for prefix in vision_prefixes:
            if (
                model == prefix
                or model.startswith(prefix + "-")
                or model.startswith(prefix + "_")
                or model.startswith(prefix + ".")
            ):
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
                # Step 1.2.3：升级为完整 json_schema（替代 json_object），
                # 强制 LLM 返回符合 INVOICE_JSON_SCHEMA 的结构化输出
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "invoice_fields",
                        "schema": INVOICE_JSON_SCHEMA,
                        "strict": False,  # 允许额外字段，避免 LLM 偶尔加字段导致拒绝
                    },
                },
                temperature=0.1,  # 低温度保证稳定输出
                max_tokens=2000,
            )

            content = response.choices[0].message.content
            # Fallback：若 Provider 仍返回 markdown 包裹的 JSON，剥离代码块
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            # 用 Pydantic TypeAdapter 校验（替代脆弱的 json.loads）
            from pydantic import TypeAdapter
            adapter = TypeAdapter(dict)
            result = adapter.validate_json(content)
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
                model=settings.get_model_for_task("fee_classify"),  # 费用分类：短文本，路由到快模型
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=200,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            return {}

    async def resolve_person_llm(
        self,
        user_ref: str,
        candidates: list[dict],
    ) -> str | None:
        """LLM 人名消歧：从候选人列表中找出与用户称呼最匹配的 employee_no

        覆盖场景：
        - 昵称：小陈=陈辉、老王=王建国、张总=张伟
        - 简称：陈工=陈工程师、Kevin=外籍员工
        - 模糊输入：陈=所有姓陈的人（多候选时由调用方 disambiguate）

        Args:
            user_ref: 用户的称呼，如"小陈""陈总""Kevin"
            candidates: 候选员工列表，每项含 employee_no/name/department 字段

        Returns:
            最佳匹配的 employee_no；多候选同等匹配度返回 None（由调用方 disambiguate）；
            LLM 不可用返回 None（回退到 SQL 模糊匹配）
        """
        if not self.is_available() or not candidates or not user_ref:
            return None

        if len(candidates) == 1:
            return candidates[0].get("employee_no")

        items_text = "\n".join(
            f"- 工号={c.get('employee_no') or ''} | 姓名={c.get('name') or ''} | 部门={c.get('department') or ''}"
            for c in candidates
        )

        prompt = f"""用户称呼：「{user_ref}」

判断用户指的是下列哪位员工。综合考虑昵称（小陈=陈、老王=王）、尊称（X总/X工）、英文名等语义等价关系。

候选员工：
{items_text}

严格返回 JSON：{{"matched_employee_no": "匹配的工号，无匹配则为空字符串"}}"""

        try:
            response = await self.client.chat.completions.create(
                model=settings.get_model_for_task("fee_classify"),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=100,
            )
            result = json.loads(response.choices[0].message.content)
            return result.get("matched_employee_no") or None
        except Exception as e:
            logger.error(f"LLM resolve_person_llm failed: {e}")
            return None

    async def classify_filter_type(self, filter_type: str) -> str:
        """LLM 判断 filter_type 槽位值是异常条件还是费用分类词

        NLU 偶尔把"打车费""快递费"等费用分类词误填进 filter_type 槽位（应走 category_amount）。
        此方法做一次轻量 LLM 判定，避免误把异常条件（如"重复""验真失败"）也当分类词转交。

        Args:
            filter_type: NLU 填入的 filter_type 值

        Returns:
            "issue"（异常条件，按 invoice_filter 处理）或 "category"（费用分类词，转交 category_amount）
        """
        if not self.is_available() or not filter_type:
            return "category"  # LLM 不可用时默认当分类词（兜底走语义筛选更安全）

        prompt = f"""判断以下 filter_type 值属于「异常条件」还是「费用分类词」：

filter_type 值：{filter_type}

判定规则：
- 异常条件（issue）：发票状态/质量相关的筛选词，如"重复""验真失败""高风险""待审核""收据""invalid""duplicate"等
- 费用分类词（category）：费用类型/用途相关的词，如"打车费""快递费""差旅费""餐饮费""培训费""投标费""办公费""住宿费""交通费"等

严格返回 JSON：{{"kind": "issue" 或 "category"}}"""

        try:
            response = await self.client.chat.completions.create(
                model=settings.get_model_for_task("fee_classify"),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=50,
            )
            result = json.loads(response.choices[0].message.content)
            return result.get("kind") == "issue" and "issue" or "category"
        except Exception as e:
            logger.error(f"LLM classify_filter_type failed: {e}")
            return "category"

    async def classify_invoices_by_category(
        self,
        category_keyword: str,
        candidates: list[dict],
    ) -> list[int]:
        """LLM 语义筛选：判断候选发票中哪些属于用户问的分类

        替代硬编码别名字典 + 子串包含匹配。LLM 能理解"打车费"="差旅-交通子类下用途
        为打车费的发票"这类语义等价关系，避免字典穷尽不到口语词导致漏匹配。

        Args:
            category_keyword: 用户问的分类词，如"打车费""快递费""差旅-交通"
            candidates: 候选发票列表，每项含 id、fee_subcategory、fee_category、
                        item_name、user_description 字段

        Returns:
            属于该分类的发票 id 列表；LLM 不可用或调用失败返回空列表（调用方回退到硬编码）
        """
        if not self.is_available() or not candidates or not category_keyword:
            return []

        # 压缩候选发票字段，降低 token 消耗
        items_text = "\n".join(
            f"#{c['id']} | subcat={c.get('fee_subcategory') or ''} | "
            f"cat={c.get('fee_category') or ''} | item={c.get('item_name') or ''} | "
            f"desc={c.get('user_description') or ''}"
            for c in candidates
        )

        prompt = f"""判断下列发票中哪些属于「{category_keyword}」分类。

判定原则：
- fee_subcategory 是分类器映射后的标准子类（如"差旅-交通""快递物流费"），可能与用户口语词不同义
- user_description 是用户上传时填写的费用用途，常含原始口语词（如"打车费"）
- 综合参考 subcategory、category、item_name、user_description 四个字段做语义判断
- **必须严格语义等价**：用户问的「{category_keyword}」与发票实际用途必须是同一类支出
  - 例：用户问"打车费"时，subcat=差旅-交通 + desc=打车费 的发票应判为属于（打车费是差旅交通的子类）
  - 例：用户问"快递费"时，subcat=快递物流费 的发票应判为属于（语义等价）
  - 例：用户问"出行费"时，subcat=差旅-交通（含打车/打车费/出行子词）的发票应判为属于（出行含打车）
  - 例：用户问"办公费"时，subcat=差旅-交通 + desc=打车费 的发票**不属于**（打车费≠办公费，是交通类）
  - 例：用户问"住宿费"时，subcat=差旅-交通 + desc=打车费 的发票**不属于**（打车费≠住宿费）
  - 例：用户问"配合费"时，desc=项目配合费 的发票应判为属于（语义等价）
- **不确定时宁可漏匹配不要误匹配**：若发票的 subcategory/description 与「{category_keyword}」
  无明确语义等价关系，不要纳入 matched_ids

候选发票：
{items_text}

严格返回以下 JSON：{{"matched_ids": [属于该分类的发票id列表]}}"""

        try:
            response = await self.client.chat.completions.create(
                model=settings.get_model_for_task("fee_classify"),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=400,
            )
            result = json.loads(response.choices[0].message.content)
            ids = result.get("matched_ids", [])
            return [int(i) for i in ids if isinstance(i, (int, str)) and str(i).lstrip("-").isdigit()]
        except Exception as e:
            logger.error(f"LLM classify_invoices_by_category failed: {e}")
            return []

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
                model=settings.get_model_for_task("project_extract"),  # 项目名提取：短文本+已知列表，路由到快模型
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
