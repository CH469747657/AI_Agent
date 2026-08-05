"""费用分类引擎（规则优先 + LLM兜底）

技术路线:
  第一层: 规则匹配（快速、确定性高）
  第二层: LLM语义分类（处理模糊/非标场景）
  第三层: 人工兜底（置信度低于阈值）
"""

import logging
import re
from typing import Optional

from app.models.invoice import ReceiptType, FeeCategory
from app.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)

# 分类置信度阈值，低于此值标记待人工确认
CONFIDENCE_THRESHOLD = 0.6


class RuleBasedClassifier:
    """第一层：规则匹配分类器

    用 Python 字典 + 正则实现轻量规则引擎
    规则可后续迁移到数据库动态管理
    """

    RULES = [
        # === 发票类型 → 大类（兜底，priority最低）===
        {
            "field": "receipt_type",
            "op": "in",
            "values": [ReceiptType.vat_normal, ReceiptType.vat_special],
            "category": FeeCategory.company,
            "subcategory": "运营费",
            "priority": 1,
        },
        {
            "field": "receipt_type",
            "op": "in",
            "values": [ReceiptType.train_ticket, ReceiptType.flight_ticket],
            "category": FeeCategory.personal,
            "subcategory": "差旅-交通",
            "priority": 10,
        },
        {
            "field": "receipt_type",
            "op": "eq",
            "values": ReceiptType.no_receipt,
            "category": FeeCategory.company,
            "subcategory": "配合费",
            "priority": 5,
        },

        # === 销售方关键词 → 类别（priority 20）===
        {
            "field": "seller_name",
            "op": "contains_any",
            "values": ["酒店", "宾馆", "招待所", "住宿", "民宿"],
            "category": FeeCategory.personal,
            "subcategory": "差旅-住宿",
            "priority": 20,
        },
        {
            "field": "seller_name",
            "op": "contains_any",
            "values": ["加油站", "石油", "石化", "中石化", "中石油", "加气站"],
            "category": FeeCategory.personal,
            "subcategory": "差旅-交通",
            "priority": 20,
        },
        {
            "field": "seller_name",
            "op": "contains_any",
            "values": ["航空", "机票", "铁路", "高铁", "出租", "滴滴", "打车"],
            "category": FeeCategory.personal,
            "subcategory": "差旅-交通",
            "priority": 20,
        },
        {
            "field": "seller_name",
            "op": "contains_any",
            "values": ["餐", "饭店", "餐饮", "美食", "食堂"],
            "category": FeeCategory.personal,
            "subcategory": "差旅-餐饮",
            "priority": 20,
        },
        # 快递物流
        {
            "field": "seller_name",
            "op": "contains_any",
            "values": ["顺丰", "邮政", "快递", "物流", "速递", "京东物流", "菜鸟", "德邦", "圆通", "中通快递", "申通", "韵达"],
            "category": FeeCategory.company,
            "subcategory": "快递物流费",
            "priority": 20,
        },
        # 培训教育
        {
            "field": "seller_name",
            "op": "contains_any",
            "values": ["培训", "教育", "学院", "学校", "考证", "职业"],
            "category": FeeCategory.personal,
            "subcategory": "培训费",
            "priority": 20,
        },
        # 招标咨询
        {
            "field": "seller_name",
            "op": "contains_any",
            "values": ["招标", "投标", "采购代理", "咨询", "审计", "评估", "会计", "律师", "事务所"],
            "category": FeeCategory.company,
            "subcategory": "咨询费",
            "priority": 20,
        },
        # 软件信息技术
        {
            "field": "seller_name",
            "op": "contains_any",
            "values": ["软件", "信息科技", "信息技术", "科技", "网络科技", "数据"],
            "category": FeeCategory.company,
            "subcategory": "软件开发费",
            "priority": 15,
        },
        # 办公用品
        {
            "field": "seller_name",
            "op": "contains_any",
            "values": ["办公用品", "文具", "打印", "复印", "办公设备"],
            "category": FeeCategory.company,
            "subcategory": "办公费",
            "priority": 20,
        },

        # === 用户描述关键词 → 类别（priority 30，最高优先级）===
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["搬运", "吊装", "装卸"],
            "category": FeeCategory.company,
            "subcategory": "搬运费",
            "priority": 30,
        },
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["安装", "调试", "维修"],
            "category": FeeCategory.company,
            "subcategory": "安装费",
            "priority": 30,
        },
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["配合", "协调", "工地"],
            "category": FeeCategory.company,
            "subcategory": "配合费",
            "priority": 30,
        },
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["住宿", "住店"],
            "category": FeeCategory.personal,
            "subcategory": "差旅-住宿",
            "priority": 30,
        },
        # 投标招标
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["投标", "招标", "标书", "竞标", "中标"],
            "category": FeeCategory.company,
            "subcategory": "投标费",
            "priority": 30,
        },
        # 快递物流
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["快递", "物流", "寄件", "邮寄", "顺丰", " Postal"],
            "category": FeeCategory.company,
            "subcategory": "快递物流费",
            "priority": 30,
        },
        # 培训考试
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["培训", "学习", "课程", "考试", "考证", "讲座", "研修"],
            "category": FeeCategory.personal,
            "subcategory": "培训费",
            "priority": 30,
        },
        # 咨询代理服务
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["咨询", "代理", "审计", "评估", "律师", "法律", "设计服务", "勘察"],
            "category": FeeCategory.company,
            "subcategory": "咨询费",
            "priority": 30,
        },
        # 办公用品
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["办公用品", "文具", "打印", "耗材", "复印", "纸", "墨盒"],
            "category": FeeCategory.company,
            "subcategory": "办公费",
            "priority": 30,
        },
        # 软件开发
        {
            "field": "user_description",
            "op": "contains_any",
            "values": ["软件开发", "系统开发", "程序", "代码", "信息技术服务"],
            "category": FeeCategory.company,
            "subcategory": "软件开发费",
            "priority": 30,
        },

        # === 金额匹配补贴标准 ===
        {
            "field": "total_with_tax",
            "op": "in",
            "values": ["60", "60.00", "80", "80.00"],
            "category": FeeCategory.personal,
            "subcategory": "补贴",
            "priority": 5,
        },
    ]

    def classify(self, invoice_data: dict, user_desc: str = "") -> dict | None:
        """执行规则匹配，返回第一个命中的分类"""
        # 合并票据数据和用户描述
        context = {**invoice_data, "user_description": user_desc or ""}

        for rule in sorted(self.RULES, key=lambda r: r.get("priority", 0), reverse=True):
            field_val = context.get(rule["field"])
            if field_val is None:
                continue

            matched = self._match(field_val, rule)
            if matched:
                return {
                    "category": rule["category"],
                    "subcategory": rule["subcategory"],
                    "source": "rule",
                    "confidence": 1.0,
                }
        return None

    def _match(self, value, rule) -> bool:
        op = rule["op"]
        targets = rule["values"]

        if op == "eq":
            return value == targets
        elif op == "in":
            return value in targets
        elif op == "contains_any":
            val_str = str(value)
            if isinstance(targets, list):
                return any(t in val_str for t in targets)
            return targets in val_str
        return False


