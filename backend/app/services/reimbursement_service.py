"""报销单业务服务层

抽取自 routers/reimbursements.py 与 routers/portal.py 的重复逻辑：
- 创建报销单 + 关联发票
- link/unlink 发票 + 重算金额
- 上传/删除附件 + 校验文件
- 删除报销单 + 清理文件
"""

import os
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.reimbursement import (
    Reimbursement,
    ReimbursementStatus,
    ReimbursementAttachment,
)
from app.models.invoice import Invoice, InvoiceStatus, VerifyStatus, DuplicateStatus
from app.models.employee import Employee

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
    """重算并更新报销单总金额（基于当前关联发票）"""
    result = await db.execute(
        select(Invoice).where(Invoice.reimbursement_id == reimbursement_id)
    )
    total = sum(
        _parse_amount(inv.total_with_tax) for inv in result.scalars().all()
    )
    reimb = await get_reimbursement_or_404(db, reimbursement_id)
    reimb.total_amount = total
    return total


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
    total = float(reimbursement.total_amount or 0)
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
        linked += 1
        total += _parse_amount(inv.total_with_tax)

    reimbursement.total_amount = total
    await db.commit()
    return linked, total


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
    total = await recalc_total_amount(db, reimbursement_id)
    await db.commit()
    return total


async def submit_reimbursement(
    db: AsyncSession, reimbursement_id: int
) -> Reimbursement:
    """提交报销单（DRAFT → SUBMITTED）"""
    from datetime import datetime, timezone
    reimbursement = await get_reimbursement_or_404(db, reimbursement_id)
    await assert_draft(reimbursement)
    reimbursement.status = ReimbursementStatus.submitted
    reimbursement.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(reimbursement)
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
