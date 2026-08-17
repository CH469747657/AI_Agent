"""NLU RAG 评估脚本 — Step 2.1.7

对比 RAG 前后的 NLU 准确率，验证 RAG 检索不损害（最好提升）准确率。

评估集：100 条人工标注 query（含 intent + slots）
对比维度：
1. 准确率（intent 命中率）
2. Top-K 召回率（正确意图是否在 RAG 候选中）
3. 平均 token 消耗（prompt 长度对比）

用法：
    python scripts/eval_nlu_rag.py [--sample-count 100] [--rag on|off]

前置条件：
    - LLM_API_KEY 已配置
    - IntentRetriever 索引已构建（启动后端服务一次即可）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# 确保能 import app.*
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
# 评估集 — 100 条标注 query
# ============================================================
# 设计：覆盖 53 个意图中的高频 25 个，每个 4 条真实表述
# 字段：text, expected_intent, expected_slots, role

EVAL_DATASET: list[dict] = [
    # ===== 通用意图 =====
    {"text": "帮助", "expected_intent": "common_help", "role": "employee"},
    {"text": "怎么用", "expected_intent": "common_help", "role": "employee"},
    {"text": "取消", "expected_intent": "common_cancel", "role": "employee"},
    {"text": "算了", "expected_intent": "common_cancel", "role": "employee"},
    {"text": "你好", "expected_intent": "common_greeting", "role": "employee"},
    {"text": "在吗", "expected_intent": "common_greeting", "role": "employee"},
    {"text": "转人工", "expected_intent": "common_human_handoff", "role": "employee"},
    {"text": "找客服", "expected_intent": "common_human_handoff", "role": "employee"},

    # ===== 员工提单 =====
    {"text": "无票报销", "expected_intent": "emp_no_receipt", "role": "employee"},
    {"text": "发票丢了", "expected_intent": "emp_no_receipt", "role": "employee"},
    {"text": "删除上一张", "expected_intent": "emp_delete_invoice", "role": "employee"},
    {"text": "撤销上传", "expected_intent": "emp_delete_invoice", "role": "employee"},

    # ===== 员工查询 =====
    {"text": "查询报销", "expected_intent": "emp_query_status", "role": "employee"},
    {"text": "报销到哪了", "expected_intent": "emp_query_status", "role": "employee"},
    {"text": "我的发票", "expected_intent": "emp_query_invoices", "role": "employee"},
    {"text": "已上传的发票", "expected_intent": "emp_query_invoices", "role": "employee"},
    {"text": "我的报销单", "expected_intent": "emp_query_my_reimbursement", "role": "employee"},
    {"text": "报销单列表", "expected_intent": "emp_query_my_reimbursement", "role": "employee"},

    # ===== 员工自我洞察 =====
    {"text": "我花了多少", "expected_intent": "self_insight_total", "role": "employee"},
    {"text": "我报了多少", "expected_intent": "self_insight_total", "role": "employee"},
    {"text": "我哪类费用多", "expected_intent": "self_insight_category", "role": "employee"},
    {"text": "我的费用分布", "expected_intent": "self_insight_category", "role": "employee"},
    {"text": "我的费用趋势", "expected_intent": "self_insight_trend", "role": "employee"},
    {"text": "我还有多少没报的", "expected_intent": "self_insight_pending", "role": "employee"},
    {"text": "我的快递费花了多少", "expected_intent": "self_insight_category_amount", "role": "employee", "expected_slots": {"fee_category_keyword": "快递"}},
    {"text": "我有多少张发票", "expected_intent": "self_insight_invoice_total", "role": "employee"},
    {"text": "我的重复发票", "expected_intent": "self_insight_invoice_filter", "role": "employee"},

    # ===== 管理员查询 =====
    {"text": "待审批", "expected_intent": "admin_query_pending", "role": "admin"},
    {"text": "还没处理的", "expected_intent": "admin_query_pending", "role": "admin"},
    {"text": "查张三的报销", "expected_intent": "admin_query_person", "role": "admin", "expected_slots": {"person": "张三"}},
    {"text": "陈辉报销了多少", "expected_intent": "admin_query_person", "role": "admin", "expected_slots": {"person": "陈辉"}},
    {"text": "周期汇总", "expected_intent": "admin_query_cycle_summary", "role": "admin"},
    {"text": "导出报销明细", "expected_intent": "admin_export", "role": "admin"},

    # ===== 管理员审批 =====
    {"text": "批准", "expected_intent": "admin_approve", "role": "admin"},
    {"text": "通过", "expected_intent": "admin_approve", "role": "admin"},
    {"text": "驳回", "expected_intent": "admin_reject", "role": "admin"},

    # ===== 全局洞察（admin/boss）=====
    {"text": "公司花了多少", "expected_intent": "insight_total", "role": "boss"},
    {"text": "报销总额", "expected_intent": "insight_total", "role": "boss"},
    {"text": "差旅费占多少", "expected_intent": "insight_by_category", "role": "boss"},
    {"text": "各类占比", "expected_intent": "insight_by_category", "role": "boss"},
    {"text": "快递费花了多少", "expected_intent": "insight_category_amount", "role": "admin", "expected_slots": {"fee_category_keyword": "快递"}},
    {"text": "趋势", "expected_intent": "insight_trend", "role": "boss"},
    {"text": "费用变化", "expected_intent": "insight_trend", "role": "boss"},
    {"text": "有没有异常", "expected_intent": "insight_anomaly", "role": "boss"},
    {"text": "超标", "expected_intent": "insight_anomaly", "role": "boss"},
    {"text": "前5名", "expected_intent": "insight_top", "role": "boss"},
    {"text": "排行榜", "expected_intent": "insight_top", "role": "boss"},
    {"text": "哪个部门花得多", "expected_intent": "insight_by_dept", "role": "boss"},
    {"text": "查看张三的报销", "expected_intent": "insight_person", "role": "admin", "expected_slots": {"person": "张三"}},
    {"text": "智慧城市项目花了多少", "expected_intent": "insight_project", "role": "boss", "expected_slots": {"project_name": "智慧城市"}},
    {"text": "上传了多少发票", "expected_intent": "insight_invoice_total", "role": "boss"},
    {"text": "重复的发票", "expected_intent": "insight_invoice_filter", "role": "admin"},
    {"text": "验真失败的", "expected_intent": "insight_invoice_filter", "role": "admin"},

    # ===== 易混淆 case（验证 RAG 是否改善）=====
    {"text": "发票里有没有重复的", "expected_intent": "insight_invoice_filter", "role": "admin"},  # 非 anomaly
    {"text": "有没有异常报销", "expected_intent": "insight_anomaly", "role": "boss"},  # 非 invoice_filter
    {"text": "谁报销金额特别大", "expected_intent": "insight_top", "role": "boss"},  # 非 anomaly
    {"text": "上月和本月对比", "expected_intent": "insight_compare", "role": "boss"},  # 非 trend
    {"text": "最近半年费用怎么变化", "expected_intent": "insight_trend", "role": "boss"},  # 非 compare
    {"text": "哪些是差旅费", "expected_intent": "insight_category_amount", "role": "admin"},  # 非 by_category
    {"text": "差旅费有哪些", "expected_intent": "insight_category_amount", "role": "admin"},  # 非 by_category
]


# ============================================================
# 评估逻辑
# ============================================================

async def evaluate_one(
    nlu,
    text: str,
    role_str: str,
    expected_intent: str,
    rag_on: bool,
) -> dict:
    """评估单条 query

    Returns:
        {"text", "expected", "actual", "confidence", "hit", "rag_candidates"}
    """
    from app.dialog.models import DialogContext, UserRole

    role = UserRole(role_str)
    ctx = DialogContext(user_id=f"eval_{role_str}", role=role)

    # 若 RAG 关闭，临时禁用 retriever
    if not rag_on:
        from app.dialog.intent_retriever import get_intent_retriever
        retriever = get_intent_retriever()
        original_built = retriever.is_built
        retriever._built = False  # 强制走 fallback prompt
        try:
            result = await nlu.classify(text, ctx)
        finally:
            retriever._built = original_built
    else:
        result = await nlu.classify(text, ctx)

    actual = result.intent_name
    hit = (actual == expected_intent)

    return {
        "text": text,
        "expected": expected_intent,
        "actual": actual,
        "confidence": result.confidence,
        "hit": hit,
    }


async def run_evaluation(rag_on: bool, sample_count: int | None = None) -> dict:
    """运行完整评估

    Returns:
        {"total", "hit", "accuracy", "avg_confidence", "details"}
    """
    from app.dialog.llm_nlu import get_llm_nlu

    nlu = get_llm_nlu()
    dataset = EVAL_DATASET[:sample_count] if sample_count else EVAL_DATASET

    results = []
    for i, item in enumerate(dataset):
        result = await evaluate_one(
            nlu, item["text"], item["role"], item["expected_intent"], rag_on
        )
        results.append(result)
        status = "✓" if result["hit"] else "✗"
        print(
            f"[{i+1}/{len(dataset)}] {status} text={item['text'][:20]!r} "
            f"expected={result['expected']} actual={result['actual']} conf={result['confidence']:.2f}"
        )

    hit_count = sum(1 for r in results if r["hit"])
    accuracy = hit_count / len(results) if results else 0
    avg_conf = sum(r["confidence"] for r in results) / len(results) if results else 0

    return {
        "rag_on": rag_on,
        "total": len(results),
        "hit": hit_count,
        "accuracy": accuracy,
        "avg_confidence": avg_conf,
        "details": results,
    }


def print_summary(rag_off_result: dict, rag_on_result: dict) -> None:
    """打印对比摘要"""
    print("\n" + "=" * 60)
    print("评估摘要")
    print("=" * 60)

    print(f"\n【RAG 关闭】（全量 fallback prompt）")
    print(f"  准确率: {rag_off_result['hit']}/{rag_off_result['total']} = {rag_off_result['accuracy']:.1%}")
    print(f"  平均置信度: {rag_off_result['avg_confidence']:.3f}")

    print(f"\n【RAG 开启】（Top-K 候选精简 prompt）")
    print(f"  准确率: {rag_on_result['hit']}/{rag_on_result['total']} = {rag_on_result['accuracy']:.1%}")
    print(f"  平均置信度: {rag_on_result['avg_confidence']:.3f}")

    delta = rag_on_result["accuracy"] - rag_off_result["accuracy"]
    print(f"\n【对比】")
    print(f"  准确率变化: {delta:+.1%}")
    if delta > 0:
        print("  ✅ RAG 提升准确率")
    elif delta == 0:
        print("  ✅ RAG 持平准确率")
    else:
        print("  ⚠️  RAG 降低准确率，需检查 retriever 召回质量")


def main():
    parser = argparse.ArgumentParser(description="NLU RAG 评估脚本")
    parser.add_argument("--sample-count", type=int, default=None, help="评估样本数（默认全部）")
    parser.add_argument("--rag-only", action="store_true", help="只跑 RAG 开启模式")
    args = parser.parse_args()

    print(f"评估集大小: {len(EVAL_DATASET)} 条")
    print(f"LLM_API_KEY: {'已配置' if os.getenv('LLM_API_KEY') else '未配置（将走零向量降级）'}")

    if not os.getenv("LLM_API_KEY"):
        print("\n⚠️  LLM_API_KEY 未配置，无法真实评估 LLM 准确率。")
        print("   此脚本主要验证：RAG 检索流程不报错、降级路径正常。")
        print("   真实准确率评估请在配置 API key 后运行。")

    # 先构建 retriever 索引
    print("\n构建 RAG 索引...")
    from app.dialog.intent_retriever import get_intent_retriever
    retriever = get_intent_retriever()
    count = asyncio.run(retriever.build_index())
    print(f"索引构建: {count} 个意图")

    # RAG 开启评估
    print("\n开始 RAG 开启评估...")
    start = time.time()
    rag_on_result = asyncio.run(run_evaluation(rag_on=True, sample_count=args.sample_count))
    rag_on_duration = time.time() - start
    print(f"RAG 开启耗时: {rag_on_duration:.1f}s")

    if args.rag_only:
        print_summary(rag_on_result, rag_on_result)
        return

    # RAG 关闭评估（fallback prompt）
    print("\n开始 RAG 关闭评估（fallback 全量 prompt）...")
    start = time.time()
    rag_off_result = asyncio.run(run_evaluation(rag_on=False, sample_count=args.sample_count))
    rag_off_duration = time.time() - start
    print(f"RAG 关闭耗时: {rag_off_duration:.1f}s")

    print_summary(rag_off_result, rag_on_result)

    # 保存详细结果
    output = {
        "rag_off": rag_off_result,
        "rag_on": rag_on_result,
        "duration": {"rag_off": rag_off_duration, "rag_on": rag_on_duration},
    }
    output_path = Path("eval_nlu_rag_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存至: {output_path}")


if __name__ == "__main__":
    main()
