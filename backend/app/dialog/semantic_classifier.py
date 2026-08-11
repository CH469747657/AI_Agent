"""L2 语义分类器 — 覆盖口语化表述

架构：
- 每个意图预定义 10-20 条典型表述模板
- 使用字符 n-gram 向量化 + 余弦相似度匹配（零外部依赖）
- 置信度阈值：>= 0.65 视为匹配，< 0.65 则 fallback 到 L3

性能：
- 初始化 ~1ms（纯内存）
- 分类 ~5-10ms（纯 Python 计算）
- 无网络调用、无 GPU 依赖
"""

from __future__ import annotations

import math
import logging
from collections import Counter
from typing import Any

from .models import NluResult, NluLevel, UserRole, DialogContext

logger = logging.getLogger(__name__)


# ============================================================
# 意图典型表述模板
# 格式: intent_name -> [典型表述列表]
# ============================================================

_INTENT_TEMPLATES: dict[str, list[str]] = {
    # --- 通用 ---
    "common_help": [
        "怎么用", "能做什么", "有什么功能", "使用说明",
        "帮我看看怎么操作", "我不太会用", "教教我",
    ],
    "common_cancel": [
        "不要了", "不做了", "算了算了", "取消掉", "别搞了",
        "放弃", "重来", "退出当前操作",
    ],
    "common_greeting": [
        "你好", "在不在", "有人吗", "嗨嗨", "哈喽",
        "你好啊", "您好", "嗨你好", "你好呀",
    ],

    # --- 员工提单 ---
    "emp_no_receipt": [
        "没有发票怎么报", "我手头没发票", "没有票能不能报",
        "发票丢了", "没带发票", "没票报销",
    ],
    "emp_submit_reimbursement": [
        "提交报销", "好了提交吧", "可以提交了", "我报完了",
        "发出去吧", "帮我提交", "确认提交报销单",
        "报销单提交", "好提交", "报完了提交",
    ],
    "emp_batch_upload": [
        "还有几张发票", "我再加一张", "继续上传", "再加一张票",
        "还有发票要传", "再传一张",
    ],
    "emp_fill_purpose": [
        "用途是出差", "用于项目", "报销事由", "我来说一下用途",
        "这笔钱是花在", "是出差的费用",
    ],
    "emp_query_status": [
        "我的报销到哪了", "审批进度怎么样", "报销单什么状态",
        "帮我查一下报销", "我提交的那个报了没", "报销进度",
        "看看我的报销单", "报销到哪一步了",
        "上次提的报销批了没", "那笔报销什么情况",
        "报销批了没", "报销通过了吗", "上次报销批了没",
    ],
    "emp_query_invoices": [
        "我上传的发票", "看看我的票", "我的票据", "已上传的发票",
        "帮我查查发票", "有哪些发票", "我传了哪些票",
        "发票拍好了怎么传", "怎么上传发票", "发票怎么传",
        "怎么传发票", "发票怎么上传",
    ],

    # --- 员工自我洞察 ---
    "self_insight_total": [
        "我花了多少钱", "我报了多少钱", "我的报销总额",
        "帮我看看我花了多少", "我这一共多少", "我消费了多少",
        "我总共报了多少", "我的费用合计",
    ],
    "self_insight_category": [
        "我哪类花得多", "我的费用类别分布", "我花钱主要在哪方面",
        "我的开支构成", "我报的钱都是什么类型", "我费用分布",
        "帮我看看我的开销分类", "我的花销占比",
        "差旅费住宿费各占多少比例", "费用各占多少比例",
    ],
    "self_insight_category_amount": [
        "快递费花了多少", "差旅费报了多少", "培训费花了多少",
        "住宿费花了多少", "办公费报了多少", "交通费用多少",
        "我快递费花了多少", "我差旅费报了多少", "我培训费花了多少",
        "运营费花了多少", "投标费报了多少",
    ],
    "self_insight_trend": [
        "我的费用变化趋势", "我每个月花了多少", "我花钱的走势",
        "帮我看看我最近的开支变化", "我的开销逐月", "我的费用涨了还是降了",
        "我花钱的趋势怎么样",
        "最近三个月我的报销有没有增长", "我的费用增长",
        "我的开支有没有增长", "我报销涨了吗",
    ],
    "self_insight_compare": [
        "我这个月和上个月比", "这个月比上月花得多吗", "我的开支环比",
        "最近两个月我花的对比", "我这个月花得多还是少",
    ],
    "self_insight_pending": [
        "我还有没有没报的", "有没有还没提交的票", "我忘了报销的",
        "帮我查查未提交的票据", "我漏报了吗", "还有哪些票没报",
        "还有几张票没报", "有没有没报的", "还有多少票没报",
    ],

    # --- 管理员 ---
    "admin_query_pending": [
        "有哪些待审批的", "还没处理的报销单", "等人批的报销",
        "帮我看看待审批", "需要我审的报销单", "还没审批的",
    ],
    "admin_approve": [
        "批准这个报销", "通过审批", "同意报销", "批准报销单",
        "审批通过", "给通过了",
    ],
    "admin_reject": [
        "驳回这个报销", "不同意", "审批不通过", "拒绝报销",
        "打回去", "驳回报销单",
    ],
    "admin_query_detail": [
        "看看报销单详情", "这个报销单具体内容", "打开报销单看看",
        "查看报销单",
    ],

    # --- 全局洞察 ---
    "insight_total": [
        "公司花了多少", "公司报销总额", "总共报了多少", "公司总费用",
        "全公司开支", "公司一共花了多少", "组织费用合计",
        "本月报销总额", "这月花了多少",
        # 老板视角："我的开支" = 公司开支
        "我上个月的开支", "我的开支情况", "上个月花了多少",
        "我这个月花了多少", "我的费用合计",
    ],
    "insight_by_dept": [
        "哪个部门花得多", "各部门费用排名", "部门开支对比",
        "哪个部门报销最多", "帮我看看部门费用", "部门费用分布",
    ],
    "insight_by_category": [
        "费用类别占比", "各类别花了多少", "什么类型花得多",
        "费用分布", "开支结构", "报销类别统计",
    ],
    "insight_category_amount": [
        "快递费花了多少", "差旅费报了多少", "培训费花了多少",
        "住宿费花了多少", "办公费报了多少", "交通费用多少",
        "公司快递费花了多少", "公司差旅费报了多少",
        "运营费花了多少", "投标费报了多少",
    ],
    "insight_trend": [
        "最近半年费用趋势", "费用变化趋势", "公司开支走势",
        "逐月费用", "费用增长还是下降", "开支趋势",
        # 老板视角
        "我上个月的开支趋势", "我的开支变化", "我最近的开支",
        "我的费用走势", "我开支的走势",
    ],
    "insight_compare": [
        "费用环比对比", "本月和上月比", "对比一下费用",
        "开支同比环比", "两个月对比",
    ],
    "insight_anomaly": [
        "有没有异常", "异常报销", "违规报销", "有没有问题发票",
        "查查异常", "有重复报销吗", "超标报销",
    ],
    "insight_top": [
        "费用最高的前10人", "谁报销最多", "花钱最多的人",
        "排行榜", "费用排名", "报销金额排名",
    ],
    "insight_person": [
        "查张三的费用", "看看李四的报销", "某个人的报销情况",
        "查一下王五的开销", "这个人花了多少",
        "张三花了多少钱", "李四的报销情况",
        "某某的费用", "谁花了多少钱",
    ],
    "insight_project": [
        "项目费用统计", "这个项目花了多少", "项目开支",
        "某个项目的报销", "项目报销汇总",
        # 查询类表述
        "关于项目的有哪些报销", "项目投标的报销项",
        "项目相关的报销", "看看项目的费用",
    ],
}


