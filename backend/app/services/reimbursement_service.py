"""报销单业务服务层

抽取自 routers/reimbursements.py 与 routers/portal.py 的重复逻辑：
- 创建报销单 + 关联发票
- link/unlink 发票 + 重算金额
- 上传/删除附件 + 校验文件
- 删除报销单 + 清理文件
"""

import os
import uuid
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.reimbursement import (
    Reimbursement,
    ReimbursementStatus,
    ReimbursementAttachment,
    ReimbursementItem,
    ReimbursementDaySubsidy,
    ReimbursementTravelDay,
)
from app.models.invoice import Invoice, InvoiceStatus, VerifyStatus, DuplicateStatus
from app.models.employee import Employee
from app.services.expense_date_engine import determine_expense_date
from app.services.subsidy_engine import recompute_all, recompute_totals, load_holidays
from app.services.report_generator import ReportGenerator

# 附件限制
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTS = {
    "pdf", "jpg", "jpeg", "png", "gif", "bmp", "webp",
    "doc", "docx", "xls", "xlsx", "zip", "rar",
}


def _parse_amount(val) -> float:
    """安全解析金额为 float，失败返回 0"""
    if not val:
        return 0.0
    try:
        return float(str(val).replace(",", "").replace("￥", "").replace("¥", ""))
    except (ValueError, TypeError):
        return 0.0


async def get_reimbursement_or_404(
    db: AsyncSession, reimbursement_id: int
) -> Reimbursement:
    result = await db.execute(
        select(Reimbursement).where(Reimbursement.id == reimbursement_id)
    )
    reimbursement = result.scalars().first()
    if not reimbursement:
        raise HTTPException(status_code=404, detail="报销单不存在")
    return reimbursement


async def assert_draft(reimbursement: Reimbursement) -> None:
    """校验报销单为草稿状态，否则抛 409"""
    if reimbursement.status != ReimbursementStatus.draft:
        raise HTTPException(
            status_code=409,
            detail=f"报销单状态为「{reimbursement.status.value}」，仅草稿状态可操作。",
        )


def _assert_invoice_linkable(inv: Invoice) -> None:
    """校验发票是否可关联到报销单

    标准发票：验真通过 + 查重唯一
    非标票据：状态=已确认 + 查重唯一
    通用约束：未关联其他报销单
    """
    if inv.reimbursement_id is not None:
        raise HTTPException(
            status_code=400,
            detail=f"发票 #{inv.id} 已关联到其他报销单，无法重复关联。",
        )

    if inv.is_nonstandard:
        # 非标票据：管理员审核通过 + 查重唯一
        if inv.status != InvoiceStatus.confirmed:
            raise HTTPException(
                status_code=400,
                detail=f"非标票据 #{inv.id} 状态为「{inv.status.value}」，需管理员审核通过后才能关联报销单。",
            )
        if inv.duplicate_status != DuplicateStatus.unique:
            raise HTTPException(
                status_code=400,
                detail=f"非标票据 #{inv.id} 查重状态为「{inv.duplicate_status.value if inv.duplicate_status else '未知'}」，仅查重唯一的票据可关联报销单。",
            )
    else:
        # 标准发票：验真通过 + 查重唯一
        if inv.verify_status != VerifyStatus.valid:
            raise HTTPException(
                status_code=400,
                detail=f"发票 #{inv.id} 验真状态为「{inv.verify_status.value if inv.verify_status else '未知'}」，仅验真通过的发票可关联报销单。",
            )
        if inv.duplicate_status != DuplicateStatus.unique:
            raise HTTPException(
                status_code=400,
                detail=f"发票 #{inv.id} 查重状态为「{inv.duplicate_status.value if inv.duplicate_status else '未知'}」，仅查重唯一的发票可关联报销单。",
            )


async def recalc_total_amount(
    db: AsyncSession, reimbursement_id: int
) -> float:
    """重算并更新报销单总金额（基于明细行 + 日补贴）"""
    reimb = await get_reimbursement_or_404(db, reimbursement_id)
    cycle_year = (reimb.cycle_start or date.today()).year
    holidays = await load_holidays(db, cycle_year)
    return await recompute_all(db, reimb, holidays)


