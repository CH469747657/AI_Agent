"""vlt_mm_31_vis 视觉模型 vs RapidOCR 实测对比（含图片样本）

样本：uploads/*.pdf 去重 + /tmp/*.png/jpg 外部样本
"""

import asyncio
import base64
import json
import os
import sys
import time
import hashlib
import logging
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from openai import AsyncOpenAI
from app.config import settings
from app.services.ocr_service import get_ocr_service
from app.services.llm_service import get_llm_service
from app.prompts.invoice_prompts import (
    INVOICE_VISION_SYSTEM_PROMPT,
    INVOICE_VISION_PROMPT,
    INVOICE_JSON_SCHEMA,
)

UPLOAD_DIR = Path(settings.upload_dir)
TARGET_FIELDS = [
    "invoice_number", "issue_date", "seller_name", "seller_tax_id",
    "buyer_name", "buyer_tax_id", "total_with_tax", "amount",
    "tax_amount", "tax_rate", "invoice_code",
]

# 外部图片样本（支付截图 / 发票截图 / 非标票据）
EXTERNAL_IMAGES = [
    "/tmp/test_payment.png",
    "/tmp/顺丰.png",
    "/tmp/培训费_v2.png",
    "/tmp/消防站_v2.png",
]


def pick_unique_pdfs(limit: int = 4) -> list[Path]:
    seen = {}
    for p in sorted(UPLOAD_DIR.glob("*.pdf")):
        h = hashlib.md5(p.read_bytes()).hexdigest()
        if h not in seen:
            seen[h] = p
        if len(seen) >= limit:
            break
    return list(seen.values())


def run_ocr_pdf(pdf_path: Path) -> dict:
    ocr = get_ocr_service()
    t0 = time.time()
    try:
        result = ocr.process_pdf(pdf_path.read_bytes())
        return {
            "fields": result.get("extracted_fields", {}),
            "elapsed": time.time() - t0,
            "confidence": result.get("confidence"),
            "raw_text": (result.get("raw_text") or "")[:300],
            "error": None,
        }
    except Exception as e:
        return {"fields": {}, "elapsed": time.time() - t0, "confidence": None,
                "raw_text": "", "error": str(e)[:200]}


def run_ocr_image(img_path: Path) -> dict:
    ocr = get_ocr_service()
    t0 = time.time()
    try:
        result = ocr.process_image(img_path.read_bytes())
        return {
            "fields": result.get("extracted_fields", {}),
            "elapsed": time.time() - t0,
            "confidence": result.get("confidence"),
            "raw_text": (result.get("raw_text") or "")[:300],
            "error": None,
        }
    except Exception as e:
        return {"fields": {}, "elapsed": time.time() - t0, "confidence": None,
                "raw_text": "", "error": str(e)[:200]}


def render_pdf_to_png(pdf_path: Path) -> bytes:
    from pdf2image import convert_from_bytes
    images = convert_from_bytes(pdf_path.read_bytes(), dpi=300, first_page=1, last_page=1)
    buf = BytesIO()
    images[0].save(buf, format="PNG")
    return buf.getvalue()


async def run_llm(client: AsyncOpenAI, image_bytes: bytes, mime: str = "image/png") -> dict:
    t0 = time.time()
    try:
        b64 = base64.b64encode(image_bytes).decode()
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": INVOICE_VISION_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": INVOICE_VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]},
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
            timeout=60.0,
        )
        content = resp.choices[0].message.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return {
            "fields": json.loads(content),
            "elapsed": time.time() - t0,
            "error": None,
        }
    except Exception as e:
        return {"fields": {}, "elapsed": time.time() - t0, "error": str(e)[:200]}


def compare_fields(ocr_f: dict, llm_f: dict) -> dict:
    rows = []
    agree = 0
    non_empty = 0
    for f in TARGET_FIELDS:
        o = str(ocr_f.get(f) or "").strip()
        l = str(llm_f.get(f) or "").strip()
        if o or l:
            non_empty += 1
        match = bool(o) and bool(l) and o == l
        if match:
            agree += 1
        rows.append({
            "field": f,
            "ocr": o or "(空)",
            "llm": l or "(空)",
            "match": match,
            "ocr_only": bool(o) and not l,
            "llm_only": bool(l) and not o,
        })
    return {
        "rows": rows,
        "agree": agree,
        "non_empty": non_empty,
        "agreement_rate": agree / non_empty if non_empty else 0,
    }


