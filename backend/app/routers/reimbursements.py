"""报销单管理路由（管理端）

业务逻辑统一委托给 services/reimbursement_service.py
"""

import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import FileResponse

from app.database import get_db
from app.models.reimbursement import Reimbursement, ReimbursementAttachment
from app.models.invoice import Invoice
from app.models.employee import Employee
from app.schemas import (
    ReimbursementCreateRequest,
    ReimbursementResponse,
    ReimbursementLinkRequest,
)
from app.services import reimbursement_service as svc

router = APIRouter()


@router.post("", response_model=ReimbursementResponse)
async def create_reimbursement(
    request: ReimbursementCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """创建报销单，可选关联发票"""
    # 自动从 Employee 表填充申请人信息（如果未手动传入）
    applicant_name = request.applicant_name
    department = request.department
    if request.applicant_id and (not applicant_name or not department):
        emp_result = await db.execute(
            select(Employee).where(
                or_(
                    Employee.wecom_user_id == request.applicant_id,
                    Employee.employee_no == request.applicant_id,
                )
            )
        )
        emp = emp_result.scalars().first()
        if emp:
            applicant_name = applicant_name or emp.name
            department = department or emp.department

    return await svc.create_reimbursement(
        db,
        applicant_id=request.applicant_id,
        applicant_name=applicant_name,
        department=department,
        period=request.period,
        reason=request.reason,
        invoice_ids=request.invoice_ids,
    )


@router.get("", response_model=list[ReimbursementResponse])
async def list_reimbursements(
    applicant_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """获取报销单列表（可按申请人筛选）"""
    query = select(Reimbursement).order_by(Reimbursement.created_at.desc())
    if applicant_id:
        query = query.where(Reimbursement.applicant_id == applicant_id)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{reimbursement_id}")
async def get_reimbursement(reimbursement_id: int, db: AsyncSession = Depends(get_db)):
    """获取报销单详情（含附件列表）"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)

    att_result = await db.execute(
        select(ReimbursementAttachment)
        .where(ReimbursementAttachment.reimbursement_id == reimbursement_id)
        .order_by(ReimbursementAttachment.created_at.desc())
    )
    attachments = list(att_result.scalars().all())

    return {
        "id": reimbursement.id,
        "applicant_id": reimbursement.applicant_id,
        "applicant_name": reimbursement.applicant_name,
        "department": reimbursement.department,
        "period": reimbursement.period,
        "reason": reimbursement.reason,
        "total_amount": reimbursement.total_amount,
        "status": reimbursement.status.value,
        "excel_path": reimbursement.excel_path,
        "pdf_path": reimbursement.pdf_path,
        "zip_path": reimbursement.zip_path,
        "created_at": reimbursement.created_at.isoformat() if reimbursement.created_at else None,
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


@router.put("/{reimbursement_id}/invoices", response_model=ReimbursementResponse)
async def link_invoices(
    reimbursement_id: int,
    request: ReimbursementLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    """关联发票到报销单"""
    await svc.link_invoices(db, reimbursement_id, request.invoice_ids)
    return await svc.get_reimbursement_or_404(db, reimbursement_id)


@router.put("/{reimbursement_id}/unlink/{invoice_id}", response_model=ReimbursementResponse)
async def unlink_invoice(
    reimbursement_id: int,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
):
    """移除报销单中的发票关联"""
    await svc.unlink_invoice(db, reimbursement_id, invoice_id)
    return await svc.get_reimbursement_or_404(db, reimbursement_id)


@router.put("/{reimbursement_id}/submit", response_model=ReimbursementResponse)
async def submit_reimbursement(reimbursement_id: int, db: AsyncSession = Depends(get_db)):
    """提交报销单（DRAFT → SUBMITTED）"""
    return await svc.submit_reimbursement(db, reimbursement_id)


@router.put("/{reimbursement_id}/withdraw", response_model=ReimbursementResponse)
async def withdraw_reimbursement(reimbursement_id: int, db: AsyncSession = Depends(get_db)):
    """撤回报销单（SUBMITTED → DRAFT）"""
    return await svc.withdraw_reimbursement(db, reimbursement_id)


@router.delete("/{reimbursement_id}")
async def delete_reimbursement(reimbursement_id: int, db: AsyncSession = Depends(get_db)):
    """删除报销单（仅草稿状态）"""
    await svc.delete_reimbursement(db, reimbursement_id)
    return {"message": f"报销单 #{reimbursement_id} 已删除", "deleted": True}


# ===== 报销单附件 =====

@router.post("/{reimbursement_id}/attachments")
async def upload_attachment(
    reimbursement_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传报销单附件"""
    file_data = await file.read()
    attachment = await svc.save_attachment(
        db,
        reimbursement_id,
        filename=file.filename or "",
        file_data=file_data,
        content_type=file.content_type,
    )
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "file_size": attachment.file_size,
        "file_type": attachment.file_type,
        "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
        "message": "附件上传成功",
    }


@router.delete("/{reimbursement_id}/attachments/{attachment_id}")
async def delete_attachment(
    reimbursement_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除报销单附件（仅草稿状态）"""
    await svc.delete_attachment(db, reimbursement_id, attachment_id)
    return {"message": "附件已删除", "deleted": True}


@router.get("/{reimbursement_id}/attachments/{attachment_id}/download")
async def download_attachment(
    reimbursement_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
):
    """下载报销单附件"""
    result = await db.execute(
        select(ReimbursementAttachment).where(
            ReimbursementAttachment.id == attachment_id
        )
    )
    attachment = result.scalars().first()
    if not attachment or attachment.reimbursement_id != reimbursement_id:
        raise HTTPException(status_code=404, detail="附件不存在")

    if not attachment.file_path or not os.path.exists(attachment.file_path):
        raise HTTPException(status_code=404, detail="附件文件不存在")

    return FileResponse(
        path=attachment.file_path,
        filename=attachment.filename,
        media_type=attachment.file_type or "application/octet-stream",
    )