def _create_item_for_invoice(invoice: Invoice, reimbursement_id: int) -> ReimbursementItem:
    """为发票创建明细行（不 commit，调用方负责后续重算与 commit）"""
    today = date.today()
    edate, src = determine_expense_date(invoice, today)
    invoice.expense_date = edate
    invoice.expense_date_source = src

    return ReimbursementItem(
        reimbursement_id=reimbursement_id,
        invoice_id=invoice.id,
        item_date=edate,
        item_date_source=src,
        weekday=edate.weekday() if edate else None,
        fee_category=invoice.fee_category.value if invoice.fee_category else None,
        fee_subcategory=invoice.fee_subcategory,
        amount=_parse_amount(invoice.total_with_tax),
        description=invoice.user_description,
    )


async def _recompute_for_reimbursement(db: AsyncSession, reimb: Reimbursement) -> None:
    """重算报销单的补贴与总额（加载节假日 → recompute_all）"""
    cycle_year = (reimb.cycle_start or date.today()).year
    holidays = await load_holidays(db, cycle_year)
    await recompute_all(db, reimb, holidays)


async def create_reimbursement(
    db: AsyncSession,
    *,
    applicant_id: str,
    applicant_name: Optional[str] = None,
    department: Optional[str] = None,
    period: Optional[str] = None,
    reason: Optional[str] = None,
    invoice_ids: Optional[list[int]] = None,
    allowed_user_filter: Optional[str] = None,
) -> Reimbursement:
    """创建报销单，可选关联发票

    Args:
        allowed_user_filter: 若提供，仅允许关联 user_id == 此值的发票（员工端场景）
    """
    if not reason or not str(reason).strip():
        raise HTTPException(status_code=400, detail="报销事由为必填项")

    reimbursement = Reimbursement(
        applicant_id=applicant_id,
        applicant_name=applicant_name,
        department=department,
        period=period,
        reason=reason,
        status=ReimbursementStatus.draft,
    )
    db.add(reimbursement)
    await db.flush()

    total = 0.0
    if invoice_ids:
        result = await db.execute(
            select(Invoice).where(Invoice.id.in_(invoice_ids))
        )
        for inv in result.scalars().all():
            if allowed_user_filter and inv.user_id != allowed_user_filter:
                continue
            _assert_invoice_linkable(inv)
            inv.reimbursement_id = reimbursement.id
            total += _parse_amount(inv.total_with_tax)
        reimbursement.total_amount = total

    await db.commit()
    await db.refresh(reimbursement)
    return reimbursement


async def link_invoices(
    db: AsyncSession,
    reimbursement_id: int,
    invoice_ids: list[int],
    *,
    allowed_user_filter: Optional[str] = None,
) -> tuple[int, float]:
    """关联发票到报销单（仅草稿状态）

    Returns: (关联成功数量, 新总金额)
    """
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    await assert_draft(reimbursement)

    if not invoice_ids:
        raise HTTPException(status_code=400, detail="请选择至少一张发票")

    result = await db.execute(
        select(Invoice).where(Invoice.id.in_(invoice_ids))
    )

    linked = 0
    for inv in result.scalars().all():
        if allowed_user_filter and inv.user_id != allowed_user_filter:
            continue
        if inv.reimbursement_id is not None and inv.reimbursement_id != reimbursement_id:
            raise HTTPException(
                status_code=400,
                detail=f"发票 #{inv.id} 已关联到其他报销单，无法重复关联。",
            )
        if inv.reimbursement_id == reimbursement_id:
            continue
        _assert_invoice_linkable(inv)
        inv.reimbursement_id = reimbursement_id
        db.add(_create_item_for_invoice(inv, reimbursement_id))
        linked += 1

    # 重算补贴与总额
    await _recompute_for_reimbursement(db, reimbursement)
    await db.commit()
    return linked, float(reimbursement.total_amount or 0)


async def unlink_invoice(
    db: AsyncSession,
    reimbursement_id: int,
    invoice_id: int,
) -> float:
    """从报销单移除发票（仅草稿状态）"""
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    await assert_draft(reimbursement)

    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.reimbursement_id == reimbursement_id,
        )
    )
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="发票未关联到此报销单")

    invoice.reimbursement_id = None
    invoice.expense_date = None
    invoice.expense_date_source = None

    # 删除对应的明细行
    item_result = await db.execute(
        select(ReimbursementItem).where(ReimbursementItem.invoice_id == invoice_id)
    )
    for item in item_result.scalars().all():
        await db.delete(item)

    # 重算补贴与总额
    await _recompute_for_reimbursement(db, reimbursement)
    await db.commit()
    return float(reimbursement.total_amount or 0)


