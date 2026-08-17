"""OCR 替换可行性调研对比

同一张发票分别跑：
1. 现有 OCR 链路（RapidOCR + 正则 FieldExtractor）
2. 视觉大模型直接看图（vlt_mm_25_vis + INVOICE_JSON_SCHEMA）

对比字段提取准确率 + 时延 + 失败率。
"""

import asyncio
import json
import time
import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from app.services.ocr_service import get_ocr_service
from app.services.llm_service import get_llm_service

# 真值（手工核对的发票字段，用于评估准确率）
GROUND_TRUTH = {
    "横山桥投标报名费.pdf": {
        "invoice_number": "25322000000468589902",
        "seller_name": "常州阳宇工程管理有限公司",
        "total_with_tax": "500.00",
        "issue_date": "2025-10-10",
    },
    "顺丰电子发票.pdf": {
        "invoice_number": "25327000001649836450",
        "seller_name": "顺丰运输(常州)有限公司",
        "total_with_tax": "215.80",
        "issue_date": "2025-12-17",
    },
    "消防站投标报名费.ofd": {
        "invoice_number": "25322000000359354502",
        "seller_name": "江苏尚阳工程管理有限公司",
        "total_with_tax": "500.00",
        "issue_date": "2025-08-04",
    },
    "付款截图.jpg": {
        # 非标票据，无标准字段
        "seller_name": "江苏尚阳工程管理有限公司",
    },
}

CASES = [
    ("横山桥投标报名费.pdf", "/tmp/hsq.pdf", "application/pdf"),
    ("顺丰电子发票.pdf", "/tmp/sf.pdf", "application/pdf"),
    ("消防站投标报名费.ofd", "/tmp/xf.ofd", "application/ofd"),
    ("付款截图.jpg", "/tmp/sc.jpg", "image/jpeg"),
]


def eval_fields(extracted: dict, truth: dict) -> dict:
    """对比提取结果与真值，返回每个字段的命中情况"""
    result = {}
    for field, expected in truth.items():
        actual = (extracted or {}).get(field, "")
        # 标准化：去除空格、统一 None 为空串
        actual_norm = (str(actual) if actual else "").strip()
        expected_norm = str(expected).strip()
        result[field] = {
            "expected": expected,
            "actual": actual_norm or "(空)",
            "match": actual_norm == expected_norm,
        }
    return result


async def run_llm(name: str, path: str, mime: str) -> dict:
    """跑视觉 LLM 提取"""
    llm = get_llm_service()
    if not llm.is_available():
        return {"error": "LLM unavailable"}
    t0 = time.time()
    try:
        with open(path, "rb") as f:
            data = f.read()
        result = await llm.parse_invoice_from_image(data, mime)
        elapsed = time.time() - t0
        return {"fields": result, "elapsed_sec": round(elapsed, 2), "error": None}
    except Exception as e:
        return {"fields": {}, "elapsed_sec": round(time.time() - t0, 2), "error": str(e)}


def run_ocr(name: str, path: str, mime: str) -> dict:
    """跑 RapidOCR + 正则提取"""
    ocr = get_ocr_service()
    t0 = time.time()
    try:
        with open(path, "rb") as f:
            data = f.read()
        if mime == "application/pdf":
            result = ocr.process_pdf(data)
        elif mime == "application/ofd":
            result = ocr.process_ofd(data)
        else:
            result = ocr.process_image(data)
        elapsed = time.time() - t0
        return {"fields": result.get("extracted_fields", {}), "elapsed_sec": round(elapsed, 2),
                "confidence": result.get("confidence"), "error": None}
    except Exception as e:
        return {"fields": {}, "elapsed_sec": round(time.time() - t0, 2), "error": str(e)}


async def main():
    print("=" * 80)
    print(f"{'发票':<30} {'方法':<10} {'时延(s)':<10} {'错误':<30}")
    print("=" * 80)

    results = []
    for name, path, mime in CASES:
        truth = GROUND_TRUTH.get(name, {})

        # OCR
        ocr_out = run_ocr(name, path, mime)
        ocr_eval = eval_fields(ocr_out.get("fields", {}), truth)
        ocr_match = sum(1 for v in ocr_eval.values() if v["match"])
        ocr_total = len(ocr_eval)
        results.append({
            "name": name, "method": "RapidOCR+正则",
            "elapsed": ocr_out["elapsed_sec"], "error": ocr_out.get("error"),
            "fields_eval": ocr_eval, "match_count": ocr_match, "field_count": ocr_total,
            "raw_fields": ocr_out.get("fields", {}),
        })

        # LLM
        llm_out = await run_llm(name, path, mime)
        llm_eval = eval_fields(llm_out.get("fields", {}), truth)
        llm_match = sum(1 for v in llm_eval.values() if v["match"])
        llm_total = len(llm_eval)
        results.append({
            "name": name, "method": "视觉LLM",
            "elapsed": llm_out["elapsed_sec"], "error": llm_out.get("error"),
            "fields_eval": llm_eval, "match_count": llm_match, "field_count": llm_total,
            "raw_fields": llm_out.get("fields", {}),
        })

    # 输出表格
    print()
    print("## 详细字段对比\n")
    print(f"| 发票 | 方法 | 时延(s) | 字段命中 | 错误 |")
    print(f"|------|------|---------|---------|------|")
    for r in results:
        err = (r.get("error") or "")[:40]
        print(f"| {r['name'][:25]:<25} | {r['method']:<10} | {r['elapsed']:<8} | {r['match_count']}/{r['field_count']:<5} | {err} |")

    print()
    print("## 字段级对比（仅命中字段）\n")
    for r in results:
        print(f"### {r['name']} - {r['method']}")
        for field, ev in r["fields_eval"].items():
            mark = "✓" if ev["match"] else "✗"
            print(f"  {mark} {field}: 期望={ev['expected']!r}, 实际={ev['actual']!r}")
        # 也打印实际所有字段
        if r.get("raw_fields"):
            print(f"  完整字段: {json.dumps(r['raw_fields'], ensure_ascii=False)[:200]}")
        print()

    # 汇总
    print("## 汇总\n")
    by_method = {}
    for r in results:
        by_method.setdefault(r["method"], {"total": 0, "match": 0, "elapsed": []})
        by_method[r["method"]]["total"] += r["field_count"]
        by_method[r["method"]]["match"] += r["match_count"]
        by_method[r["method"]]["elapsed"].append(r["elapsed"])
    print(f"| 方法 | 字段命中 | 时延(平均/最大) |")
    print(f"|------|---------|-----------------|")
    for method, stats in by_method.items():
        avg = sum(stats["elapsed"]) / len(stats["elapsed"])
        mx = max(stats["elapsed"])
        rate = stats["match"]/stats["total"]*100 if stats["total"] else 0
        print(f"| {method} | {stats['match']}/{stats['total']} ({rate:.1f}%) | {avg:.2f}/{mx:.2f}s |")


if __name__ == "__main__":
    asyncio.run(main())
