"""员工端业务路由

所有接口需 JWT 鉴权，数据自动隔离为当前员工。
报销单业务逻辑委托给 services/reimbursement_service.py。
"""

import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import FileResponse

from app.database import get_db
from app.models.invoice import Invoice, InvoiceStatus
from app.models.reimbursement import Reimbursement, ReimbursementStatus, ReimbursementAttachment
from app.models.employee import Employee
from app.routers.portal_auth import get_current_employee_async
from app.services import reimbursement_service as svc
from app.services.invoice_service import InvoiceService
from app.schemas import InvoiceResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 我的发票 =====

@router.post("/invoices/upload", response_model=InvoiceResponse)
async def portal_upload_invoice(
    file: UploadFile = File(...),
    receipt_type: str = Form("增值税普通发票"),
    user_description: str = Form("", min_length=0),
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """员工端上传发票（JWT 鉴权，user_id 从 token 推导）

    - 不接受客户端传入 user_id，服务端从 JWT token 获取 employee_no
    - 调用与管理端相同的 InvoiceService.process_upload 处理链路
    """
    file_data = await file.read()
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "jpg"

    ALLOWED_EXTS = {"pdf", "ofd", "jpg", "jpeg", "png", "gif", "bmp", "webp"}
    if file_ext not in ALLOWED_EXTS:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 .{file_ext}，允许：{', '.join(sorted(ALLOWED_EXTS))}",
        )

    service = InvoiceService(db)
    invoice = await service.process_upload(
        file_data=file_data,
        file_type=file_ext,
        receipt_type=receipt_type,
        user_id=employee.employee_no,
        user_description=user_description,
    )
    return invoice


