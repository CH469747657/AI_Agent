"""文本模型候选对比 — NLU 意图分类

10 条用户输入 × 7 个候选模型，对比分类正确率 + 时延 + reasoning。
"""

import asyncio
import json
import time
import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.WARNING)

from openai import AsyncOpenAI
from app.config import settings

API_KEY = settings.llm_api_key
BASE_URL = settings.llm_base_url

# 10 条典型用户输入 + 期望意图
INTENT_CASES = [
    ("我有哪些发票", "emp_query_invoices"),
    ("上传一张打车费发票", "emp_upload_invoice"),
    ("查询报销单 73 详情", "emp_query_my_reimbursement"),
    ("发票 460 的销方名称对吗", "admin_query_detail"),
    ("修改发票 461 用途为快递费", "emp_modify_field"),
    ("本周期发票汇总", "insight_invoice_total"),
    ("今天天气怎么样", "common_help"),  # 无关问题应拒绝
    ("帮我上传一张火车票", "emp_upload_invoice"),
    ("我有哪些投标费的发票", "self_insight_category_amount"),
    ("驳回发票 462", "admin_reject"),
]

CANDIDATE_MODELS = [
    "qwen-plus",          # 当前模型
    "qwen3-max",          # 通义旗舰，0.97s 无 reasoning
    "qwen3.6-plus",       # reasoning 但慢
    "qwen3.7-max",
    "qwen3.8-max",
    "glm-5.2",
    "deepseek-v4-pro",
]

SYSTEM_PROMPT = """你是AI报销系统的意图分类器。根据用户输入判断意图，返回 JSON：{"intent": "<意图名>", "confidence": 0.0-1.0}

可选意图（员工）：
- emp_upload_invoice: 上传发票
- emp_query_invoices: 查询我的发票列表
- emp_query_my_reimbursement: 查询我的报销单
- emp_modify_field: 修改发票字段
- self_insight_category_amount: 按费用分类查询
- emp_fill_invoice_desc: 补充用途描述

可选意图（管理员）：
- admin_query_detail: 查询发票详情
- admin_approve: 审核通过
- admin_reject: 驳回
- insight_invoice_total: 团队发票汇总

无关问题返回：
- common_help: 与报销无关的问题

只返回JSON，不要其他文字。"""


async def classify(client: AsyncOpenAI, model: str, text: str) -> tuple[str, float, str, bool]:
    """调模型分类，返回 (intent, elapsed, error, has_reasoning)"""
    t0 = time.time()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        elapsed = time.time() - t0
        content = resp.choices[0].message.content or ""
        has_reasoning = "reasoning_content" in (resp.choices[0].message.model_dump() or {})
        # 提取 intent
        try:
            data = json.loads(content)
            intent = data.get("intent", "")
        except Exception:
            intent = ""
        return intent, elapsed, "", has_reasoning
    except Exception as e:
        return "", time.time() - t0, str(e)[:120], False


async def main():
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
    results = []

    print("=" * 100)
    print(f"{'模型':<20} {'输入':<32} {'时延':<8} {'命中':<6} {'reason':<6} {'错误'}")
    print("=" * 100)

    for model in CANDIDATE_MODELS:
        for text, expected in INTENT_CASES:
            intent, elapsed, err, has_rs = await classify(client, model, text)
            match = (intent == expected)
            results.append({
                "model": model, "text": text, "expected": expected,
                "actual": intent, "match": match,
                "elapsed": elapsed, "error": err, "reasoning": has_rs,
            })
            print(f"{model:<20} {text[:30]:<32} {elapsed:<8.2f} {'✓' if match else '✗':<6} {'Y' if has_rs else 'N':<6} {err[:30]}")

    print()
    print("## 汇总\n")
    print(f"| 模型 | 正确率 | 平均时延 | reasoning | 失败 |")
    print(f"|------|--------|---------|-----------|------|")
    by_model = {}
    for r in results:
        by_model.setdefault(r["model"], {"match": 0, "total": 0, "elapsed": [], "rs": False, "fail": 0})
        by_model[r["model"]]["total"] += 1
        if r["match"]:
            by_model[r["model"]]["match"] += 1
        by_model[r["model"]]["elapsed"].append(r["elapsed"])
        if r["reasoning"]:
            by_model[r["model"]]["rs"] = True
        if r["error"]:
            by_model[r["model"]]["fail"] += 1
    for model, stats in by_model.items():
        avg = sum(stats["elapsed"]) / len(stats["elapsed"])
        rate = stats["match"]/stats["total"]*100
        print(f"| {model} | {stats['match']}/{stats['total']} ({rate:.0f}%) | {avg:.2f}s | {'是' if stats['rs'] else '否'} | {stats['fail']} |")


if __name__ == "__main__":
    asyncio.run(main())
