"""classifier 单元测试

覆盖三层分类策略：
- L1 规则匹配（票据类型、销售方关键词、用户描述、补贴金额）
- L3 人工兜底（无 LLM + 规则未命中）
注意：L2 LLM 分类的测试需 mock，作为后续补充项
"""

import sys
import os
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.invoice import ReceiptType, FeeCategory
from app.services.classifier import RuleBasedClassifier, FeeClassifier, CONFIDENCE_THRESHOLD


class TestRuleBasedClassifier:
    def setup_method(self):
        self.engine = RuleBasedClassifier()

    def test_vat_normal_is_company_fee(self):
        """增值税普通发票 → 公司运营费"""
        result = self.engine.classify({"receipt_type": ReceiptType.vat_normal})
        assert result is not None
        assert result["category"] == FeeCategory.company
        assert result["subcategory"] == "运营费"
        assert result["source"] == "rule"
        assert result["confidence"] == 1.0

    def test_train_ticket_is_personal_travel(self):
        """火车票 → 个人差旅交通"""
        result = self.engine.classify({"receipt_type": ReceiptType.train_ticket})
        assert result is not None
        assert result["category"] == FeeCategory.personal
        assert result["subcategory"] == "差旅-交通"

    def test_flight_ticket_is_personal_travel(self):
        """机票 → 个人差旅交通"""
        result = self.engine.classify({"receipt_type": ReceiptType.flight_ticket})
        assert result is not None
        assert result["category"] == FeeCategory.personal
        assert result["subcategory"] == "差旅-交通"

    def test_hotel_keyword_matches_accommodation(self):
        """销售方含'酒店' → 差旅-住宿"""
        result = self.engine.classify({"seller_name": "全季酒店"})
        assert result is not None
        assert result["subcategory"] == "差旅-住宿"
        assert result["category"] == FeeCategory.personal

    def test_gas_station_keyword_matches_transport(self):
        """销售方含'加油站'/'中石化'/'中石油' → 差旅-交通"""
        for seller in ["中石化加油站", "中石油加油站", "市区加气站"]:
            result = self.engine.classify({"seller_name": seller})
            assert result is not None, f"应命中: {seller}"
            assert result["subcategory"] == "差旅-交通"

    def test_china_petroleum_branch_does_not_match(self):
        """已知覆盖盲区：'中国石化销售有限公司'不含'中石化'/'石油'子串

        规则字段 ["加油站", "石油", "中石化", "中石油", "加气站"] 无法命中。
        真实销售方名常写作'中国石化...'，规则需补充'石化'关键词。
        此测试记录该已知缺口，待补全规则后改为通过。
        """
        result = self.engine.classify({"seller_name": "中国石化销售有限公司"})
        assert result is None  # 当前规则确实不命中

    def test_restaurant_keyword_matches_dining(self):
        """销售方含'餐'/'饭店' → 差旅-餐饮"""
        result = self.engine.classify({"seller_name": "老乡餐饮店"})
        assert result is not None
        assert result["subcategory"] == "差旅-餐饮"

    def test_user_description_install_fee(self):
        """用户描述含'安装'/'调试' → 安装费"""
        result = self.engine.classify(
            {"receipt_type": ReceiptType.vat_normal},
            user_desc="设备安装调试费",
        )
        assert result is not None
        assert result["subcategory"] == "安装费"
        assert result["category"] == FeeCategory.company

    def test_user_description_handling_fee(self):
        """用户描述含'搬运'/'吊装' → 搬运费"""
        result = self.engine.classify(
            {},
            user_desc="工地搬运费",
        )
        assert result is not None
        assert result["subcategory"] == "搬运费"

    def test_subsidy_amount_60(self):
        """金额 60 → 补贴"""
        result = self.engine.classify({"total_with_tax": "60.00"})
        assert result is not None
        assert result["subcategory"] == "补贴"

    def test_subsidy_amount_80(self):
        """金额 80 → 补贴"""
        result = self.engine.classify({"total_with_tax": "80"})
        assert result is not None
        assert result["subcategory"] == "补贴"

    def test_no_rule_match_returns_none(self):
        """无规则命中返回 None"""
        result = self.engine.classify(
            {"receipt_type": ReceiptType.payment_screenshot, "total_with_tax": "100"}
        )
        assert result is None

    def test_priority_user_desc_overrides_seller(self):
        """用户描述优先级 30 > 销售方关键词 20"""
        result = self.engine.classify(
            {"seller_name": "全季酒店"},
            user_desc="工地配合协调费",
        )
        # 用户描述命中的"配合费"优先级更高
        assert result is not None
        assert result["subcategory"] == "配合费"


class TestFeeClassifierManualFallback:
    """三层策略：规则未命中且无 LLM → 人工兜底"""

    def setup_method(self):
        # patch LLM 服务为不可用
        with patch("app.services.classifier.get_llm_service") as mock:
            llm = mock.return_value
            llm.is_available.return_value = False
            self.classifier = FeeClassifier()

    async def test_no_rule_no_llm_returns_manual(self):
        """无规则命中 + 无 LLM → source=manual, confidence=0"""
        result = await self.classifier.classify(
            {"receipt_type": ReceiptType.payment_screenshot, "total_with_tax": "100"}
        )
        assert result["source"] == "manual"
        assert result["confidence"] == 0.0
        assert result["category"] is None
        assert result["subcategory"] is None


class TestFeeClassifierRuleHit:
    """规则命中 → 不调用 LLM"""

    def setup_method(self):
        with patch("app.services.classifier.get_llm_service") as mock:
            llm = mock.return_value
            llm.is_available.return_value = True
            llm.classify_fee = AsyncMock(return_value={})
            self.llm_mock = llm
            self.classifier = FeeClassifier()

    async def test_rule_hit_skips_llm(self):
        """规则命中 → 不调用 LLM"""
        result = await self.classifier.classify({"receipt_type": ReceiptType.vat_normal})
        assert result["source"] == "rule"
        self.llm_mock.classify_fee.assert_not_called()
