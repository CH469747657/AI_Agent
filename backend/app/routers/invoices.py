"""发票管理路由"""

import base64
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.admin_auth import get_current_admin, get_current_admin_or_boss
from app.schemas import (
    InvoiceResponse, InvoiceUpdateRequest, NoReceiptRequest,
    WeComProcessRequest, StatisticsResponse, InvoiceVerifyRequest,
    OnlineVerifyResponse,
)
from app.services.invoice_service import InvoiceService

router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])

# 上传发票允许的文件扩展名
ALLOWED_INVOICE_EXTS = {"pdf", "ofd", "jpg", "jpeg", "png", "gif", "bmp", "webp"}


@router.post("/upload", response_model=InvoiceResponse)
async def upload_invoice(
    file: UploadFile = File(...),
    receipt_type: str = Form(""),  # 留空 → LLM Vision 自动识别
    user_id: str = Form(...),
    user_description: str = Form("", min_length=0),  # 无感上传：备注可选
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """上传票据文件并自动处理（OCR + LLM 双源验证 + 分类 + 查重）

    支持 PDF / OFD / JPG / PNG / GIF / BMP / WEBP。

    无感上传模式：
    - receipt_type 留空时，由 LLM Vision 自动判断票据类型
    - user_description 留空时，识别完成后由前端引导用户补充用途
    """
    file_data = await file.read()
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "jpg"

    if file_ext not in ALLOWED_INVOICE_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 .{file_ext}，允许：{', '.join(sorted(ALLOWED_INVOICE_EXTS))}",
        )

    service = InvoiceService(db)
    invoice = await service.process_upload(
        file_data=file_data,
        file_type=file_ext,
        receipt_type=receipt_type or "",
        user_id=user_id,
        user_description=user_description,
    )
    return invoice


