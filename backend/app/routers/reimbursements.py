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
from app.routers.admin_auth import get_current_admin, get_current_admin_or_boss
from app.schemas import (
    ReimbursementCreateRequest,
    ReimbursementResponse,
    ReimbursementLinkRequest,
    SubsidyToggleRequest,
    AggregateRequest,
)
from app.services import reimbursement_service as svc

router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])


@router.post("", response_model=ReimbursementResponse)
async def create_reimbursement(
    request: ReimbursementCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
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
    department: str = None,
    keyword: str = None,
    db: AsyncSession = Depends(get_db),
):
    """获取报销单列表（可按申请人/部门/人名工号筛选）"""
    from sqlalchemy import select, or_
    from app.models.employee import Employee

    query = select(Reimbursement).order_by(Reimbursement.created_at.desc())

    # 按 keyword/department 筛出匹配的 applicant_id 集合
    matched_ids: list[str] | None = None
    if keyword or department:
        emp_q = select(Employee)
        if keyword:
            emp_q = emp_q.where(
                or_(
                    Employee.name.contains(keyword),
                    Employee.employee_no.contains(keyword),
                )
            )
        if department:
            emp_q = emp_q.where(Employee.department == department)
        emp_result = await db.execute(emp_q)
        matched_ids = [str(e.employee_no) for e in emp_result.scalars().all() if e.employee_no]
        if not matched_ids:
            return []

    if applicant_id:
        query = query.where(Reimbursement.applicant_id == applicant_id)
    if matched_ids is not None:
        query = query.where(Reimbursement.applicant_id.in_(matched_ids))

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{reimbursement_id}")
async def get_reimbursement(reimbursement_id: int, db: AsyncSession = Depends(get_db)):
    """获取报销单详情（含明细行、日补贴、附件）"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    return await svc.serialize_reimbursement_detail(db, reimbursement, include_invoices=False)


@router.put("/{reimbursement_id}/invoices", response_model=ReimbursementResponse)
async def link_invoices(
    reimbursement_id: int,
    request: ReimbursementLinkRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """关联发票到报销单"""
    await svc.link_invoices(db, reimbursement_id, request.invoice_ids)
    return await svc.get_reimbursement_or_404(db, reimbursement_id)


@router.put("/{reimbursement_id}/unlink/{invoice_id}", response_model=ReimbursementResponse)
async def unlink_invoice(
    reimbursement_id: int,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """移除报销单中的发票关联"""
    await svc.unlink_invoice(db, reimbursement_id, invoice_id)
    return await svc.get_reimbursement_or_404(db, reimbursement_id)


@router.put("/{reimbursement_id}/submit", response_model=ReimbursementResponse)
async def submit_reimbursement(
    reimbursement_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """提交报销单（DRAFT → SUBMITTED）"""
    return await svc.submit_reimbursement(db, reimbursement_id)


@router.put("/{reimbursement_id}/withdraw", response_model=ReimbursementResponse)
async def withdraw_reimbursement(
    reimbursement_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """撤回报销单（SUBMITTED → DRAFT）"""
    return await svc.withdraw_reimbursement(db, reimbursement_id)


@router.put("/{reimbursement_id}/approve", response_model=ReimbursementResponse)
async def approve_reimbursement(
    reimbursement_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """审核通过（SUBMITTED → REVIEWED）"""
    return await svc.approve_reimbursement(db, reimbursement_id)


@router.put("/{reimbursement_id}/reject", response_model=ReimbursementResponse)
async def reject_reimbursement(
    reimbursement_id: int,
    reason: str = "",
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """驳回报销单（SUBMITTED → DRAFT）"""
    return await svc.reject_reimbursement(db, reimbursement_id, reason=reason)


@router.put("/{reimbursement_id}/reimburse", response_model=ReimbursementResponse)
async def reimburse_reimbursement(
    reimbursement_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """标记已报销（SUBMITTED/REVIEWED → REIMBURSED）"""
    return await svc.mark_reimbursed(db, reimbursement_id)


@router.put("/{reimbursement_id}/subsidy/toggle")
async def toggle_subsidy(
    reimbursement_id: int,
    request: SubsidyToggleRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """手动切换某天的补贴计入/取消（仅草稿状态）"""
    return await svc.toggle_day_subsidy(
        db,
        reimbursement_id,
        request.subsidy_date,
        included=request.included,
        exclude_reason=request.exclude_reason,
    )


@router.post("/cycle/lock/{cycle_key}")
async def lock_cycle(
    cycle_key: str,
    auto_submit: bool = True,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """手动封账指定周期（管理端）

    - auto_submit=True 时自动提交该周期的 DRAFT 报销单
    - 已封账的周期重复封账无副作用（幂等）
    """
    from app.services.cycle_lock_service import lock_cycle as do_lock
    return await do_lock(db, cycle_key, auto_submit_drafts=auto_submit)


@router.get("/cycle/status/{cycle_key}")
async def cycle_lock_status(
    cycle_key: str,
    db: AsyncSession = Depends(get_db),
):
    """查询某周期封账状态"""
    from app.services.cycle_lock_service import get_cycle_lock_status
    return await get_cycle_lock_status(db, cycle_key)


@router.post("/aggregate")
async def aggregate_invoices(
    request: AggregateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """批量归集游离发票到报销单（管理端）

    将所有未关联报销单的游离发票按费用发生日归入对应周期报销单。
    - user_id=None: 归集全公司游离发票
    - user_id="xxx": 只归集指定用户的游离发票

    归集后可继续提交/审批报销单。
    """
    from app.services.aggregation_service import aggregate_pending_invoices
    result = await aggregate_pending_invoices(db, user_id=request.user_id)

    if result["total"] == 0:
        return {
            "message": "没有需要归集的游离发票",
            **result,
        }

    return {
        "message": (
            f"归集完成：共 {result['total']} 张游离发票，"
            f"成功归集 {result['attached']} 张到 {len(result['reimb_ids'])} 份报销单"
            + (f"，{len(result['errors'])} 张失败" if result["errors"] else "")
        ),
        **result,
    }


@router.delete("/{reimbursement_id}")
async def delete_reimbursement(
    reimbursement_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """删除报销单（仅草稿状态）"""
    await svc.delete_reimbursement(db, reimbursement_id)
    return {"message": f"报销单 #{reimbursement_id} 已删除", "deleted": True}


# ===== 报销单附件 =====

@router.post("/{reimbursement_id}/attachments")
async def upload_attachment(
    reimbursement_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
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
    _admin: dict = Depends(get_current_admin),
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