async def submit_reimbursement(
    db: AsyncSession, reimbursement_id: int
) -> Reimbursement:
    """提交报销单（DRAFT → SUBMITTED）

    提交后自动生成报销报表（Excel + PDF + ZIP）。
    """
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    await assert_draft(reimbursement)
    reimbursement.status = ReimbursementStatus.submitted
    reimbursement.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(reimbursement)

    # 提交后自动生成报表（失败不阻断提交主流程）
    try:
        generator = ReportGenerator(db)
        await generator.generate_all(reimbursement_id)
    except Exception:
        logger.exception(f"报销单 #{reimbursement_id} 提交后自动生成报表失败")

    return reimbursement


async def withdraw_reimbursement(
    db: AsyncSession, reimbursement_id: int
) -> Reimbursement:
    """撤回报销单（SUBMITTED → DRAFT）

    仅已提交状态可撤回，撤回后恢复为草稿可继续编辑。
    """
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.status != ReimbursementStatus.submitted:
        raise HTTPException(
            status_code=409,
            detail=f"报销单状态为「{reimbursement.status.value}」，仅已提交状态可撤回。",
        )
    reimbursement.status = ReimbursementStatus.draft
    reimbursement.submitted_at = None
    await db.commit()
    await db.refresh(reimbursement)
    return reimbursement


async def approve_reimbursement(
    db: AsyncSession, reimbursement_id: int
) -> Reimbursement:
    """审核通过报销单（SUBMITTED → REVIEWED）

    管理员审批操作：将已提交的报销单标记为已审核。
    """
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.status != ReimbursementStatus.submitted:
        raise HTTPException(
            status_code=409,
            detail=f"报销单状态为「{reimbursement.status.value}」，仅已提交状态可审核。",
        )
    reimbursement.status = ReimbursementStatus.reviewed
    reimbursement.confirmed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(reimbursement)
    return reimbursement


async def reject_reimbursement(
    db: AsyncSession, reimbursement_id: int, reason: str = ""
) -> Reimbursement:
    """驳回报销单（SUBMITTED → DRAFT）

    管理员驳回操作：将已提交的报销单退回为草稿。
    """
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.status != ReimbursementStatus.submitted:
        raise HTTPException(
            status_code=409,
            detail=f"报销单状态为「{reimbursement.status.value}」，仅已提交状态可驳回。",
        )
    reimbursement.status = ReimbursementStatus.draft
    reimbursement.submitted_at = None
    if reason:
        existing = reimbursement.reason or ""
        reimbursement.reason = f"{existing}[驳回：{reason}]".strip("[]")
    await db.commit()
    await db.refresh(reimbursement)
    return reimbursement


async def mark_reimbursed(
    db: AsyncSession, reimbursement_id: int
) -> Reimbursement:
    """标记已报销（SUBMITTED/REVIEWED → REIMBURSED）

    财务确认报销后，将已提交或已审核的报销单直接标记为已报销。
    允许跳过 REVIEWED 中间态，从 SUBMITTED 直达 REIMBURSED。
    """
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.status not in (
        ReimbursementStatus.submitted,
        ReimbursementStatus.reviewed,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"报销单状态为「{reimbursement.status.value}」，仅已提交或已审核状态可标记报销。",
        )
    reimbursement.status = ReimbursementStatus.reimbursed
    reimbursement.confirmed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(reimbursement)
    return reimbursement


# ============================================================
# 报销单详情序列化
# ============================================================