# ============================================================
# 字符 n-gram 向量化 + 余弦相似度
# ============================================================

def _char_ngrams(text: str, n: int = 2) -> Counter:
    """提取字符 n-gram 词频向量"""
    text = text.strip().lower()
    if len(text) < n:
        return Counter({text: 1})
    grams = Counter()
    for i in range(len(text) - n + 1):
        grams[text[i:i+n]] += 1
    return grams


def _cosine_similarity(v1: Counter, v2: Counter) -> float:
    """计算两个词频向量的余弦相似度"""
    if not v1 or not v2:
        return 0.0
    # 点积
    common = set(v1.keys()) & set(v2.keys())
    dot = sum(v1[k] * v2[k] for k in common)
    # 模
    norm1 = math.sqrt(sum(v * v for v in v1.values()))
    norm2 = math.sqrt(sum(v * v for v in v2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


class SemanticClassifier:
    """L2 语义分类器

    使用字符 bigram + 余弦相似度匹配用户输入与意图模板。
    优点：零外部依赖，~5ms 延迟，覆盖口语化表述
    缺点：不如深度语义模型精准，需依赖 L3 处理复杂表述
    """

    # 置信度阈值（中文 bigram 相似度天然偏低，0.45 即可匹配有语义关联的表述）
    CONFIDENCE_THRESHOLD = 0.45

    def __init__(self):
        self._template_vectors: dict[str, list[Counter]] = {}
        self._precompute()

    def _precompute(self) -> None:
        """预计算所有模板的 n-gram 向量"""
        for intent, templates in _INTENT_TEMPLATES.items():
            self._template_vectors[intent] = [_char_ngrams(t) for t in templates]

    def classify(
        self,
        text: str,
        context: DialogContext,
    ) -> NluResult | None:
        """对用户输入做语义分类

        Args:
            text: 用户输入
            context: 对话上下文

        Returns:
            NluResult 或 None（低于阈值时返回 None，由 L3 接管）
        """
        role = context.role
        input_vec = _char_ngrams(text)

        # 按角色过滤可用意图
        allowed_prefixes = self._get_role_prefixes(role)

        best_intent = ""
        best_score = 0.0
        candidates: list[tuple[str, float]] = []

        for intent, template_vecs in self._template_vectors.items():
            # 角色过滤
            if not any(intent.startswith(p) for p in allowed_prefixes):
                continue

            # 计算与该意图所有模板的最大相似度
            max_sim = 0.0
            for tvec in template_vecs:
                sim = _cosine_similarity(input_vec, tvec)
                if sim > max_sim:
                    max_sim = sim

            if max_sim > 0:
                candidates.append((intent, max_sim))
                if max_sim > best_score:
                    best_score = max_sim
                    best_intent = intent

        # 排序取 Top 3
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidates[:3]

        if best_score < self.CONFIDENCE_THRESHOLD:
            logger.info(
                "L2 below threshold: text=%r best=%s score=%.3f (threshold=%.2f)",
                text, best_intent, best_score, self.CONFIDENCE_THRESHOLD,
            )
            # 返回候选但不作为最终结果，让 L3 接管
            if top_candidates:
                return NluResult(
                    intent_name="",
                    confidence=best_score,
                    level=NluLevel.L2_SEMANTIC,
                    raw_text=text,
                    candidates=top_candidates,
                )
            return None

        logger.info(
            "L2 classified: text=%r intent=%s confidence=%.3f",
            text, best_intent, best_score,
        )
        return NluResult(
            intent_name=best_intent,
            confidence=best_score,
            level=NluLevel.L2_SEMANTIC,
            raw_text=text,
            candidates=top_candidates,
        )

    def _get_role_prefixes(self, role: UserRole) -> tuple[str, ...]:
        """根据角色返回允许的意图前缀"""
        if role == UserRole.EMPLOYEE:
            return ("common_", "emp_", "self_insight_", "insight_")
        elif role == UserRole.ADMIN:
            return ("common_", "emp_", "admin_", "self_insight_", "insight_")
        elif role == UserRole.BOSS:
            return ("common_", "insight_", "emp_query_")
        return ("common_",)


# 全局单例
_classifier: SemanticClassifier | None = None


def get_semantic_classifier() -> SemanticClassifier:
    """获取语义分类器单例"""
    global _classifier
    if _classifier is None:
        _classifier = SemanticClassifier()
        logger.info("Semantic classifier initialized with %d intents", len(_INTENT_TEMPLATES))
    return _classifier