class FeeClassifier:
    """费用分类器：三层策略

    第一层: 规则匹配 → 确定性高，速度最快
    第二层: LLM语义分类 → 处理模糊场景
    第三层: 人工兜底 → 置信度低于阈值标记待确认
    """

    def __init__(self):
        self.rule_engine = RuleBasedClassifier()
        self.llm = get_llm_service()

    async def classify(self, invoice_data: dict, user_desc: str = "") -> dict:
        """执行三层分类策略"""
        # === 第一层：规则匹配 ===
        result = self.rule_engine.classify(invoice_data, user_desc)
        if result and result["confidence"] >= CONFIDENCE_THRESHOLD:
            logger.info(f"Rule-based classification: {result['subcategory']} (confidence=1.0)")
            return result

        # === 第二层：LLM 语义分类 ===
        if self.llm.is_available():
            llm_result = await self.llm.classify_fee(
                receipt_type=str(invoice_data.get("receipt_type", "")),
                seller_name=invoice_data.get("seller_name", ""),
                amount=invoice_data.get("total_with_tax", ""),
                user_desc=user_desc,
            )
            if llm_result and llm_result.get("subcategory"):
                cat_str = llm_result.get("category", "company")
                category = FeeCategory.personal if cat_str == "personal" else FeeCategory.company
                confidence = float(llm_result.get("confidence", 0.5))
                result = {
                    "category": category,
                    "subcategory": llm_result["subcategory"],
                    "source": "llm",
                    "confidence": confidence,
                }
                logger.info(f"LLM classification: {result['subcategory']} (confidence={confidence})")
                return result

        # === 第三层：人工兜底 ===
        logger.warning("Classification confidence below threshold, marking for manual review")
        return {
            "category": None,
            "subcategory": None,
            "source": "manual",
            "confidence": 0.0,
        }
