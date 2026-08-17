"""NLU 结果 Pydantic Schema — Step 1.2.1

定义 LLM 意图识别的输出契约，用于：
1. response_format json_schema：强制 LLM 返回结构化 JSON
2. Pydantic TypeAdapter 校验：替代脆弱的 split("```json") 解析
3. 失败自动重试：校验不通过时由调用方重试 1 次

字段对齐 dialog/models.py 的 NluResult dataclass 中"LLM 应输出的部分"：
- intent_name / confidence / slots / reasoning
- level / raw_text / candidates 由后端代码注入，不要求 LLM 输出
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class NluResultSchema(BaseModel):
    """LLM NLU 输出契约

    对应 llm_nlu.py _SYSTEM_PROMPT 中的输出格式约定：
    ```json
    {
      "intent_name": "意图名称，如果都不匹配则为空字符串",
      "confidence": 0.0到1.0的浮点数,
      "slots": {"槽位名": "槽位值"},
      "reasoning": "简要推理过程"
    }
    ```
    """

    model_config = ConfigDict(
        # 允许 LLM 返回额外字段（向前兼容，避免 LLM 偶尔加字段导致校验失败）
        extra="ignore",
        # 数值范围校验：confidence 必须在 [0, 1]
        str_strip_whitespace=True,
    )

    intent_name: str = Field(
        default="",
        description="意图名称，如果都不匹配则为空字符串",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="置信度，0.0 到 1.0 的浮点数",
    )
    slots: dict[str, Any] = Field(
        default_factory=dict,
        description="槽位名到槽位值的映射",
    )
    reasoning: str = Field(
        default="",
        description="简要推理过程，用于调试与 badcase 分析",
    )


# ============================================================
# 批量描述拆解 Schema — 用于 _call_llm_batch_describe
# ============================================================

class BatchDescribeItemSchema(BaseModel):
    """批量描述拆解的单条结果"""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    invoice_id: int = Field(description="发票 ID")
    description: str = Field(default="", description="该发票的用途描述")


class BatchDescribeResultSchema(BaseModel):
    """批量描述拆解结果（JSON 数组的元素）

    注意：LLM 实际返回的是 JSON 数组 [{invoice_id, description}, ...]，
    而非单个对象。校验时用 TypeAdapter(list[BatchDescribeItemSchema])。
    """

    model_config = ConfigDict(extra="ignore")
    items: list[BatchDescribeItemSchema] = Field(default_factory=list)
