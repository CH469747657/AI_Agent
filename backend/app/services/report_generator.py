"""报表生成服务（Excel + PDF + ZIP）

技术路线:
  Excel: openpyxl — 按费用类别分Sheet，含合计公式和条件格式
  PDF:   WeasyPrint — HTML/CSS 模板 → PDF，含票据缩略图
  ZIP:   Python zipfile — 原始票据按分类归档

参考: openpyxl 官方文档, WeasyPrint (6.7k⭐)
"""

import os
import zipfile
import logging
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus, FeeCategory
from app.models.reimbursement import Reimbursement
from app.config import settings

logger = logging.getLogger(__name__)


class ReportGenerator:
    """报销报表生成器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_all(self, reimbursement_id: int) -> dict:
        """生成完整报销包：Excel + PDF + ZIP"""
        # 获取报销单及所有票据
        result = await self.db.execute(
            select(Reimbursement).where(Reimbursement.id == reimbursement_id)
        )
        reimbursement = result.scalars().first()
        if not reimbursement:
            raise ValueError(f"Reimbursement #{reimbursement_id} not found")

        result = await self.db.execute(
            select(Invoice).where(Invoice.reimbursement_id == reimbursement_id)
        )
        invoices = list(result.scalars().all())

        # 生成三种格式（PDF 失败不阻断 Excel/ZIP）
        excel_path = self._generate_excel(reimbursement, invoices)
        pdf_path = None
        try:
            pdf_path = await self._generate_pdf(reimbursement, invoices)
        except Exception as e:
            logger.warning(f"PDF generation failed (non-fatal): {e}")
        zip_path = self._generate_zip(
            invoices,
            reimbursement_id=reimbursement_id,
            excel_path=excel_path,
            pdf_path=pdf_path,
        )

        # 更新报销单记录
        reimbursement.excel_path = excel_path
        reimbursement.pdf_path = pdf_path
        reimbursement.zip_path = zip_path
        await self.db.commit()

        logger.info(f"Report generated for reimbursement #{reimbursement_id}")
        return {"excel": excel_path, "pdf": pdf_path, "zip": zip_path}

    # ===== Excel 报表 =====
    def _generate_excel(self, reimbursement: Reimbursement, invoices: list[Invoice]) -> str:
        """生成 Excel 汇总表

        参考: openpyxl — 样式、公式、条件格式
        """
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        wb = Workbook()

        # === 汇总 Sheet ===
        ws = wb.active
        ws.title = "汇总"

        headers = ["日期", "项目", "费用类别", "子类别", "金额", "税额", "价税合计", "发票号", "验真状态", "查重状态"]
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=11)
        thin_border = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin"),
        )

        # === 报销信息标题区 ===
        ws.merge_cells("A1:J1")
        title_cell = ws.cell(row=1, column=1, value="报销汇总报表")
        title_cell.font = Font(bold=True, size=14, color="1a5276")
        title_cell.alignment = Alignment(horizontal="center")

        info_parts = [f"申请人：{reimbursement.applicant_name or reimbursement.applicant_id}"]
        if reimbursement.department:
            info_parts.append(f"部门：{reimbursement.department}")
        if reimbursement.period:
            info_parts.append(f"报销期间：{reimbursement.period}")
        ws.merge_cells("A2:J2")
        ws.cell(row=2, column=1, value="    ".join(info_parts)).font = Font(size=11)

        ws.merge_cells("A3:J3")
        ws.cell(row=3, column=1, value=f"报销事由：{reimbursement.reason or '—'}").font = Font(size=11)

        # === 表头（第5行）===
        HEADER_ROW = 5
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=HEADER_ROW, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
            cell.border = thin_border

        # 数据行
        for row_idx, inv in enumerate(invoices, HEADER_ROW + 1):
            row_data = [
                inv.issue_date or "",
                inv.project_id or "",
                inv.fee_category.value if inv.fee_category else "",
                inv.fee_subcategory or "",
                float(inv.amount) if inv.amount else 0,
                float(inv.tax_amount) if inv.tax_amount else 0,
                float(inv.total_with_tax) if inv.total_with_tax else 0,
                inv.invoice_number or "",
                inv.verify_status.value if inv.verify_status else "",
                inv.duplicate_status.value if inv.duplicate_status else "",
            ]
            for col_idx, val in enumerate(row_data, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.border = thin_border

            # 验真失败标红
            if inv.verify_status and inv.verify_status.value == "INVALID":
                for c in range(1, len(headers) + 1):
                    ws.cell(row=row_idx, column=c).fill = PatternFill(
                        start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"
                    )

        # 合计行
        total_row = HEADER_ROW + len(invoices) + 1
        ws.cell(row=total_row, column=4, value="合计").font = Font(bold=True)
        ws.cell(row=total_row, column=5, value=f"=SUM(E{HEADER_ROW+1}:E{total_row-1})").font = Font(bold=True)
        ws.cell(row=total_row, column=6, value=f"=SUM(F{HEADER_ROW+1}:F{total_row-1})").font = Font(bold=True)
        ws.cell(row=total_row, column=7, value=f"=SUM(G{HEADER_ROW+1}:G{total_row-1})").font = Font(bold=True)

        # 列宽
        col_widths = [12, 15, 12, 15, 12, 12, 12, 20, 12, 12]
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[chr(64 + i)].width = w

        # === 分类 Sheet ===
        for category, sheet_name in [(FeeCategory.personal, "个人费用"), (FeeCategory.company, "公司费用")]:
            ws_cat = wb.create_sheet(sheet_name)
            cat_invoices = [i for i in invoices if i.fee_category == category]

            for col, header in enumerate(headers, 1):
                cell = ws_cat.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill

            for row_idx, inv in enumerate(cat_invoices, 2):
                row_data = [
                    inv.issue_date or "", inv.project_id or "",
                    inv.fee_category.value if inv.fee_category else "",
                    inv.fee_subcategory or "",
                    float(inv.amount) if inv.amount else 0,
                    float(inv.tax_amount) if inv.tax_amount else 0,
                    float(inv.total_with_tax) if inv.total_with_tax else 0,
                    inv.invoice_number or "",
                    inv.verify_status.value if inv.verify_status else "",
                    inv.duplicate_status.value if inv.duplicate_status else "",
                ]
                for col_idx, val in enumerate(row_data, 1):
                    ws_cat.cell(row=row_idx, column=col_idx, value=val)

            for i, w in enumerate(col_widths, 1):
                ws_cat.column_dimensions[chr(64 + i)].width = w

        # 保存
        filepath = os.path.join(settings.report_dir, f"reimbursement_{reimbursement.id}.xlsx")
        wb.save(filepath)
        return filepath

    # ===== PDF 报表 =====
    async def _generate_pdf(self, reimbursement: Reimbursement, invoices: list[Invoice]) -> str:
        """生成 PDF 明细报告（HTML → PDF）"""
        from weasyprint import HTML
        from jinja2 import Template

        total_amount = sum(float(i.total_with_tax) for i in invoices if i.total_with_tax)

        html_template = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 2cm; }
body { font-family: "Noto Sans CJK SC", "SimHei", sans-serif; }
.cover { text-align: center; padding: 80px 0; }
.cover h1 { font-size: 24pt; color: #1a5276; margin-bottom: 30px; }
.cover p { font-size: 14pt; margin: 8px 0; }
.summary { margin: 30px 0; }
.summary table { width: 100%; border-collapse: collapse; }
.summary th { background: #4472C4; color: white; padding: 8px; text-align: left; }
.summary td { border: 1px solid #ddd; padding: 8px; }
.item { border: 1px solid #ddd; margin: 10px 0; padding: 12px; border-radius: 4px; }
.item table { width: 100%; border-collapse: collapse; }
.item td { padding: 4px 8px; }
.item .label { color: #666; width: 100px; }
.status-ok { color: #27ae60; font-weight: bold; }
.status-warn { color: #e74c3c; font-weight: bold; }
</style></head><body>
<div class="cover">
  <h1>报销汇总报告</h1>
  <p>报销人：{{ applicant_name }}</p>
  <p>部门：{{ department }}</p>
  <p>报销期间：{{ period }}</p>
  {% if reason %}<p>报销事由：{{ reason }}</p>{% endif %}
  <p>票据数量：{{ invoice_count }} 张</p>
  <p style="font-size: 18pt; color: #e74c3c; margin-top: 20px;">总金额：¥{{ total_amount }}</p>
</div>
<div class="summary">
  <h2>票据明细</h2>
  {% for inv in invoices %}
  <div class="item">
    <table>
      <tr><td class="label">发票号</td><td>{{ inv.invoice_number or '无' }}</td></tr>
      <tr><td class="label">日期</td><td>{{ inv.issue_date or '未知' }}</td></tr>
      <tr><td class="label">销售方</td><td>{{ inv.seller_name or '未知' }}</td></tr>
      <tr><td class="label">金额</td><td>¥{{ inv.total_with_tax or '0' }}</td></tr>
      <tr><td class="label">费用类别</td><td>{{ inv.fee_subcategory or '待确认' }}</td></tr>
      <tr><td class="label">验真</td>
          <td class="{{ 'status-ok' if inv.verify_status.value == 'VALID' else 'status-warn' }}">
          {{ '✓ 已验真' if inv.verify_status.value == 'VALID' else '⚠ 待验证' }}</td></tr>
      <tr><td class="label">查重</td>
          <td class="{{ 'status-ok' if inv.duplicate_status.value == 'UNIQUE' else 'status-warn' }}">
          {{ '✓ 无重复' if inv.duplicate_status.value == 'UNIQUE' else '⚠ ' + inv.duplicate_status.value }}</td></tr>
    </table>
  </div>
  {% endfor %}
</div>
</body></html>"""

        html_content = Template(html_template).render(
            applicant_name=reimbursement.applicant_name or "未知",
            department=reimbursement.department or "未知",
            period=reimbursement.period or "未知",
            reason=reimbursement.reason,
            invoice_count=len(invoices),
            total_amount=f"{total_amount:.2f}",
            invoices=invoices,
        )

        filepath = os.path.join(settings.report_dir, f"reimbursement_{reimbursement.id}.pdf")
        HTML(string=html_content).write_pdf(filepath)
        return filepath

    # ===== ZIP 完整报销包 =====
    def _generate_zip(
        self,
        invoices: list[Invoice],
        reimbursement_id: int = None,
        excel_path: str = None,
        pdf_path: str = None,
    ) -> str:
        """打包完整报销包：Excel 明细表 + PDF 报销单 + 原始发票"""
        suffix = f"_{reimbursement_id}" if reimbursement_id else ""
        filepath = os.path.join(settings.report_dir, f"reimbursement{suffix}.zip")

        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Excel 明细表
            if excel_path and os.path.exists(excel_path):
                zf.write(excel_path, os.path.basename(excel_path))

            # 2. PDF 报销单
            if pdf_path and os.path.exists(pdf_path):
                zf.write(pdf_path, os.path.basename(pdf_path))

            # 3. 原始发票（按分类归档到子目录）
            for inv in invoices:
                if not inv.file_path or not os.path.exists(inv.file_path):
                    continue
                cat = inv.fee_subcategory or "未分类"
                date = inv.issue_date or "未知日期"
                amount = inv.total_with_tax or "0"
                num = inv.invoice_number or "无票号"
                ext = os.path.splitext(inv.file_path)[1]
                arcname = f"原始发票/{cat}_{date}_{amount}_{num}{ext}"
                zf.write(inv.file_path, arcname)

        return filepath