async def serialize_reimbursement_detail(
    db: AsyncSession,
    reimbursement: Reimbursement,
    include_invoices: bool = True,
) -> dict:
    """构建报销单详情响应 dict（含明细行、日补贴、附件，可选发票）"""
    # 明细行
    items_result = await db.execute(
        select(ReimbursementItem)
        .where(ReimbursementItem.reimbursement_id == reimbursement.id)
        .order_by(ReimbursementItem.sort_order, ReimbursementItem.item_date)
    )
    items = list(items_result.scalars().all())

    # 日补贴
    ds_result = await db.execute(
        select(ReimbursementDaySubsidy)
        .where(ReimbursementDaySubsidy.reimbursement_id == reimbursement.id)
        .order_by(ReimbursementDaySubsidy.subsidy_date)
    )
    day_subsidies = list(ds_result.scalars().all())

    # 出差日（员工标记的 travel_days）
    td_result = await db.execute(
        select(ReimbursementTravelDay)
        .where(ReimbursementTravelDay.reimbursement_id == reimbursement.id)
        .order_by(ReimbursementTravelDay.travel_date)
    )
    travel_days = list(td_result.scalars().all())

    # 附件
    att_result = await db.execute(
        select(ReimbursementAttachment)
        .where(ReimbursementAttachment.reimbursement_id == reimbursement.id)
        .order_by(ReimbursementAttachment.created_at.desc())
    )
    attachments = list(att_result.scalars().all())

    resp = {
        "id": reimbursement.id,
        "applicant_id": reimbursement.applicant_id,
        "applicant_name": reimbursement.applicant_name,
        "department": reimbursement.department,
        "period": reimbursement.period,
        "reason": reimbursement.reason,
        "total_amount": reimbursement.total_amount,
        "expense_total": reimbursement.expense_total,
        "subsidy_total": reimbursement.subsidy_total,
        "status": reimbursement.status.value,
        "cycle_start": reimbursement.cycle_start.isoformat() if reimbursement.cycle_start else None,
        "cycle_end": reimbursement.cycle_end.isoformat() if reimbursement.cycle_end else None,
        "cycle_key": reimbursement.cycle_key,
        "auto_generated": reimbursement.auto_generated,
        "is_cycle_locked": reimbursement.is_cycle_locked,
        "locked_at": reimbursement.locked_at.isoformat() if reimbursement.locked_at else None,
        "submitted_at": reimbursement.submitted_at.isoformat() if reimbursement.submitted_at else None,
        "confirmed_at": reimbursement.confirmed_at.isoformat() if reimbursement.confirmed_at else None,
        "excel_path": reimbursement.excel_path,
        "pdf_path": reimbursement.pdf_path,
        "zip_path": reimbursement.zip_path,
        "created_at": reimbursement.created_at.isoformat() if reimbursement.created_at else None,
        "items": [
            {
                "id": it.id,
                "invoice_id": it.invoice_id,
                "item_date": it.item_date.isoformat() if it.item_date else None,
                "item_date_source": it.item_date_source,
                "weekday": it.weekday,
                "fee_category": it.fee_category,
                "fee_subcategory": it.fee_subcategory,
                "amount": it.amount,
                "description": it.description,
                "is_late_charge": it.is_late_charge,
                "intended_cycle_key": it.intended_cycle_key,
                "sort_order": it.sort_order,
            }
            for it in items
        ],
        "day_subsidies": [
            {
                "id": ds.id,
                "subsidy_date": ds.subsidy_date.isoformat() if ds.subsidy_date else None,
                "weekday": ds.weekday,
                "day_type": ds.day_type,
                "base_rate": ds.base_rate,
                "subsidy_amount": ds.subsidy_amount,
                "included": ds.included,
                "exclude_reason": ds.exclude_reason,
                "trigger_invoice_count": ds.trigger_invoice_count,
            }
            for ds in day_subsidies
        ],
        "travel_days": [
            {
                "id": td.id,
                "reimbursement_id": td.reimbursement_id,
                "travel_date": td.travel_date.isoformat() if td.travel_date else None,
                "note": td.note,
                "weekday": td.weekday,
                "day_type": td.day_type,
                "base_rate": td.base_rate,
                "applicant_id": td.applicant_id,
            }
            for td in travel_days
        ],
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "file_size": a.file_size,
                "file_type": a.file_type,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in attachments
        ],
    }

    if include_invoices:
        inv_result = await db.execute(
            select(Invoice).where(Invoice.reimbursement_id == reimbursement.id)
        )
        invoices = list(inv_result.scalars().all())
        resp["invoices"] = [
            {
                "id": inv.id,
                "seller_name": inv.seller_name,
                "issue_date": inv.issue_date,
                "total_with_tax": inv.total_with_tax,
                "fee_category": inv.fee_category.value if inv.fee_category else None,
                "fee_subcategory": inv.fee_subcategory,
                "invoice_number": inv.invoice_number,
                "verify_status": inv.verify_status.value if inv.verify_status else None,
                "duplicate_status": inv.duplicate_status.value if inv.duplicate_status else None,
            }
            for inv in invoices
        ]

    return resp


# ============================================================
# 日补贴手动切换
# ============================================================

