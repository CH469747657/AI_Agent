"""员工端业务路由

所有接口需 JWT 鉴权，数据自动隔离为当前员工。
报销单业务逻辑委托给 services/reimbursement_service.py。
"""

import logging
import os
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import FileResponse, StreamingResponse

from app.database import get_db
from app.models.invoice import Invoice, InvoiceStatus
from app.models.reimbursement import Reimbursement, ReimbursementStatus, ReimbursementAttachment
from app.models.employee import Employee
from app.routers.portal_auth import get_current_employee_async
from app.services import reimbursement_service as svc
from app.services.invoice_service import InvoiceService
from app.schemas import InvoiceResponse, SubsidyToggleRequest
from app.dialog.dialog_engine import get_dialog_engine
from app.dialog.models import UserRole
from app.routers.dialog import DialogRequest, DialogAPIResponse, DialogStateResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 我的发票 =====

@router.post("/invoices/upload", response_model=InvoiceResponse)
async def portal_upload_invoice(
    file: UploadFile = File(...),
    receipt_type: str = Form(""),  # 留空 → LLM Vision 自动识别
    user_description: str = Form("", min_length=0),
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """员工端上传发票（JWT 鉴权，user_id 从 token 推导）

    - 不接受客户端传入 user_id，服务端从 JWT token 获取 employee_no
    - 调用与管理端相同的 InvoiceService.process_upload 处理链路

    无感上传模式：
    - receipt_type 留空时，由 LLM Vision 自动判断票据类型
    - user_description 留空时，识别完成后由前端引导用户补充用途
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
        receipt_type=receipt_type or "",
        user_id=employee.employee_no,
        user_description=user_description,
    )
    return invoice


@router.get("/invoices")
async def list_my_invoices(
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """获取我的发票列表（仅展示识别完成的发票，排除 processing 脏数据）"""
    result = await db.execute(
        select(Invoice)
        .where(
            Invoice.user_id == employee.employee_no,
            Invoice.status != InvoiceStatus.processing,
        )
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
            "expense_total": r.expense_total,
            "subsidy_total": r.subsidy_total,
            "status": r.status.value,
            "cycle_start": r.cycle_start.isoformat() if r.cycle_start else None,
            "cycle_end": r.cycle_end.isoformat() if r.cycle_end else None,
            "cycle_key": r.cycle_key,
            "auto_generated": r.auto_generated,
            "is_cycle_locked": r.is_cycle_locked,
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
    """获取报销单详情（含明细行、日补贴、发票、附件）"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权查看该报销单")
    return await svc.serialize_reimbursement_detail(db, reimbursement, include_invoices=True)


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


