"""端到端测试：上传 4 张发票串联流程

用法：
    docker cp 本文件进容器后执行：
    docker exec ai-reimbursement-agent-backend-1 python /app/scripts/e2e_test.py
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select
from app.database import get_async_sessionmaker
from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice_service import InvoiceService

USER_ID = "EMP001"  # 陈辉

# 4 张 PDF 发票，全部强制塞进当前周期 2026-08（7/21–8/20）通过备注日期
INVOICES = [
    {
        "name": "横山桥投标报名费",
        "path": "/app/test_invoices/横山桥投标报名费.pdf",
        "ext": "pdf",
        "receipt_type": "",
        "user_description": "8月3日，横山桥项目投标报名费",
    },
    {
        "name": "顺丰电子发票",
        "path": "/app/test_invoices/顺丰电子发票.pdf",
        "ext": "pdf",
        "receipt_type": "",
        "user_description": "8月5日，快递邮寄费",
    },
    {
        "name": "消防站投标报名费",
        "path": "/app/test_invoices/消防站投标报名费.pdf",
        "ext": "pdf",
        "receipt_type": "",
        "user_description": "8月10日，消防站项目投标报名费",
    },
    {
        "name": "新南村报名费",
        "path": "/app/test_invoices/新南村报名费.pdf",
        "ext": "pdf",
        "receipt_type": "",
        "user_description": "8月15日，新南村项目报名费",
    },
]


async def main():
    sm = get_async_sessionmaker()
    async with sm() as db:
        service = InvoiceService(db)
        for inv_def in INVOICES:
            path = inv_def["path"]
            if not Path(path).exists():
                print(f"  [MISS] 文件不存在: {path}")
                continue

            with open(path, "rb") as f:
                file_data = f.read()

            print(f"  [UP] {inv_def['name']} ({len(file_data)} bytes, type={inv_def['ext']})")
            try:
                invoice = await service.process_upload(
                    file_data=file_data,
                    file_type=inv_def["ext"],
                    receipt_type=inv_def["receipt_type"],
                    user_id=USER_ID,
                    user_description=inv_def["user_description"],
                )
                print(
                    f"  [OK] invoice #{invoice.id}: "
                    f"receipt_type={invoice.receipt_type.value if invoice.receipt_type else None}, "
                    f"seller={invoice.seller_name}, "
                    f"amount={invoice.total_with_tax}, "
                    f"expense_date={invoice.expense_date} (src={invoice.expense_date_source}), "
                    f"verify_status={invoice.verify_status.value if invoice.verify_status else None}, "
                    f"duplicate_status={invoice.duplicate_status.value if invoice.duplicate_status else None}, "
                    f"status={invoice.status.value}, "
                    f"fee_subcategory={invoice.fee_subcategory}"
                )
            except Exception as e:
                import traceback
                print(f"  [FAIL] {inv_def['name']}: {e}")
                traceback.print_exc()
            print()

        # 汇总
        result = await db.execute(
            select(Invoice).where(Invoice.user_id == USER_ID).order_by(Invoice.id)
        )
        invoices = list(result.scalars().all())
        print(f"=== 汇总：EMP001 共 {len(invoices)} 张发票 ===")
        for inv in invoices:
            print(
                f"  #{inv.id}: type={inv.receipt_type.value if inv.receipt_type else None}, "
                f"seller={inv.seller_name}, "
                f"amount={inv.total_with_tax}, "
                f"expense_date={inv.expense_date} (src={inv.expense_date_source}), "
                f"verify={inv.verify_status.value if inv.verify_status else None}, "
                f"dup={inv.duplicate_status.value if inv.duplicate_status else None}, "
                f"status={inv.status.value}, "
                f"fee_subcategory={inv.fee_subcategory}"
            )


if __name__ == "__main__":
    asyncio.run(main())