async def toggle_day_subsidy(
    db: AsyncSession,
    reimbursement_id: int,
    subsidy_date: date,
    *,
    included: bool,
    exclude_reason: Optional[str] = None,
) -> dict:
    """手动切换某天的补贴计入/取消

    - 仅草稿状态可操作
    - included=False 时 subsidy_amount 归零，included=True 时恢复 base_rate
    - 自动重算 subsidy_total 和 total_amount

    Returns: {subsidy_date, included, subsidy_amount, subsidy_total, total_amount}
    """
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    await assert_draft(reimbursement)

    result = await db.execute(
        select(ReimbursementDaySubsidy).where(
            ReimbursementDaySubsidy.reimbursement_id == reimbursement_id,
            ReimbursementDaySubsidy.subsidy_date == subsidy_date,
        )
    )
    ds = result.scalars().first()
    if not ds:
        raise HTTPException(status_code=404, detail=f"日期 {subsidy_date} 无补贴记录")

    ds.included = included
    ds.exclude_reason = exclude_reason if not included else None
    ds.subsidy_amount = float(ds.base_rate or 0) if included else 0.0

    # 重算总额
    await recompute_totals(db, reimbursement)
    await db.commit()

    return {
        "subsidy_date": subsidy_date.isoformat(),
        "included": included,
        "subsidy_amount": ds.subsidy_amount,
        "subsidy_total": reimbursement.subsidy_total,
        "total_amount": reimbursement.total_amount,
    }


async def save_attachment(
    db: AsyncSession,
    reimbursement_id: int,
    *,
    filename: str,
    file_data: bytes,
    content_type: Optional[str] = None,
) -> ReimbursementAttachment:
    """校验并保存附件，返回附件记录"""
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    await assert_draft(reimbursement)

    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename else ""
    if ext not in ALLOWED_ATTACHMENT_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 .{ext}，允许的格式：{', '.join(sorted(ALLOWED_ATTACHMENT_EXTS))}",
        )

    if len(file_data) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过 20MB")

    att_dir = os.path.join(settings.upload_dir, "attachments")
    os.makedirs(att_dir, exist_ok=True)
    stored_name = f"{reimbursement_id}_{uuid.uuid4().hex[:12]}.{ext}"
    file_path = os.path.join(att_dir, stored_name)
    with open(file_path, "wb") as f:
        f.write(file_data)

    attachment = ReimbursementAttachment(
        reimbursement_id=reimbursement_id,
        filename=filename or stored_name,
        file_path=file_path,
        file_size=len(file_data),
        file_type=content_type or ext,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return attachment


async def delete_attachment(
    db: AsyncSession,
    reimbursement_id: int,
    attachment_id: int,
) -> None:
    """删除附件物理文件 + 记录（仅草稿状态）"""
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    await assert_draft(reimbursement)

    result = await db.execute(
        select(ReimbursementAttachment).where(
            ReimbursementAttachment.id == attachment_id
        )
    )
    attachment = result.scalars().first()
    if not attachment or attachment.reimbursement_id != reimbursement_id:
        raise HTTPException(status_code=404, detail="附件不存在")

    if attachment.file_path and os.path.exists(attachment.file_path):
        try:
            os.remove(attachment.file_path)
        except OSError:
            pass

    await db.delete(attachment)
    await db.commit()


async def delete_reimbursement(
    db: AsyncSession, reimbursement_id: int
) -> None:
    """删除报销单（仅草稿状态）

    - 解除关联发票（发票不删）
    - 删除附件文件 + 记录
    - 删除已生成的报表文件（excel/pdf/zip）
    """
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    await assert_draft(reimbursement)

    # 解除关联发票
    inv_result = await db.execute(
        select(Invoice).where(Invoice.reimbursement_id == reimbursement_id)
    )
    for inv in inv_result.scalars().all():
        inv.reimbursement_id = None
        inv.expense_date = None
        inv.expense_date_source = None

    # 删除附件
    att_result = await db.execute(
        select(ReimbursementAttachment).where(
            ReimbursementAttachment.reimbursement_id == reimbursement_id
        )
    )
    for att in att_result.scalars().all():
        if att.file_path and os.path.exists(att.file_path):
            try:
                os.remove(att.file_path)
            except OSError:
                pass
        await db.delete(att)

    # 删除报表文件
    for path_attr in ("excel_path", "pdf_path", "zip_path"):
        path = getattr(reimbursement, path_attr, None)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    await db.delete(reimbursement)
    await db.commit()
