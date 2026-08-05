"""企业微信交互路由（后端侧API）"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.invoice import Invoice, InvoiceStatus

router = APIRouter()


@router.get("/invoices/{user_id}")
async def get_user_invoices_summary(user_id: str, db: AsyncSession = Depends(get_db)):
    """获取用户发票摘要（用于企微消息展示）"""
    result = await db.execute(
        select(Invoice)
        .where(Invoice.user_id == user_id)
        .order_by(Invoice.created_at.desc())
    )
    invoices = list(result.scalars().all())

    if not invoices:
        return {"count": 0, "total_amount": 0, "items": []}

    total = sum(float(i.total_with_tax) for i in invoices if i.total_with_tax)
    return {
        "count": len(invoices),
        "total_amount": round(total, 2),
        "items": [
            {
                "id": i.id,
                "status": i.status.value,
                "category": i.fee_subcategory,
                "amount": i.total_with_tax,
                "seller": i.seller_name,
                "date": i.issue_date,
                "is_duplicate": i.duplicate_status.value == "DUPLICATE",
            }
            for i in invoices
        ],
    }


@router.post("/invoices/{invoice_id}/confirm")
async def confirm_invoice(invoice_id: int, db: AsyncSession = Depends(get_db)):
    """用户确认发票分类（企微交互）"""
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice.status = InvoiceStatus.confirmed
    await db.commit()
    return {"status": "ok", "message": "发票已确认"}


@router.get("/invoices/{invoice_id}/detail")
async def get_invoice_detail_for_wecom(invoice_id: int, db: AsyncSession = Depends(get_db)):
    """获取发票详情（用于企微消息卡片展示）"""
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "issue_date": invoice.issue_date,
        "seller_name": invoice.seller_name,
        "total_with_tax": invoice.total_with_tax,
        "fee_category": invoice.fee_category.value if invoice.fee_category else None,
        "fee_subcategory": invoice.fee_subcategory,
        "project_id": invoice.project_id,
        "diff_confidence": invoice.diff_confidence,
        "has_conflicts": bool(invoice.diff_conflicts),
        "verify_status": invoice.verify_status.value,
        "duplicate_status": invoice.duplicate_status.value,
        "status": invoice.status.value,
    }