@router.put("/reimbursements/{reimbursement_id}/subsidy/toggle")
async def toggle_my_subsidy(
    reimbursement_id: int,
    request: SubsidyToggleRequest,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """手动切换某天的补贴计入/取消（仅草稿状态）"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="无权操作该报销单")
    return await svc.toggle_day_subsidy(
        db,
        reimbursement_id,
        request.subsidy_date,
        included=request.included,
        exclude_reason=request.exclude_reason,
    )


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
    """员工端首页统计数据

    发票统计按当前报销周期（上月21日至本月20日）过滤。
    报销单统计已移除（员工端首页不再展示）。
    """
    from datetime import datetime, time, timezone
    from app.services.cycle_engine import current_cycle_key, billing_cycle

    # 当前报销周期：上月21日 ~ 本月20日
    today = datetime.utcnow().date()
    ck = current_cycle_key(today)
    cycle_start, cycle_end = billing_cycle(ck)
    # 转为带时区的 datetime 边界（UTC），与 Invoice.created_at (timestamptz) 对齐
    start_dt = datetime.combine(cycle_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(cycle_end, time.max, tzinfo=timezone.utc)

    # 本周期发票统计（排除 processing 脏数据）
    inv_result = await db.execute(
        select(Invoice).where(
            Invoice.user_id == employee.employee_no,
            Invoice.status != InvoiceStatus.processing,
            Invoice.created_at >= start_dt,
            Invoice.created_at <= end_dt,
        )
    )
    invoices = list(inv_result.scalars().all())

    # 金额求和（容错：total_with_tax 可能是 "200元" 等带非数字字符的脏数据）
    import re
    def _safe_amount(val) -> float:
        if not val:
            return 0.0
        try:
            return float(val)
        except (ValueError, TypeError):
            # 提取首个数字部分
            m = re.search(r"\d+(?:\.\d+)?", str(val))
            return float(m.group()) if m else 0.0

    return {
        "invoice_count": len(invoices),
        "invoice_total": sum(_safe_amount(i.total_with_tax) for i in invoices),
        "cycle_key": ck,
        "cycle_start": cycle_start.isoformat(),
        "cycle_end": cycle_end.isoformat(),
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
    }


# ===== 对话引擎（JWT 鉴权）=====

@router.post("/dialog/message", response_model=DialogAPIResponse)
async def portal_send_message(
    req: DialogRequest,
    employee: Employee = Depends(get_current_employee_async),
):
    """员工端对话入口（JWT 鉴权，user_id/role 从 token 强制推导）

    与管理端 /api/dialog/message 的区别：
    - user_id 强制为 employee.employee_no（客户端传入的被忽略）
    - role 强制为 employee
    - 须携带有效 JWT
    """
    engine = get_dialog_engine()

    attachment_data = {"base64": req.attachment_base64} if req.attachment_base64 else None
    if attachment_data and req.attachment_file_type:
        attachment_data["file_type"] = req.attachment_file_type

    response = await engine.process_message(
        user_id=employee.employee_no,   # 强制覆盖，忽略客户端传入
        text=req.text,
        role=UserRole.EMPLOYEE,         # 强制覆盖
        has_attachment=req.has_attachment,
        attachment_data=attachment_data,
        receipt_type=req.receipt_type,
        user_description=req.user_description,
        no_receipt_amount=req.no_receipt_amount,
    )

    action_data: dict | None = None
    if isinstance(response.action_result, dict):
        d = response.action_result.get("data")
        if d:
            action_data = d

    return DialogAPIResponse(
        text=response.text,
        state=response.state.value,
        intent=response.intent_name,
        action_taken=response.action_taken,
        need_user_input=response.need_user_input,
        quick_replies=response.quick_replies,
        error=response.error,
        data=action_data,
    )


@router.post("/dialog/message/stream")
async def portal_stream_message(
    req: DialogRequest,
    employee: Employee = Depends(get_current_employee_async),
):
    """员工端流式对话入口（JWT 鉴权，SSE）

    与管理端 /api/dialog/message/stream 的区别：
    - user_id 强制为 employee.employee_no（客户端传入的被忽略）
    - role 强制为 employee
    - 须携带有效 JWT

    事件流格式（每行 `data: <json>\\n\\n`）：
    1. {"phase": "progress", "text": "正在理解您的需求…"}  — LLM NLU 前 / Action 执行前
    2. {"phase": "done", "response": <DialogAPIResponse>}  — 最终响应
    3. {"phase": "error", "message": "..."}                  — 异常
    """
    engine = get_dialog_engine()

    attachment_data = {"base64": req.attachment_base64} if req.attachment_base64 else None
    if attachment_data and req.attachment_file_type:
        attachment_data["file_type"] = req.attachment_file_type

    progress_queue: list[dict] = []

    async def on_progress(text: str) -> None:
        progress_queue.append({"text": text})

    async def event_gen():
        try:
            response = await engine.process_message(
                user_id=employee.employee_no,   # 强制覆盖
                text=req.text,
                role=UserRole.EMPLOYEE,         # 强制覆盖
                has_attachment=req.has_attachment,
                attachment_data=attachment_data,
                receipt_type=req.receipt_type,
                user_description=req.user_description,
                no_receipt_amount=req.no_receipt_amount,
                on_progress=on_progress,
            )
            for ev in progress_queue:
                yield f"data: {json.dumps({'phase': 'progress', 'text': ev['text']}, ensure_ascii=False)}\n\n"

            action_data: Optional[dict] = None
            if isinstance(response.action_result, dict):
                d = response.action_result.get("data")
                if d:
                    action_data = d

            final = DialogAPIResponse(
                text=response.text,
                state=response.state.value,
                intent=response.intent_name,
                action_taken=response.action_taken,
                need_user_input=response.need_user_input,
                quick_replies=response.quick_replies,
                error=response.error,
                data=action_data,
            )
            yield f"data: {json.dumps({'phase': 'done', 'response': final.model_dump()}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("Portal SSE stream error: %s", e)
            yield f"data: {json.dumps({'phase': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/dialog/reset")
async def portal_reset_context(
    employee: Employee = Depends(get_current_employee_async),
):
    """重置当前员工的对话上下文（JWT 鉴权，user_id 从 token 推导）"""
    engine = get_dialog_engine()
    await engine.reset_user_async(employee.employee_no)
    return {"status": "ok", "message": "对话上下文已重置"}


@router.get("/dialog/state", response_model=DialogStateResponse)
async def portal_get_state(
    employee: Employee = Depends(get_current_employee_async),
):
    """查询当前员工的对话状态（JWT 鉴权）"""
    engine = get_dialog_engine()
    state = await engine.get_user_state(employee.employee_no)
    if not state:
        return DialogStateResponse(
            user_id=employee.employee_no,
            state="idle",
            role="employee",
            current_intent=None,
            turn_count=0,
            history=[],
        )
    return DialogStateResponse(
        user_id=employee.employee_no,
        state=state.get("state", "idle"),
        role="employee",
        current_intent=state.get("current_intent"),
        turn_count=state.get("turn_count", 0),
        history=state.get("history", []),
    )
