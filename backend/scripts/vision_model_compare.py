"""视觉模型候选对比测试

跑 4 个候选视觉模型 × 4 张测试发票，对比字段命中率和时延。
"""

import asyncio
import base64
import json
import time
import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from openai import AsyncOpenAI
from app.prompts.invoice_prompts import INVOICE_VISION_SYSTEM_PROMPT, INVOICE_VISION_PROMPT, INVOICE_JSON_SCHEMA
from app.config import settings

API_KEY = settings.llm_api_key
BASE_URL = settings.llm_base_url

# 候选视觉模型
CANDIDATES = [
    "vlt_mm_25_vis",       # 当前模型（基线）
    "vlt_mm_25_ultra",
    "vlt_mm_30_visultra",
    "vlt_mm_31_vis",
    "vlt_mm_31_ultra",
    "orb_base_02_vis",
]

# 测试发票 + 真值（仅 PDF + 图片，去掉 OFD）
CASES = [
    ("顺丰电子发票.pdf", "/tmp/test_sf.pdf", "application/pdf", {
        "invoice_number": "25327000001649836450",
        "seller_name": "顺丰运输(常州)有限公司",
        "total_with_tax": "215.80",
        "issue_date": "2025-12-17",
    }),
    ("消防站投标报名费.pdf", "/tmp/test_xf.pdf", "application/pdf", {
        "invoice_number": "25322000000359354502",
        "seller_name": "江苏尚阳工程管理有限公司",
        "total_with_tax": "500.00",
        "issue_date": "2025-08-04",
    }),
    # 付款截图：非标票据，期望 LLM 能识别销方 + 金额（无发票号/日期/总金额）
    ("付款截图.jpg", "/tmp/test_sc.jpg", "image/jpeg", {
        "seller_name": "江苏尚阳工程管理有限公司",
    }),
    # token充值收据：非标票据，期望 LLM 能识别销方 + 金额
    ("token充值收据.jpg", "/tmp/test_token.jpg", "image/jpeg", {
        # 真值待 LLM 输出后人工确认（先留空，验证至少能提取到 seller_name）
    }),
]


def convert_to_image(path: str, mime: str) -> tuple[bytes, str]:
    """PDF/OFD 转图片字节"""
    with open(path, "rb") as f:
        data = f.read()
    if mime == "application/pdf":
        from pdf2image import convert_from_bytes
        from io import BytesIO
        images = convert_from_bytes(data, dpi=300, first_page=1, last_page=1)
        if images:
            buf = BytesIO()
            images[0].save(buf, format="PNG")
            return buf.getvalue(), "image/png"
    elif mime == "application/ofd":
        from app.services.ofd_parser import get_ofd_parser
        parsed = get_ofd_parser().parse(data)
        img_bytes = parsed.get("image_bytes")
        if img_bytes:
            return img_bytes, "image/png"
    else:
        return data, mime
    return data, mime


async def call_vision(client: AsyncOpenAI, model: str, image_bytes: bytes, mime: str) -> tuple[dict, float, str]:
    """调用视觉模型提取发票字段"""
    b64 = base64.b64encode(image_bytes).decode()
    t0 = time.time()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": INVOICE_VISION_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": INVOICE_VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
                ]}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "invoice_fields",
                    "schema": INVOICE_JSON_SCHEMA,
                    "strict": False,
                },
            },
            temperature=0.1,
            max_tokens=2000,
        )
        elapsed = time.time() - t0
        content = resp.choices[0].message.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        result = json.loads(content)
        return result, elapsed, ""
    except Exception as e:
        return {}, time.time() - t0, str(e)[:120]


def eval_fields(extracted: dict, truth: dict) -> tuple[int, int, list]:
    match_count = 0
    details = []
    for field, expected in truth.items():
        actual = (extracted or {}).get(field, "")
        actual_norm = (str(actual) if actual else "").strip()
        expected_norm = str(expected).strip()
        match = actual_norm == expected_norm
        if match:
            match_count += 1
        details.append((field, expected, actual_norm or "(空)", match))
    return match_count, len(truth), details


async def main():
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
    results = []

    print("=" * 90)
    print(f"{'模型':<22} {'发票':<26} {'时延(s)':<10} {'命中':<8} {'错误'}")
    print("=" * 90)

    for model in CANDIDATES:
        for name, path, mime, truth in CASES:
            try:
                img_bytes, img_mime = convert_to_image(path, mime)
                fields, elapsed, err = await call_vision(client, model, img_bytes, img_mime)
                mc, tc, _ = eval_fields(fields, truth)
                results.append({"model": model, "case": name, "elapsed": elapsed,
                                "match": mc, "total": tc, "error": err, "fields": fields})
                print(f"{model:<22} {name[:25]:<26} {elapsed:<10.2f} {mc}/{tc:<6} {err[:40]}")
            except Exception as e:
                results.append({"model": model, "case": name, "elapsed": 0,
                                "match": 0, "total": len(truth), "error": str(e)[:120], "fields": {}})
                print(f"{model:<22} {name[:25]:<26} {'FAIL':<10} 0/{len(truth)} {str(e)[:40]}")

    # 汇总
    print()
    print("## 汇总\n")
    print(f"| 模型 | 字段命中 | 平均时延 | 最大时延 | 失败数 |")
    print(f"|------|---------|---------|---------|-------|")
    by_model = {}
    for r in results:
        by_model.setdefault(r["model"], {"match": 0, "total": 0, "elapsed": [], "fail": 0})
        by_model[r["model"]]["match"] += r["match"]
        by_model[r["model"]]["total"] += r["total"]
        if r["error"]:
            by_model[r["model"]]["fail"] += 1
        else:
            by_model[r["model"]]["elapsed"].append(r["elapsed"])

    for model, stats in by_model.items():
        avg = sum(stats["elapsed"]) / max(len(stats["elapsed"]), 1)
        mx = max(stats["elapsed"]) if stats["elapsed"] else 0
        rate = stats["match"]/stats["total"]*100 if stats["total"] else 0
        print(f"| {model} | {stats['match']}/{stats['total']} ({rate:.1f}%) | {avg:.2f}s | {mx:.2f}s | {stats['fail']} |")


if __name__ == "__main__":
    asyncio.run(main())