@router.post("/wecom-process", response_model=InvoiceResponse)
async def process_from_wecom(
    request: WeComProcessRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """企微网关转发：base64图片 → 处理"""
    file_data = base64.b64decode(request.file_data) if request.file_data else b""

    service = InvoiceService(db)
    invoice = await service.process_upload(
        file_data=file_data,
        file_type=request.file_type,
        receipt_type=request.receipt_type,
        user_id=request.user_id,
        user_description=request.description,
    )
    return invoice


@router.post("/no-receipt", response_model=InvoiceResponse)
async def create_no_receipt(
    request: NoReceiptRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """无票报销：用户文字描述 → LLM 分类"""
    service = InvoiceService(db)
    invoice = await service.process_no_receipt(
        user_id=request.user_id,
        user_description=request.user_description,
        amount=request.amount,
    )
    return invoice


@router.get("", response_model=list[InvoiceResponse])
async def list_invoices(
    user_id: str = None,
    status: str = None,
    db: AsyncSession = Depends(get_db),
):
    """获取发票列表（含上传者信息：员工显示姓名+工号，管理员显示 admin）"""
    from sqlalchemy import select
    from app.models.invoice import Invoice, InvoiceStatus
    from app.models.employee import Employee

    # 默认排除 processing 状态（识别中/失败的脏数据），除非用户显式筛选该状态
    query = select(Invoice).where(Invoice.status != InvoiceStatus.processing).order_by(Invoice.created_at.desc())
    if user_id:
        query = query.where(Invoice.user_id == user_id)
    if status:
        # 显式筛选指定状态时，覆盖默认过滤
        query = select(Invoice).order_by(Invoice.created_at.desc())
        if user_id:
            query = query.where(Invoice.user_id == user_id)
        query = query.where(Invoice.status == InvoiceStatus(status))
    result = await db.execute(query)
    invoices = list(result.scalars().all())

    # 批量查员工表，构建 user_id → uploader_name 映射
    # 同时按 employee_no 和 wecom_user_id 匹配，覆盖更多场景
    user_ids = {inv.user_id for inv in invoices if inv.user_id}
    uploader_map: dict[str, str] = {}
    if user_ids:
        from sqlalchemy import or_
        emp_result = await db.execute(
            select(Employee.employee_no, Employee.name, Employee.wecom_user_id).where(
                or_(
                    Employee.employee_no.in_(user_ids),
                    Employee.wecom_user_id.in_(user_ids),
                )
            )
        )
        for emp_no, emp_name, wecom_uid in emp_result.all():
            display = f"{emp_name}（{emp_no}）" if emp_no else emp_name
            if emp_no:
                uploader_map[emp_no] = display
            if wecom_uid:
                uploader_map[wecom_uid] = display

    # 组装返回：手动构建 dict 以附加 uploader_name
    # 未匹配到员工记录的 user_id 直接显示原始 ID，不再统一回退为 "admin"
    resp = []
    for inv in invoices:
        item = InvoiceResponse.model_validate(inv)
        item.uploader_name = uploader_map.get(inv.user_id, inv.user_id or "未知")
        resp.append(item)
    return resp


@router.get("/export")
async def export_invoices(
    user_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """导出发票清单为 xlsx 文件，可选按上传者筛选"""
    import io
    from sqlalchemy import select
    from app.models.invoice import Invoice, InvoiceStatus, VerifyStatus, DuplicateStatus
    from app.models.employee import Employee
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    # 查询发票
    query = select(Invoice).order_by(Invoice.created_at.desc())
    if user_id:
        query = query.where(Invoice.user_id == user_id)
    result = await db.execute(query)
    invoices = list(result.scalars().all())

    # 构建 uploader_map — 同时按 employee_no 和 wecom_user_id 匹配
    user_ids = {inv.user_id for inv in invoices if inv.user_id}
    uploader_map: dict[str, str] = {}
    if user_ids:
        from sqlalchemy import or_ as _or
        emp_result = await db.execute(
            select(Employee.employee_no, Employee.name, Employee.wecom_user_id).where(
                _or(
                    Employee.employee_no.in_(user_ids),
                    Employee.wecom_user_id.in_(user_ids),
                )
            )
        )
        for emp_no, emp_name, wecom_uid in emp_result.all():
            display = f"{emp_name}（{emp_no}）" if emp_no else emp_name
            if emp_no:
                uploader_map[emp_no] = display
            if wecom_uid:
                uploader_map[wecom_uid] = display

    # 枚举翻译
    def translate_verify(v: VerifyStatus | None) -> str:
        mapping = {VerifyStatus.valid: "验真通过", VerifyStatus.invalid: "验真失败", VerifyStatus.pending: "待验真", VerifyStatus.unable: "无法验真"}
        return mapping.get(v, "—")

    def translate_dup(v: DuplicateStatus | None) -> str:
        mapping = {DuplicateStatus.unique: "唯一", DuplicateStatus.duplicate: "重复", DuplicateStatus.pending: "待查重"}
        return mapping.get(v, "—")

    def translate_status(v: InvoiceStatus | None) -> str:
        mapping = {
            InvoiceStatus.uploaded: "已上传", InvoiceStatus.processing: "处理中",
            InvoiceStatus.reviewing: "待审核", InvoiceStatus.reviewed: "已确认",
            InvoiceStatus.reviewed: "已报销", InvoiceStatus.rejected: "不予报销",
        }
        return mapping.get(v, "—")

    def translate_category(inv: Invoice) -> str:
        cat = {"personal": "个人", "company": "公司"}.get(inv.fee_category.value if inv.fee_category else "", "")
        sub = inv.fee_subcategory or ""
        return f"{cat}/{sub}" if cat and sub else (cat or sub or "—")

    # 创建工作簿
    wb = Workbook()
    ws = wb.active
    ws.title = "发票清单"

    headers = ["序号", "发票号码", "发票代码", "销方名称", "购方名称", "开票日期",
               "金额(不含税)", "税额", "价税合计", "费用分类", "验真状态", "查重状态",
               "发票状态", "上传者", "上传日期"]
    ws.append(headers)

    # 表头样式
    header_font = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # 列宽
    col_widths = [6, 24, 22, 28, 28, 14, 14, 12, 14, 20, 12, 10, 12, 20, 14]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[chr(64 + i) if i <= 26 else "A" + chr(64 + i - 26)].width = w

    # 数据行
    body_font = Font(name="微软雅黑", size=10)
    number_font = Font(name="微软雅黑", size=10)
    body_align = Alignment(vertical="center", wrap_text=False)
    center_align = Alignment(horizontal="center", vertical="center")

    for idx, inv in enumerate(invoices, 1):
        row_data = [
            idx,
            inv.invoice_number or "",
            inv.invoice_code or "",
            inv.seller_name or "",
            inv.buyer_name or "",
            inv.issue_date or "",
            inv.amount or "",
            inv.tax_amount or "",
            inv.total_with_tax or "",
            translate_category(inv),
            translate_verify(inv.verify_status),
            translate_dup(inv.duplicate_status),
            translate_status(inv.status),
            uploader_map.get(inv.user_id, inv.user_id or "未知"),
            inv.created_at.strftime("%Y/%m/%d") if inv.created_at else "",
        ]
        ws.append(row_data)

        row_num = idx + 1
        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=col_idx)
            cell.font = body_font
            cell.border = thin_border
            # 金额列(7,8,9)设数字格式
            if col_idx in (7, 8, 9) and val and str(val).replace(".", "").replace("-", "").isdigit():
                cell.number_format = '#,##0.00'
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx == 1:
                cell.alignment = center_align
            else:
                cell.alignment = body_align

    # 冻结首行
    ws.freeze_panes = "A2"
    # 自动筛选
    ws.auto_filter.ref = f"A1:{chr(64 + len(headers))}1"

    # 写入内存
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    import urllib.parse
    from fastapi.responses import StreamingResponse
    filename_raw = f"发票清单_{user_id or '全部'}.xlsx"
    filename_encoded = urllib.parse.quote(filename_raw)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"},
    )


@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics(db: AsyncSession = Depends(get_db)):
    """获取统计数据"""
    service = InvoiceService(db)
    return await service.get_statistics()


@router.get("/nonstandard-stats")
async def get_nonstandard_stats(db: AsyncSession = Depends(get_db)):
    """非标准票据统计：按风险等级、票据类型分布，及高风险列表"""
    from sqlalchemy import select, func
    from app.models.invoice import Invoice

    # 总量
    total_result = await db.execute(
        select(func.count()).select_from(Invoice).where(Invoice.is_nonstandard == True)
    )
    total_nonstandard = total_result.scalar() or 0

    # 按风险等级
    risk_result = await db.execute(
        select(Invoice.risk_level, func.count()).where(Invoice.is_nonstandard == True).group_by(Invoice.risk_level)
    )
    risk_distribution = {row[0] or "unknown": row[1] for row in risk_result.all()}

    # 按票据类型
    type_result = await db.execute(
        select(Invoice.receipt_type, func.count()).where(Invoice.is_nonstandard == True).group_by(Invoice.receipt_type)
    )
    type_distribution = {str(row[0].value) if row[0] else "unknown": row[1] for row in type_result.all()}

    # 高风险列表
    high_risk_result = await db.execute(
        select(Invoice).where(
            Invoice.is_nonstandard == True,
            Invoice.risk_level == "high",
        ).order_by(Invoice.created_at.desc()).limit(20)
    )
    high_risk_invoices = list(high_risk_result.scalars().all())

    return {
        "total_nonstandard": total_nonstandard,
        "risk_distribution": risk_distribution,
        "type_distribution": type_distribution,
        "high_risk_count": sum(1 for i in high_risk_invoices),
        "high_risk_invoices": [
            {
                "id": i.id,
                "receipt_type": i.receipt_type.value if i.receipt_type else None,
                "seller_name": i.seller_name,
                "total_with_tax": i.total_with_tax,
                "risk_level": i.risk_level,
                "vlm_confidence": i.vlm_confidence,
                "status": i.status.value if i.status else None,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in high_risk_invoices
        ],
    }


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(invoice_id: int, db: AsyncSession = Depends(get_db)):
    """获取发票详情"""
    from sqlalchemy import select
    from app.models.invoice import Invoice
    from app.models.employee import Employee

    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    resp = InvoiceResponse.model_validate(invoice)
    # 关联员工表获取上传者显示名（同时按 employee_no 和 wecom_user_id 匹配）
    if invoice.user_id:
        from sqlalchemy import or_ as _or2
        emp_result = await db.execute(
            select(Employee.name, Employee.employee_no, Employee.wecom_user_id).where(
                _or2(
                    Employee.employee_no == invoice.user_id,
                    Employee.wecom_user_id == invoice.user_id,
                )
            )
        )
        emp = emp_result.first()
        if emp:
            resp.uploader_name = f"{emp.name}（{emp.employee_no}）" if emp.employee_no else emp.name
        else:
            resp.uploader_name = invoice.user_id
    return resp


@router.put("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: int,
    request: InvoiceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """更新发票信息（人工修正分类/项目/状态）"""
    from sqlalchemy import select
    from app.models.invoice import Invoice, InvoiceStatus, FeeCategory
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if request.fee_category:
        try:
            invoice.fee_category = FeeCategory(request.fee_category)
            invoice.classify_source = "manual"
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid fee_category: {request.fee_category}. Valid values: personal, company")
    if request.fee_subcategory:
        invoice.fee_subcategory = request.fee_subcategory
        invoice.classify_source = "manual"
    if request.project_id:
        invoice.project_id = request.project_id
        invoice.project_match_source = "manual"
    if request.status:
        try:
            invoice.status = InvoiceStatus(request.status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid status: {request.status}. Valid values: {', '.join(s.value for s in InvoiceStatus)}")
    if request.user_description is not None:
        invoice.user_description = request.user_description

    await db.commit()
    await db.refresh(invoice)
    return invoice


@router.post("/{invoice_id}/online-verify", response_model=OnlineVerifyResponse)
async def online_verify_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """在线验真：调用百度智能云增值税发票验真 API

    根据发票 OCR 提取的信息（发票代码/号码/日期/校验码/金额）调用国税数据源查验真伪。
    - 验真通过 → verify_status 设为 VALID
    - 验真未通过 → verify_status 设为 INVALID
    - 凭据未配置/请求失败 → verify_status 保持原状，返回降级提示

    返回验真结果 + 百度返回的票面信息（可交叉验证 OCR）。
    """
    from sqlalchemy import select
    from app.models.invoice import Invoice, VerifyStatus
    from app.services.verify_service import get_verify_service

    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    verify_service = get_verify_service()

    # 构建验真请求参数
    invoice_data = {
        "receipt_type": invoice.receipt_type.value if invoice.receipt_type else "增值税普通发票",
        "invoice_code": invoice.invoice_code or "",
        "invoice_number": invoice.invoice_number or "",
        "issue_date": invoice.issue_date or "",
        "check_code": invoice.check_code or "",
        "amount": invoice.amount or "",
        "total_with_tax": invoice.total_with_tax or "",
    }

    # 调用在线验真
    verify_result = await verify_service.verify_invoice(invoice_data)

    # 根据结果更新发票状态
    if verify_result.is_valid is True:
        invoice.verify_status = VerifyStatus.valid
        invoice.verify_message = verify_result.message
        # 验真通过后用国税票面做第三源交叉验证
        if verify_result.verified_fields:
            from app.services.verify_cross_check import cross_check_verified_fields
            from app.models.invoice import InvoiceStatus
            from app.services.classifier import FeeClassifier
            import logging
            logger = logging.getLogger(__name__)
            confirmed = {
                "invoice_number": invoice.invoice_number,
                "invoice_code": invoice.invoice_code,
                "issue_date": invoice.issue_date,
                "seller_name": invoice.seller_name,
                "seller_tax_id": invoice.seller_tax_id,
                "buyer_name": invoice.buyer_name,
                "buyer_tax_id": invoice.buyer_tax_id,
                "total_with_tax": invoice.total_with_tax,
                "amount": invoice.amount,
                "tax_amount": invoice.tax_amount,
                "check_code": invoice.check_code,
            }
            cross = cross_check_verified_fields(confirmed, verify_result.verified_fields)
            invoice.verify_cross_check = cross
            if cross["mismatches"]:
                # 用国税权威数据回写本地识别错误的字段
                corrected_fields = {}
                for mm in cross["mismatches"]:
                    field = mm["field"]
                    verified_val = mm["verified"]
                    if verified_val and field in (
                        "seller_name", "seller_tax_id",
                        "buyer_name", "buyer_tax_id",
                    ):
                        old_val = getattr(invoice, field, None)
                        setattr(invoice, field, verified_val)
                        corrected_fields[field] = {"old": old_val, "new": verified_val}
                        logger.info(
                            f"Invoice #{invoice.id} 验真第三源回写: "
                            f"{field} {old_val} → {verified_val}"
                        )
                # seller_name 修正后重新分类
                if "seller_name" in corrected_fields:
                    try:
                        classifier = FeeClassifier()
                        invoice_data_for_classify = {
                            "receipt_type": invoice.receipt_type.value if invoice.receipt_type else None,
                            "seller_name": invoice.seller_name,
                            "total_with_tax": invoice.total_with_tax,
                            "item_name": invoice.item_name,
                        }
                        classify_result = await classifier.classify(
                            invoice_data_for_classify, invoice.user_description or ""
                        )
                        invoice.fee_category = classify_result["category"]
                        invoice.fee_subcategory = classify_result["subcategory"]
                        invoice.classify_source = classify_result["source"]
                        invoice.classify_confidence = classify_result["confidence"]
                        logger.info(
                            f"Invoice #{invoice.id} seller 修正后重新分类: "
                            f"{classify_result['subcategory']}"
                        )
                    except Exception as e:
                        logger.error(f"Invoice #{invoice.id} 重新分类失败: {e}")
                # 有差异 → 标记人工复核
                if invoice.status == InvoiceStatus.reviewed:
                    invoice.status = InvoiceStatus.reviewing
    elif verify_result.is_valid is False:
        invoice.verify_status = VerifyStatus.invalid
        invoice.verify_message = verify_result.message
    else:
        # is_valid is None → 降级，不修改状态，但记录原因
        invoice.verify_message = verify_result.message

    await db.commit()
    await db.refresh(invoice)

    return OnlineVerifyResponse(
        invoice_id=invoice_id,
        verify_status=invoice.verify_status.value,
        message=verify_result.message,
        is_verified=verify_result.is_valid,
        invoice_status=verify_result.invoice_status or None,
        verified_fields=verify_result.verified_fields or None,
        invoice=invoice,
    )


@router.put("/{invoice_id}/verify", response_model=InvoiceResponse)
async def verify_invoice(
    invoice_id: int,
    request: InvoiceVerifyRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """手动设置发票验真状态"""
    from sqlalchemy import select
    from app.models.invoice import Invoice, VerifyStatus
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    try:
        invoice.verify_status = VerifyStatus(request.verify_status)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid verify_status: {request.verify_status}")

    await db.commit()
    await db.refresh(invoice)
    return invoice


@router.get("/{invoice_id}/file")
async def download_invoice_file(invoice_id: int, db: AsyncSession = Depends(get_db)):
    """下载发票原始文件"""
    import os
    from sqlalchemy import select
    from app.models.invoice import Invoice
    from fastapi.responses import FileResponse

    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if not invoice.file_path or not os.path.exists(invoice.file_path):
        raise HTTPException(status_code=404, detail="原始文件不存在")

    ext = os.path.splitext(invoice.file_path)[1]
    return FileResponse(
        invoice.file_path,
        filename=f"发票_{invoice.invoice_number or invoice_id}{ext}",
        media_type="application/octet-stream",
    )


@router.post("/{invoice_id}/approve", response_model=InvoiceResponse)
async def approve_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """审核通过：REVIEWING → CONFIRMED（管理员专用）"""
    from sqlalchemy import select
    from app.models.invoice import Invoice, InvoiceStatus
    from datetime import datetime

    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != InvoiceStatus.reviewing:
        raise HTTPException(
            status_code=409,
            detail=f"当前发票状态为 {invoice.status.value}，仅待审核状态可确认",
        )
    invoice.status = InvoiceStatus.reviewed
    invoice.confirmed_at = datetime.now()
    await db.commit()
    await db.refresh(invoice)
    return invoice


@router.post("/{invoice_id}/reject", response_model=InvoiceResponse)
async def reject_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """审核驳回：REVIEWING → NOT_REIMBURSED（管理员专用）"""
    from sqlalchemy import select
    from app.models.invoice import Invoice, InvoiceStatus

    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != InvoiceStatus.reviewing:
        raise HTTPException(
            status_code=409,
            detail=f"当前发票状态为 {invoice.status.value}，仅待审核状态可驳回",
        )
    invoice.status = InvoiceStatus.rejected
    await db.commit()
    await db.refresh(invoice)
    return invoice


@router.delete("/{invoice_id}")
async def delete_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """删除发票及其关联的 OCR/LLM 结果

    同时删除服务器上的原始票据文件。
    关联了报销单的发票不允许删除。
    """
    import os
    from sqlalchemy import select
    from app.models.invoice import Invoice, OcrResult, LlmResult

    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice = result.scalars().first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

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

    # 删除发票记录
    await db.delete(invoice)
    await db.commit()

    return {"message": f"发票 #{invoice_id} 已删除", "deleted": True}