async def main():
    samples_pdf = pick_unique_pdfs(limit=4)
    samples_img = [Path(p) for p in EXTERNAL_IMAGES if Path(p).exists()]

    print(f"模型: vision={settings.llm_model} text={settings.llm_text_model} base_url={settings.llm_base_url}")
    print(f"PDF 样本数: {len(samples_pdf)}  图片样本数: {len(samples_img)}")
    print("=" * 110)

    client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    all_results = []

    # PDF 测试
    for i, pdf in enumerate(samples_pdf, 1):
        print(f"\n[PDF {i}/{len(samples_pdf)}] {pdf.name} ({pdf.stat().st_size} B)")
        print("-" * 110)

        ocr_out = run_ocr_pdf(pdf)
        png = render_pdf_to_png(pdf)
        llm_out = await run_llm(client, png)

        print(f"  OCR  : elapsed={ocr_out['elapsed']:.2f}s  err={ocr_out['error'] or '无'}  conf={ocr_out['confidence']}")
        print(f"  LLM  : elapsed={llm_out['elapsed']:.2f}s  err={llm_out['error'] or '无'}")

        cmp = compare_fields(ocr_out["fields"], llm_out["fields"])
        print(f"  一致率: {cmp['agree']}/{cmp['non_empty']} = {cmp['agreement_rate']:.1%}")

        print(f"  {'字段':<22} {'OCR':<32} {'LLM':<32} {'一致'}")
        for r in cmp["rows"]:
            if r["ocr"] == "(空)" and r["llm"] == "(空)":
                continue
            mark = "✓" if r["match"] else ("O" if r["ocr_only"] else ("L" if r["llm_only"] else "✗"))
            o_short = r["ocr"][:30]
            l_short = r["llm"][:30]
            print(f"  {r['field']:<22} {o_short:<32} {l_short:<32} {mark}")

        all_results.append({
            "kind": "PDF",
            "file": pdf.name,
            "ocr_elapsed": ocr_out["elapsed"],
            "llm_elapsed": llm_out["elapsed"],
            "ocr_error": ocr_out["error"],
            "llm_error": llm_out["error"],
            "ocr_fields_n": sum(1 for v in ocr_out["fields"].values() if v),
            "llm_fields_n": sum(1 for v in llm_out["fields"].values() if v),
            "agreement": cmp["agreement_rate"],
            "ocr_raw_text": ocr_out["raw_text"],
            "llm_fields": llm_out["fields"],
            "ocr_fields": ocr_out["fields"],
        })

    # 图片测试
    for i, img in enumerate(samples_img, 1):
        print(f"\n[IMG {i}/{len(samples_img)}] {img.name} ({img.stat().st_size} B)")
        print("-" * 110)

        ocr_out = run_ocr_image(img)
        llm_out = await run_llm(client, img.read_bytes())

        print(f"  OCR  : elapsed={ocr_out['elapsed']:.2f}s  err={ocr_out['error'] or '无'}  conf={ocr_out['confidence']}")
        print(f"  LLM  : elapsed={llm_out['elapsed']:.2f}s  err={llm_out['error'] or '无'}")
        print(f"  OCR raw_text: {ocr_out['raw_text'][:120]}")
        print(f"  LLM fields : {json.dumps({k:v for k,v in llm_out.get('fields',{}).items() if v}, ensure_ascii=False)[:200]}")

        all_results.append({
            "kind": "IMG",
            "file": img.name,
            "ocr_elapsed": ocr_out["elapsed"],
            "llm_elapsed": llm_out["elapsed"],
            "ocr_error": ocr_out["error"],
            "llm_error": llm_out["error"],
            "ocr_fields_n": sum(1 for v in ocr_out["fields"].values() if v),
            "llm_fields_n": sum(1 for v in llm_out["fields"].values() if v),
            "agreement": 0,  # 非标样本不评一致率
            "ocr_raw_text": ocr_out["raw_text"],
            "llm_fields": llm_out.get("fields", {}),
            "ocr_fields": ocr_out["fields"],
        })

    # 汇总
    print("\n" + "=" * 110)
    print("## 汇总\n")
    print(f"| 类型 | 文件 | OCR 时延 | LLM 时延 | OCR 字段数 | LLM 字段数 | 一致率 |")
    print(f"|------|------|---------|---------|-----------|-----------|-------|")
    for r in all_results:
        print(f"| {r['kind']} | {r['file'][:25]:<25} | {r['ocr_elapsed']:.2f}s | {r['llm_elapsed']:.2f}s | {r['ocr_fields_n']} | {r['llm_fields_n']} | {r['agreement']:.0%} |")

    pdf_results = [r for r in all_results if r["kind"] == "PDF"]
    img_results = [r for r in all_results if r["kind"] == "IMG"]
    if pdf_results:
        ocr_t = [r["ocr_elapsed"] for r in pdf_results]
        llm_t = [r["llm_elapsed"] for r in pdf_results]
        print(f"\nPDF: OCR 平均时延={sum(ocr_t)/len(ocr_t):.2f}s  LLM 平均时延={sum(llm_t)/len(llm_t):.2f}s")
    if img_results:
        ocr_t = [r["ocr_elapsed"] for r in img_results]
        llm_t = [r["llm_elapsed"] for r in img_results]
        print(f"IMG: OCR 平均时延={sum(ocr_t)/len(ocr_t):.2f}s  LLM 平均时延={sum(llm_t)/len(llm_t):.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
