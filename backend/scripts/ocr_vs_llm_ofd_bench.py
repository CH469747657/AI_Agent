"""OFD 样本：OCR (ofd_parser 矢量文字) vs LLM Vision 双源对比"""

import asyncio
import base64
import json
import sys
import time
import logging
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from openai import AsyncOpenAI
from app.config import settings
from app.services.ocr_service import get_ocr_service
from app.prompts.invoice_prompts import (
    INVOICE_VISION_SYSTEM_PROMPT,
    INVOICE_VISION_PROMPT,
    INVOICE_JSON_SCHEMA,
)

OFD_SAMPLES = [
    "/tmp/sf.ofd",
    "/tmp/xf.ofd",
    "/tmp/住宿费.ofd",
]

TARGET_FIELDS = [
    "invoice_number", "issue_date", "seller_name", "seller_tax_id",
    "buyer_name", "buyer_tax_id", "total_with_tax", "amount",
    "tax_amount", "tax_rate", "invoice_code",
]


def run_ocr_ofd(ofd_path: Path) -> dict:
    ocr = get_ocr_service()
    t0 = time.time()
    try:
        result = ocr.process_ofd(ofd_path.read_bytes())
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


async def run_llm_ofd(client: AsyncOpenAI, ofd_path: Path) -> dict:
    """OFD：先看 ofd_parser 是否有结构化字段（有则跳过 Vision），否则回落内嵌图片"""
    from app.services.ofd_parser import get_ofd_parser
    t0 = time.time()
    try:
        parsed = get_ofd_parser().parse(ofd_path.read_bytes())
        fields = parsed.get("fields", {})
        if any(v for v in fields.values()):
            # ofd_parser 已结构化 → 跳过 LLM Vision（项目当前逻辑）
            return {
                "fields": {k: v for k, v in fields.items() if k != "check_code"},
                "elapsed": time.time() - t0,
                "error": None,
                "source": "ofd_parser",
            }
        # 无结构化字段 → 走内嵌图片 LLM Vision
        img_bytes = parsed.get("image_bytes")
        if not img_bytes:
            return {"fields": {}, "elapsed": time.time() - t0,
                    "error": "OFD 无结构化字段也无内嵌图片", "source": "none"}
        b64 = base64.b64encode(img_bytes).decode()
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": INVOICE_VISION_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": INVOICE_VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
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
            "source": "llm_vision",
        }
    except Exception as e:
        return {"fields": {}, "elapsed": time.time() - t0, "error": str(e)[:200],
                "source": "error"}


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
        rows.append({"field": f, "ocr": o or "(空)", "llm": l or "(空)", "match": match})
    return {"rows": rows, "agree": agree, "non_empty": non_empty,
            "agreement_rate": agree / non_empty if non_empty else 0}


async def main():
    samples = [Path(p) for p in OFD_SAMPLES if Path(p).exists()]
    print(f"模型: vision={settings.llm_model}  base_url={settings.llm_base_url}")
    print(f"OFD 样本数: {len(samples)}")
    print("=" * 110)

    client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

    for i, ofd in enumerate(samples, 1):
        print(f"\n[OFD {i}/{len(samples)}] {ofd.name} ({ofd.stat().st_size} B)")
        print("-" * 110)

        ocr_out = run_ocr_ofd(ofd)
        llm_out = await run_llm_ofd(client, ofd)

        print(f"  OCR  : elapsed={ocr_out['elapsed']:.2f}s  err={ocr_out['error'] or '无'}  conf={ocr_out['confidence']}")
        print(f"  LLM  : elapsed={llm_out['elapsed']:.2f}s  err={llm_out['error'] or '无'}  source={llm_out.get('source')}")

        cmp = compare_fields(ocr_out["fields"], llm_out["fields"])
        print(f"  一致率: {cmp['agree']}/{cmp['non_empty']} = {cmp['agreement_rate']:.1%}")

        print(f"  {'字段':<22} {'OCR':<32} {'LLM':<32} {'一致'}")
        for r in cmp["rows"]:
            if r["ocr"] == "(空)" and r["llm"] == "(空)":
                continue
            mark = "✓" if r["match"] else "✗"
            print(f"  {r['field']:<22} {r['ocr'][:30]:<32} {r['llm'][:30]:<32} {mark}")


if __name__ == "__main__":
    asyncio.run(main())
