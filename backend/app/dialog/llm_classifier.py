"""L3 LLM 意图理解 — 开放域问题、复杂多意图

架构：
- 使用 OpenAI 兼容接口（配置中的 LLM Provider）
- 构造 system prompt 列出所有意图 + 槽位定义
- LLM 返回结构化 JSON（intent_name + confidence + slots）
- 超时保护：3s 超时自动降级到"未识别"
- 成本控制：仅在 L1/L2 未命中时调用

性能：
- 延迟 1-3s（取决于 LLM Provider）
- 每次调用消耗约 200-400 tokens
"""

from __future__ import annotations

import json
import logging
import asyncio
from typing import Any

from .models import NluResult, NluLevel, UserRole, DialogContext
from .semantic_classifier import get_semantic_classifier

logger = logging.getLogger(__name__)


# ============================================================
# LLM 意图理解 System Prompt
# ============================================================

_SYSTEM_PROMPT = """你是AI报销智能体的意图识别引擎。根据用户输入和角色，从该角色可用的意图中选择最匹配的意图，并提取相关槽位。

## 角色与可用意图映射

- **employee**（员工）可用: common_help, common_cancel, common_greeting, emp_no_receipt, emp_submit_reimbursement, emp_batch_upload, emp_fill_purpose, emp_query_status, emp_query_invoices, self_insight_total, self_insight_category, self_insight_category_amount, self_insight_trend, self_insight_compare, self_insight_pending
- **admin**（管理员）可用: 上述所有 + admin_query_pending, admin_query_detail, admin_approve, admin_reject, insight_total, insight_by_dept, insight_by_category, insight_category_amount, insight_trend, insight_compare, insight_anomaly, insight_top, insight_person, insight_project
- **boss**（老板）可用: common_help, common_cancel, common_greeting, insight_total, insight_by_dept, insight_by_category, insight_category_amount, insight_trend, insight_compare, insight_anomaly, insight_top, insight_person, insight_project, emp_query_status

## 关键语义判别规则

1. **员工说"我花了多少"** → 个人开支 → self_insight_total；**老板说"我花了多少"** → 公司开支 → insight_total。绝不能为老板返回self_insight_*意图！
2. **提到具体人名（张三/李四等）的费用** → insight_person，而非 insight_total
3. **"各占多少比例"/"占比"/"分布"** → insight_by_category 或 self_insight_category
4. **提到具体分类名+金额查询**（如"快递费花了多少"、"差旅费报了多少"）→ insight_category_amount 或 self_insight_category_amount，而非 insight_by_category
5. **"增长"/"波动"/"有没有涨"** → insight_trend 或 self_insight_trend，而非 emp_query_status
5. **"发票怎么传"/"怎么上传"** → emp_query_invoices（引导用户上传）
6. **"批了没"/"什么情况"且上下文含报销单** → emp_query_status

## 可提取的槽位

- period: 时间段（current_month/last_month/current_year/last_year/last_6_months/last_12_months/YYYY-MM/YYYY）
- person: 人员姓名
- project_name: 项目名称
- fee_category_keyword: 费用分类关键词（差旅/交通/住宿/餐饮/培训/快递/办公/投标/运营）
- limit: 排名数量（整数）
- reimb_id: 报销单编号（整数）

## 输出格式

请严格返回以下 JSON 格式，不要包含其他文字：
{
  "intent_name": "意图名称，如果都不匹配则为空字符串",
  "confidence": 0.0到1.0的浮点数,
  "slots": {"槽位名": "槽位值"},
  "reasoning": "简要推理过程"
}
"""


class LlmIntentClassifier:
    """L3 LLM 意图理解

    当 L1 关键词和 L2 语义分类都无法识别时，调用 LLM 进行意图理解。
    支持所有配置的 LLM Provider（qwen/deepseek/openai/anthropic）。
    """

    # 超时保护
    TIMEOUT_SECONDS = 5.0
    # 最低置信度阈值
    CONFIDENCE_THRESHOLD = 0.6

    def __init__(self):
        self._client = None
        self._model = None
        self._initialized = False

    def _ensure_client(self):
        """延迟初始化 LLM 客户端"""
        if self._initialized:
            return
        try:
            from app.config import settings, LLM_PROVIDERS
            from openai import OpenAI

            base_url = settings.llm_base_url
            if not base_url:
                provider = settings.llm_provider.lower()
                provider_info = LLM_PROVIDERS.get(provider, {})
                base_url = provider_info.get("base_url", "")

            # 文本模型优先（使用 config.py 的 text_model 属性，自动推导 VL→文本）
            model = settings.text_model

            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=base_url,
            )
            self._model = model
            self._initialized = True
            logger.info("LLM intent classifier initialized: model=%s", model)
        except Exception as e:
            logger.warning("Failed to init LLM client: %s", e)
            self._initialized = True  # 避免反复重试

    async def classify(
        self,
        text: str,
        context: DialogContext,
        l2_candidates: list[tuple[str, float]] | None = None,
    ) -> NluResult | None:
        """调用 LLM 进行意图理解

        Args:
            text: 用户输入
            context: 对话上下文
            l2_candidates: L2 返回的候选意图（帮助 LLM 缩小范围）

        Returns:
            NluResult 或 None（超时或失败时）
        """
        self._ensure_client()
        if not self._client:
            logger.warning("LLM client not available, skipping L3")
            return None

        # 构造用户消息
        user_msg = f"用户角色: {context.role.value}\n用户输入: {text}"
        if l2_candidates:
            cand_str = ", ".join(f"{i}({c:.1f})" for i, c in l2_candidates)
            user_msg += f"\nL2候选意图（仅供参考，可能不准确）: {cand_str}"

        try:
            result = await asyncio.wait_for(
                self._call_llm(user_msg),
                timeout=self.TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("L3 LLM timeout for text=%r", text)
            return None
        except Exception as e:
            logger.warning("L3 LLM error: %s", e)
            return None

        if not result:
            return None

        intent_name = result.get("intent_name", "")
        confidence = result.get("confidence", 0.0)
        slots = result.get("slots", {})

        if not intent_name or confidence < self.CONFIDENCE_THRESHOLD:
            logger.debug(
                "L3 low confidence: text=%r intent=%s conf=%.2f",
                text, intent_name, confidence,
            )
            return NluResult(
                intent_name="",
                confidence=confidence,
                level=NluLevel.L3_LLM,
                raw_text=text,
                extracted_slots=slots,
                candidates=[(intent_name, confidence)] if intent_name else [],
            )

        logger.info(
            "L3 classified: text=%r intent=%s confidence=%.2f",
            text, intent_name, confidence,
        )
        return NluResult(
            intent_name=intent_name,
            confidence=confidence,
            level=NluLevel.L3_LLM,
            raw_text=text,
            extracted_slots=slots,
        )

    async def _call_llm(self, user_msg: str) -> dict | None:
        """调用 LLM API"""
        try:
            resp = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=256,
                timeout=self.TIMEOUT_SECONDS,
            )
            content = resp.choices[0].message.content.strip()
            # 提取 JSON（可能被 markdown 代码块包裹）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("L3 JSON parse error: %s content=%r", e, content[:200])
            return None
        except Exception as e:
            logger.warning("L3 API call error: %s", e)
            return None


# 全局单例
_classifier: LlmIntentClassifier | None = None


def get_llm_classifier() -> LlmIntentClassifier:
    """获取 LLM 分类器单例"""
    global _classifier
    if _classifier is None:
        _classifier = LlmIntentClassifier()
    return _classifier