@router.get("/invoices")
async def list_my_invoices(
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """获取我的发票列表（字段过滤，不泄漏 file_path 等内部字段）"""
    result = await db.execute(
        select(Invoice)
        .where(Invoice.user_id == employee.employee_no)
        .order_by(Invoice.created_at.desc())
    )
    invoices = list(result.scalars().all())
    return [InvoiceResponse.model_validate(inv).model_dump() for inv in invoices]


@router.get("/invoices/{invoice_id}")
async def get_my_invoice(
    invoice_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """获取发票详情（校验归属，字段过滤）"""
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")
    if invoice.user_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权查看该发票")
    return InvoiceResponse.model_validate(invoice).model_dump()


@router.get("/invoices/{invoice_id}/file")
async def download_my_invoice_file(
    invoice_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """下载发票原始文件（仅限自己上传的发票）"""
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")
    if invoice.user_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该发票")

    if not invoice.file_path or not os.path.exists(invoice.file_path):
        raise HTTPException(status_code=404, detail="原始文件不存在")

    ext = os.path.splitext(invoice.file_path)[1]
    return FileResponse(
        invoice.file_path,
        filename=f"发票_{invoice.invoice_number or invoice_id}{ext}",
        media_type="application/octet-stream",
    )


@router.delete("/invoices/{invoice_id}")
async def delete_my_invoice(
    invoice_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """删除发票及其关联的 OCR/LLM 结果（校验归属）

    - 校验发票归属于当前员工
    - 关联了报销单的发票不允许删除（返回 409）
    - 同步删除 OCR/LLM 结果和原始文件
    """
    from app.models.invoice import OcrResult, LlmResult

    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")
    if invoice.user_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该发票")

    # 检查是否关联了报销单
    if invoice.reimbursement_id is not None:
        raise HTTPException(
            status_code=409,
            detail="该发票已关联报销单，无法删除。请先从报销单中移除。",
        )

    # 删除关联的 OCR/LLM 结果
    ocr_results = await db.execute(select(OcrResult).where(OcrResult.invoice_id == invoice_id))
    for ocr in ocr_results.scalars().all():
        await db.delete(ocr)

    llm_results = await db.execute(select(LlmResult).where(LlmResult.invoice_id == invoice_id))
    for llm in llm_results.scalars().all():
        await db.delete(llm)

    # 删除原始文件
    if invoice.file_path and os.path.exists(invoice.file_path):
        try:
            os.remove(invoice.file_path)
        except OSError:
            pass  # 文件删除失败不阻塞

    await db.delete(invoice)
    await db.commit()
    return {"message": f"发票 #{invoice_id} 已删除", "deleted": True}


# ===== 我的报销单 =====

@router.get("/reimbursements")
async def list_my_reimbursements(
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """获取我的报销单列表"""
    result = await db.execute(
        select(Reimbursement)
        .where(Reimbursement.applicant_id == employee.employee_no)
        .order_by(Reimbursement.created_at.desc())
    )
    reimbursements = list(result.scalars().all())

    # 为每个报销单附加关联发票数量
    resp = []
    for r in reimbursements:
        inv_result = await db.execute(
            select(func.count()).select_from(Invoice).where(Invoice.reimbursement_id == r.id)
        )
        inv_count = inv_result.scalar() or 0
        resp.append({
            "id": r.id,
            "applicant_id": r.applicant_id,
            "applicant_name": r.applicant_name,
            "department": r.department,
            "period": r.period,
            "reason": r.reason,
            "total_amount": r.total_amount,
            "status": r.status.value,
            "invoice_count": inv_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return resp


@router.get("/reimbursements/{reimbursement_id}")
async def get_my_reimbursement(
    reimbursement_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """获取报销单详情"""
    result = await db.execute(
        select(Reimbursement).where(Reimbursement.id == reimbursement_id)
    )
    reimbursement = result.scalars().first()
    if not reimbursement:
        raise HTTPException(status_code=404, detail="报销单不存在")
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权查看该报销单")

    # 附加关联发票
    inv_result = await db.execute(
        select(Invoice).where(Invoice.reimbursement_id == reimbursement_id)
    )
    invoices = list(inv_result.scalars().all())

    # 附加附件列表
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
        "invoices": [
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


@router.post("/reimbursements")
async def create_my_reimbursement(
    body: dict,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """创建报销单 — 自动填充申请人信息

    - reason 报销事由为必填项
    - period 报销期间可选
    - invoice_ids 可关联已有发票
    """
    invoice_ids = body.get("invoice_ids", [])
    reason = body.get("reason")
    period = body.get("period")

    reimbursement = await svc.create_reimbursement(
        db,
        applicant_id=employee.employee_no,
        applicant_name=employee.name,
        department=employee.department,
        period=period,
        reason=reason,
        invoice_ids=invoice_ids,
        allowed_user_filter=employee.employee_no,
    )

    return {
        "id": reimbursement.id,
        "status": reimbursement.status.value,
        "total_amount": reimbursement.total_amount,
        "message": "报销单创建成功",
    }


@router.put("/reimbursements/{reimbursement_id}")
async def update_my_reimbursement(
    reimbursement_id: int,
    body: dict,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """编辑报销单（仅草稿状态可编辑）

    可编辑字段: reason, period
    """
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")
    await svc.assert_draft(reimbursement)

    if "reason" in body:
        new_reason = body["reason"]
        if not new_reason or not str(new_reason).strip():
            raise HTTPException(status_code=400, detail="报销事由不能为空")
        reimbursement.reason = str(new_reason).strip()
    if "period" in body:
        reimbursement.period = body["period"]

    await db.commit()
    await db.refresh(reimbursement)

    return {
        "id": reimbursement.id,
        "reason": reimbursement.reason,
        "period": reimbursement.period,
        "status": reimbursement.status.value,
        "message": "报销单已更新",
    }


@router.put("/reimbursements/{reimbursement_id}/invoices")
async def link_my_invoices(
    reimbursement_id: int,
    body: dict,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """关联发票到报销单（仅草稿状态）

    - 校验报销单归属
    - 仅允许关联当前员工名下且未关联其他报销单的发票
    - 自动累加金额
    """
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")

    invoice_ids: list = body.get("invoice_ids", [])
    linked, total = await svc.link_invoices(
        db, reimbursement_id, invoice_ids,
        allowed_user_filter=employee.employee_no,
    )

    return {
        "status": "ok",
        "linked": linked,
        "total_amount": total,
        "message": f"成功关联 {linked} 张发票",
    }


@router.put("/reimbursements/{reimbursement_id}/unlink/{invoice_id}")
async def unlink_my_invoice(
    reimbursement_id: int,
    invoice_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """从报销单移除发票（仅草稿状态）

    - 校验报销单归属
    - 校验发票归属当前报销单
    - 自动扣减金额
    """
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")

    total = await svc.unlink_invoice(db, reimbursement_id, invoice_id)

    return {
        "status": "ok",
        "total_amount": total,
        "message": "发票已移除",
    }


# ===== 报销单附件 =====

@router.post("/reimbursements/{reimbursement_id}/attachments")
async def upload_attachment(
    reimbursement_id: int,
    file: UploadFile = File(...),
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """上传报销单附件

    - 校验报销单归属且为草稿状态
    - 支持图片/PDF/Office/压缩包格式，单文件最大 20MB
    """
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")

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


@router.delete("/reimbursements/{reimbursement_id}/attachments/{attachment_id}")
async def delete_attachment(
    reimbursement_id: int,
    attachment_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """删除报销单附件（仅草稿状态）"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")
    await svc.delete_attachment(db, reimbursement_id, attachment_id)
    return {"message": "附件已删除", "deleted": True}


@router.get("/reimbursements/{reimbursement_id}/attachments/{attachment_id}/download")
async def download_attachment(
    reimbursement_id: int,
    attachment_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """下载报销单附件"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")

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


@router.post("/reimbursements/{reimbursement_id}/submit")
async def submit_my_reimbursement(
    reimbursement_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """提交报销单"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")
    await svc.submit_reimbursement(db, reimbursement_id)
    return {"status": "ok", "message": "报销单已提交"}


@router.post("/reimbursements/{reimbursement_id}/withdraw")
async def withdraw_my_reimbursement(
    reimbursement_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """撤回报销单（SUBMITTED → DRAFT）"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")
    await svc.withdraw_reimbursement(db, reimbursement_id)
    return {"status": "ok", "message": "报销单已撤回"}


@router.delete("/reimbursements/{reimbursement_id}")
async def delete_my_reimbursement(
    reimbursement_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """删除报销单（校验归属，仅草稿状态可删除）"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")
    await svc.delete_reimbursement(db, reimbursement_id)
    return {"message": f"报销单 #{reimbursement_id} 已删除", "deleted": True}


# ===== 个人信息 =====

@router.get("/profile")
async def get_my_profile(
    employee: Employee = Depends(get_current_employee_async),
):
    """获取个人信息"""
    return {
        "id": employee.id,
        "employee_no": employee.employee_no,
        "name": employee.name,
        "department": employee.department,
        "position": employee.position,
        "mobile": employee.mobile,
        "email": employee.email,
        "status": employee.status.value,
        "last_login_at": employee.last_login_at.isoformat() if employee.last_login_at else None,
    }


# ===== 统计概览 =====

@router.get("/dashboard")
async def get_my_dashboard(
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """员工端首页统计数据"""
    # 我的发票统计
    inv_result = await db.execute(
        select(Invoice).where(Invoice.user_id == employee.employee_no)
    )
    invoices = list(inv_result.scalars().all())

    # 我的报销单统计
    reimb_result = await db.execute(
        select(Reimbursement).where(Reimbursement.applicant_id == employee.employee_no)
    )
    reimbursements = list(reimb_result.scalars().all())

    return {
        "invoice_count": len(invoices),
        "invoice_total": sum(float(i.total_with_tax) for i in invoices if i.total_with_tax),
        "reimbursement_count": len(reimbursements),
        "draft_count": sum(1 for r in reimbursements if r.status == ReimbursementStatus.draft),
        "submitted_count": sum(1 for r in reimbursements if r.status == ReimbursementStatus.submitted),
        "recent_invoices": [
            {
                "id": i.id,
                "seller_name": i.seller_name,
                "total_with_tax": i.total_with_tax,
                "fee_subcategory": i.fee_subcategory,
                "status": i.status.value,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in invoices[:5]
        ],
        "recent_reimbursements": [
            {
                "id": r.id,
                "total_amount": r.total_amount,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reimbursements[:5]
        ],
    }
