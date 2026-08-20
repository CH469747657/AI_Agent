"""报表生成服务（Excel + PDF + ZIP）

重构后内容：
  Excel: openpyxl — 费用清单，一行一个 ReimbursementItem（无 item 时退回到一张发票一行）
  PDF:   WeasyPrint — 发票汇总：封面 + 每张发票元数据 + 嵌入原始图片（PDF 发票先转图片）
  ZIP:   Python zipfile — Excel 费用清单 + PDF 发票汇总 + 原始发票图片目录

数据源:
  ReimbursementItem       — 费用清单行
  Invoice                 — 发票元数据、原始文件、PDF 内嵌图片
"""

import os
import re
import shutil
import tempfile
import zipfile
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.reimbursement import (
    Reimbursement,
    ReimbursementItem,
    ReimbursementDaySubsidy,
)
from app.config import settings

logger = logging.getLogger(__name__)

_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


def _weekday_cn(d: date | None) -> str:
    if not d:
        return ""
    return _WEEKDAY_CN[d.weekday()]


def _parse_amount_safe(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _format_cycle_range(reimbursement: Reimbursement) -> str:
    """格式化周期时间段为中文: （2026年6月21日-7月20日）"""
    start = reimbursement.cycle_start
    end = reimbursement.cycle_end
    if not start or not end:
        if reimbursement.cycle_key:
            return f"（{reimbursement.cycle_key}）"
        if reimbursement.period:
            return f"（{reimbursement.period}）"
        return ""
    start_str = f"{start.year}年{start.month}月{start.day}日"
    if start.year == end.year:
        end_str = f"{end.month}月{end.day}日"
    else:
        end_str = f"{end.year}年{end.month}月{end.day}日"
    return f"（{start_str}-{end_str}）"


def _clean_filename_part(part: str | None, default: str = "未知") -> str:
    if not part:
        return default
    # 保留中英文、数字、下划线、连字符、小数点；其余替换为下划线
    cleaned = re.sub(r"[^\w一-龥.\-]", "_", str(part))
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or default


class ReportGenerator:
    """报销报表生成器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_all(self, reimbursement_id: int) -> dict:
        """生成完整报销包：Excel + PDF + ZIP"""
        result = await self.db.execute(
            select(Reimbursement).where(Reimbursement.id == reimbursement_id)
        )
        reimbursement = result.scalars().first()
        if not reimbursement:
            raise ValueError(f"Reimbursement #{reimbursement_id} not found")

        result = await self.db.execute(
            select(ReimbursementItem)
            .where(ReimbursementItem.reimbursement_id == reimbursement_id)
            .order_by(ReimbursementItem.sort_order)
        )
        reimbursement._items_cache = list(result.scalars().all())

        result = await self.db.execute(
            select(ReimbursementDaySubsidy)
            .where(ReimbursementDaySubsidy.reimbursement_id == reimbursement_id)
            .order_by(ReimbursementDaySubsidy.subsidy_date)
        )
        reimbursement._day_subsidies_cache = list(result.scalars().all())

        result = await self.db.execute(
            select(Invoice).where(Invoice.reimbursement_id == reimbursement_id)
        )
        invoices = list(result.scalars().all())

        # 加载节假日 — 周期跨年时同时查上一年 12 月与本年全年
        cycle_year = (reimbursement.cycle_start or date.today()).year
        holidays = await self._load_holidays(cycle_year)

        excel_path = self._generate_excel(reimbursement, invoices, holidays)
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

        reimbursement.excel_path = excel_path
        reimbursement.pdf_path = pdf_path
        reimbursement.zip_path = zip_path
        await self.db.commit()

        logger.info(f"Report generated for reimbursement #{reimbursement_id}")
        return {"excel": excel_path, "pdf": pdf_path, "zip": zip_path}

    # ===== Excel：费用清单 =====
    async def _load_holidays(self, cycle_year: int) -> dict:
        """加载节假日 dict {date: "holiday"|"workday"}"""
        from app.models.holiday import Holiday
        year_start = date(cycle_year - 1, 12, 1)
        year_end = date(cycle_year, 12, 31)
        result = await self.db.execute(
            select(Holiday).where(
                Holiday.holiday_date >= year_start,
                Holiday.holiday_date <= year_end,
            )
        )
        return {h.holiday_date: h.day_type for h in result.scalars().all()}

    def _generate_excel(
        self,
        reimbursement: Reimbursement,
        invoices: list[Invoice],
        holidays: dict | None = None,
    ) -> str:
        """生成模板格式的 Excel 报销单

        严格对齐 报销单模板.xlsx：
        - 5 列：日期 / 星期 / 补贴 / 其他费用（金额） / 内容说明
        - 上半段一天一行，仅列周期内有费用发生的天；同日 ≥2 张发票 D/E 留空，费用行移至末尾
        - 小计行 C 列 SUM 补贴、D 列 SUM 费用；合计行 C{小计}+D{小计}
        """
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, Border, Side
        from collections import defaultdict

        if holidays is None:
            holidays = {}

        wb = Workbook()
        ws = wb.active
        ws.title = "报销单"

        thin = Side(style="thin")
        thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
        font_title = Font(name="宋体", size=14)
        font_normal = Font(name="宋体", size=12)
        align_center = Alignment(horizontal="center", vertical="center")
        align_center_wrap = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # 1-4 行：标题 / 副标题 / 报销人 / 周期
        ws.merge_cells("A1:E1")
        c = ws.cell(row=1, column=1, value=settings.company_name)
        c.font = font_title
        c.alignment = align_center

        ws.merge_cells("A2:E2")
        c = ws.cell(row=2, column=1, value="项目出差报销费用清单")
        c.font = font_title
        c.alignment = align_center

        ws.merge_cells("A3:E3")
        applicant = reimbursement.applicant_name or reimbursement.applicant_id or ""
        c = ws.cell(row=3, column=1, value=f"报销人：  {applicant}")
        c.font = font_normal
        c.alignment = align_center

        ws.merge_cells("A4:E4")
        c = ws.cell(row=4, column=1, value=_format_cycle_range(reimbursement))
        c.font = font_normal
        c.alignment = align_center
        c.border = thin_border

        # 第 5 行：表头
        ws.cell(row=5, column=1, value="日期").font = font_normal
        ws.cell(row=5, column=2, value="星期").font = font_normal
        ws.cell(row=5, column=3, value="补贴").font = font_normal
        ws.merge_cells("D5:E5")
        ws.cell(row=5, column=4, value="其他费用及内容说明").font = font_normal
        for col in range(1, 6):
            cell = ws.cell(row=5, column=col)
            cell.alignment = align_center_wrap
            cell.border = thin_border

        # 数据行构建
        # 补贴行：从 day_subsidies 表读，每条出差日独立一行（不再从 items 推导）
        subsidies = getattr(reimbursement, "_day_subsidies_cache", None) or []
        subsidy_by_date: dict[date, ReimbursementDaySubsidy] = {}
        for sub in subsidies:
            if not sub.included:
                continue
            if not sub.subsidy_date:
                continue
            subsidy_by_date[sub.subsidy_date] = sub

        # 费用行：按 item_date 分组
        items = getattr(reimbursement, "_items_cache", None) or []
        in_cycle_items: list = []  # 有日期且在周期内 → 进主体行
        tail_items: list = []      # 无日期或不在周期内 → 进末尾
        for it in items:
            if not it.item_date:
                tail_items.append(it)
                continue
            if reimbursement.cycle_start and reimbursement.cycle_end:
                if not (reimbursement.cycle_start <= it.item_date <= reimbursement.cycle_end):
                    tail_items.append(it)
                    continue
            in_cycle_items.append(it)

        by_date: dict[date, list] = defaultdict(list)
        for it in in_cycle_items:
            by_date[it.item_date].append(it)

        # 合并日期集合：补贴日期 ∪ 费用日期，排序
        all_dates = sorted(set(subsidy_by_date.keys()) | set(by_date.keys()))

        upper_rows = []  # (date, weekday_str, subsidy_amount_or_None, amount_or_None, desc_or_None)
        lower_rows = []  # (amount, desc) — 同日溢出 + 无日期费用
        for d in all_dates:
            sub = subsidy_by_date.get(d)
            subsidy_amt = float(sub.subsidy_amount) if sub else None
            wd = _WEEKDAY_CN[d.weekday()]

            its = by_date.get(d, [])
            its.sort(key=lambda x: x.sort_order or 0)

            if not its:
                # 该日只有补贴，无费用
                upper_rows.append((d, wd, subsidy_amt, None, None))
            elif len(its) == 1:
                it = its[0]
                amt = float(it.amount) if it.amount is not None else 0.0
                desc = it.description or it.fee_subcategory or ""
                upper_rows.append((d, wd, subsidy_amt, amt, desc))
            else:
                # 同日多条费用：第一条进主行，其余进末尾
                first = its[0]
                amt = float(first.amount) if first.amount is not None else 0.0
                desc = first.description or first.fee_subcategory or ""
                upper_rows.append((d, wd, subsidy_amt, amt, desc))
                for it in its[1:]:
                    a = float(it.amount) if it.amount is not None else 0.0
                    dsc = it.description or it.fee_subcategory or ""
                    lower_rows.append((a, dsc))

        # 无日期/不在周期内的费用 → 末尾
        for it in tail_items:
            a = float(it.amount) if it.amount is not None else 0.0
            dsc = it.description or it.fee_subcategory or ""
            lower_rows.append((a, dsc))

        # 写入上半段（日期行：A 日期 / B 星期 / C 补贴 / D 费用 / E 说明）
        row = 6
        upper_first = row
        for d, wd, subsidy_amt, amt, desc in upper_rows:
            cell = ws.cell(row=row, column=1, value=d)
            cell.font = font_normal
            cell.number_format = "yyyy-mm-dd"
            cell.alignment = align_center
            cell.border = thin_border

            cell = ws.cell(row=row, column=2, value=wd)
            cell.font = font_normal
            cell.alignment = align_center
            cell.border = thin_border

            # C 列补贴：每条出差日独立填写
            if subsidy_amt is not None:
                cell = ws.cell(row=row, column=3, value=subsidy_amt)
                cell.font = font_normal
                cell.number_format = "0.00"
                cell.alignment = align_center
                cell.border = thin_border
            else:
                ws.cell(row=row, column=3).border = thin_border

            if amt is not None:
                cell = ws.cell(row=row, column=4, value=amt)
                cell.font = font_normal
                cell.number_format = "0.00"
                cell.alignment = align_center
                cell.border = thin_border
            else:
                ws.cell(row=row, column=4).border = thin_border

            if desc:
                cell = ws.cell(row=row, column=5, value=desc)
                cell.font = font_normal
                cell.alignment = align_center_wrap
                cell.border = thin_border
            else:
                ws.cell(row=row, column=5).border = thin_border
            row += 1
        upper_last = row - 1

        # 写入下半段（末尾费用行：D 金额 / E 说明，A/B/C 空）
        for amt, desc in lower_rows:
            cell = ws.cell(row=row, column=4, value=amt)
            cell.font = font_normal
            cell.number_format = "0.00"
            cell.alignment = align_center
            cell.border = thin_border

            cell = ws.cell(row=row, column=5, value=desc)
            cell.font = font_normal
            cell.alignment = align_center_wrap
            cell.border = thin_border

            for col in (1, 2, 3):
                ws.cell(row=row, column=col).border = thin_border
            row += 1
        lower_last = row - 1

        # 小计行
        subtotal_row = row
        cell = ws.cell(row=subtotal_row, column=2, value="小计")
        cell.font = font_normal
        cell.alignment = align_center
        cell.border = thin_border

        if upper_first <= upper_last:
            cell = ws.cell(row=subtotal_row, column=3, value=f"=SUM(C{upper_first}:C{upper_last})")
        else:
            cell = ws.cell(row=subtotal_row, column=3, value=0)
        cell.font = font_normal
        cell.alignment = align_center
        cell.border = thin_border

        if upper_first <= lower_last:
            cell = ws.cell(row=subtotal_row, column=4, value=f"=SUM(D{upper_first}:D{lower_last})")
        else:
            cell = ws.cell(row=subtotal_row, column=4, value=0)
        cell.font = font_normal
        cell.alignment = align_center
        cell.border = thin_border

        for col in (1, 5):
            ws.cell(row=subtotal_row, column=col).border = thin_border

        # 合计行
        total_row = subtotal_row + 1
        cell = ws.cell(row=total_row, column=2, value="合计")
        cell.font = font_normal
        cell.alignment = align_center
        cell.border = thin_border

        ws.merge_cells(start_row=total_row, start_column=3, end_row=total_row, end_column=4)
        cell = ws.cell(row=total_row, column=3, value=f"=C{subtotal_row}+D{subtotal_row}")
        cell.font = font_normal
        cell.alignment = align_center
        cell.border = thin_border
        ws.cell(row=total_row, column=4).border = thin_border

        for col in (1, 5):
            ws.cell(row=total_row, column=col).border = thin_border

        # 列宽（与模板一致）
        ws.column_dimensions["A"].width = 15.67
        ws.column_dimensions["B"].width = 8.51
        ws.column_dimensions["C"].width = 7.49
        ws.column_dimensions["D"].width = 14.53
        ws.column_dimensions["E"].width = 38.17

        filepath = os.path.join(settings.report_dir, f"reimbursement_{reimbursement.id}.xlsx")
        wb.save(filepath)
        return filepath

    # ===== PDF：发票汇总 =====
    async def _generate_pdf(self, reimbursement: Reimbursement, invoices: list[Invoice]) -> str:
        from weasyprint import HTML
        from jinja2 import Template

        tmp_files = []
        invoice_contexts = []
        for idx, inv in enumerate(invoices, 1):
            ctx = self._invoice_to_pdf_context(inv, idx)
            # 所有转出的临时图片都加入 tmp_files 等待清理（OFD/PDF 转换产物）
            if ctx.get("embed_image_path"):
                ext = os.path.splitext(ctx["embed_image_path"])[1].lower()
                # 仅清理临时目录下的转换产物，原始 jpg/png 不动
                if ctx["embed_image_path"].startswith(os.path.join(settings.report_dir, ".tmp")):
                    tmp_files.append(ctx["embed_image_path"])
            invoice_contexts.append(ctx)

        expense_total = float(reimbursement.expense_total or 0)
        subsidy_total = float(reimbursement.subsidy_total or 0)
        total_amount = float(reimbursement.total_amount or (expense_total + subsidy_total))

        html_template = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 1.8cm; }
body { font-family: "Noto Sans CJK SC", "SimHei", sans-serif; font-size: 11pt; }
.cover { text-align: center; padding: 40px 0; }
.cover h1 { font-size: 20pt; color: #1a5276; margin-bottom: 12px; }
.cover p { font-size: 12pt; margin: 6px 0; }
.amount-summary { margin: 20px 0; display: flex; justify-content: center; gap: 40px; }
.amount-box { text-align: center; }
.amount-box .label { font-size: 10pt; color: #666; }
.amount-box .value { font-size: 16pt; font-weight: bold; margin-top: 4px; }
.amount-box.total .value { color: #e74c3c; }
.section { page-break-before: always; }
.section:first-of-type { page-break-before: auto; }
.section h2 { font-size: 14pt; color: #1a5276; margin-bottom: 8px; }
.meta { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
.meta th, .meta td { border: 1px solid #999; padding: 5px 8px; font-size: 10.5pt; }
.meta th { background: #f0f0f0; width: 18%; text-align: left; }
.invoice-image { max-width: 100%; max-height: 18cm; border: 1px solid #ddd; }
.placeholder { color: #999; font-style: italic; padding: 24px; border: 1px dashed #ccc; text-align: center; }
.no-invoice { text-align: center; padding: 40px; color: #999; font-size: 12pt; }
</style></head><body>
<div class="cover">
  <h1>{{ company_name }}<br/>发票汇总</h1>
  <p>申请人：{{ applicant_name }}</p>
  {% if department %}<p>部门：{{ department }}</p>{% endif %}
  <p>周期：{{ cycle_range }}</p>
  {% if reason %}<p>报销事由：{{ reason }}</p>{% endif %}
  <div class="amount-summary">
    <div class="amount-box"><div class="label">费用合计</div><div class="value">¥{{ expense_total }}</div></div>
    <div class="amount-box"><div class="label">补贴合计</div><div class="value">¥{{ subsidy_total }}</div></div>
    <div class="amount-box total"><div class="label">报销总额</div><div class="value">¥{{ total_amount }}</div></div>
  </div>
</div>
{% if invoices %}
{% for inv in invoices %}
<div class="section">
  <h2>发票 #{{ inv.index }}</h2>
  <table class="meta">
    <tr><th>发票类型</th><td>{{ inv.receipt_type }}</td><th>开票日期</th><td>{{ inv.issue_date }}</td></tr>
    <tr><th>发票代码</th><td>{{ inv.invoice_code }}</td><th>发票号码</th><td>{{ inv.invoice_number }}</td></tr>
    <tr><th>购方名称</th><td>{{ inv.buyer_name }}</td><th>销方名称</th><td>{{ inv.seller_name }}</td></tr>
    <tr><th>金额(含税)</th><td>{{ inv.total_with_tax }}</td><th>税率</th><td>{{ inv.tax_rate }}</td></tr>
    <tr><th>税额</th><td>{{ inv.tax_amount }}</td><th>费用分类</th><td>{{ inv.fee_subcategory }}</td></tr>
    <tr><th>验真状态</th><td>{{ inv.verify_status }}</td><th>查重状态</th><td>{{ inv.duplicate_status }}</td></tr>
  </table>
  {% if inv.is_image %}
  <img class="invoice-image" src="file://{{ inv.embed_image_path }}">
  {% else %}
  <div class="placeholder">{{ inv.placeholder }}</div>
  {% endif %}
</div>
{% endfor %}
{% else %}
<div class="no-invoice">本报销单暂无关联发票</div>
{% endif %}
</body></html>"""

        html_content = Template(html_template).render(
            company_name=settings.company_name,
            applicant_name=reimbursement.applicant_name or reimbursement.applicant_id,
            department=reimbursement.department or "",
            cycle_range=_format_cycle_range(reimbursement).strip("（）") or reimbursement.cycle_key or "",
            reason=reimbursement.reason or "",
            expense_total=f"{expense_total:.2f}",
            subsidy_total=f"{subsidy_total:.2f}",
            total_amount=f"{total_amount:.2f}",
            invoices=invoice_contexts,
        )

        filepath = os.path.join(settings.report_dir, f"reimbursement_{reimbursement.id}.pdf")
        HTML(string=html_content).write_pdf(filepath)

        for tmp in tmp_files:
            try:
                os.remove(tmp)
            except Exception as e:
                logger.warning(f"Failed to remove temp image {tmp}: {e}")
        return filepath

    def _invoice_to_pdf_context(self, invoice: Invoice, index: int) -> dict:
        ctx = {
            "index": index,
            "receipt_type": invoice.receipt_type.value if invoice.receipt_type else "—",
            "invoice_code": invoice.invoice_code or "—",
            "invoice_number": invoice.invoice_number or "—",
            "issue_date": invoice.issue_date or "—",
            "buyer_name": invoice.buyer_name or "—",
            "seller_name": invoice.seller_name or "—",
            "total_with_tax": invoice.total_with_tax or "—",
            "tax_rate": invoice.tax_rate or "—",
            "tax_amount": invoice.tax_amount or "—",
            "fee_subcategory": invoice.fee_subcategory or "—",
            "verify_status": invoice.verify_status.value if invoice.verify_status else "—",
            "duplicate_status": invoice.duplicate_status.value if invoice.duplicate_status else "—",
            "is_image": False,
            "is_pdf": False,
            "embed_image_path": None,
            "placeholder": "原始文件缺失或无法访问",
        }
        file_path = invoice.file_path
        if not file_path or not os.path.exists(file_path):
            return ctx

        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".ofd":
            # OFD → 内嵌图片（数电票 OFD 通常含版式图）
            png_path = self._ofd_to_image(file_path)
            if png_path:
                ctx["is_image"] = True
                ctx["embed_image_path"] = png_path
                return ctx
            ctx["placeholder"] = "OFD 内嵌图片提取失败，请下载 ZIP 包查看原文件"
            return ctx

        if ext == ".pdf":
            # PDF → pdf2image (poppler) 转首页
            png_path = self._pdf_page_to_image(file_path)
            if png_path:
                ctx["is_image"] = True
                ctx["embed_image_path"] = png_path
                return ctx
            ctx["placeholder"] = "PDF 转图片失败，请下载 ZIP 包查看原文件"
            return ctx

        if ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"):
            if self._is_valid_image(file_path):
                ctx["is_image"] = True
                ctx["embed_image_path"] = file_path
                return ctx
            else:
                ctx["placeholder"] = "原始图片文件损坏，无法显示"
                return ctx

        ctx["placeholder"] = "不支持的文件格式，请下载 ZIP 包查看原文件"
        return ctx

    @staticmethod
    def _is_valid_image(file_path: str) -> bool:
        from PIL import Image
        try:
            with Image.open(file_path) as im:
                im.verify()
            return True
        except Exception:
            return False

    def _pdf_page_to_image(self, file_path: str | None) -> str | None:
        """PDF 首页 → PNG 文件路径

        优先用 pdf2image（依赖 poppler）；失败时回落到 pdftoppm 命令行
        """
        if not file_path or not os.path.exists(file_path):
            return None
        tmp_dir = os.path.join(settings.report_dir, ".tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        out_path = os.path.join(tmp_dir, f"invoice_pdf_{os.path.basename(file_path)}.png")

        # 1. 优先 pdf2image（封装 poppler）
        try:
            from pdf2image import convert_from_path
            pages = convert_from_path(file_path, first_page=1, last_page=1, dpi=150)
            if pages:
                pages[0].save(out_path, "PNG")
                return out_path
        except Exception as e:
            logger.warning(f"pdf2image failed for {file_path}: {e}, trying pdftoppm fallback")

        # 2. 回落到 pdftoppm 命令行
        try:
            import subprocess
            import shutil as _sh
            pdftoppm = _sh.which("pdftoppm")
            if not pdftoppm:
                logger.warning("pdftoppm not found in PATH")
                return None
            # pdftoppm -png -r 150 -f 1 -l 1 input.pdf prefix
            prefix = out_path.rsplit(".", 1)[0]  # 去掉 .png
            subprocess.run(
                [pdftoppm, "-png", "-r", "150", "-f", "1", "-l", "1",
                 file_path, prefix],
                timeout=30,
                capture_output=True,
                check=False,
            )
            # pdftoppm 输出 prefix-1.png
            actual = f"{prefix}-1.png"
            if os.path.exists(actual):
                os.rename(actual, out_path)
                return out_path
            # 兜底查找 prefix-*.png
            import glob
            candidates = sorted(glob.glob(f"{prefix}*.png"))
            if candidates:
                if candidates[0] != out_path:
                    os.rename(candidates[0], out_path)
                return out_path
        except Exception as e:
            logger.warning(f"pdftoppm fallback failed for {file_path}: {e}")

        return None

    def _ofd_to_image(self, file_path: str | None) -> str | None:
        """OFD → PNG 文件路径

        调用 ofd_service（ofd2img.jar + pdftoppm）渲染 OFD 为 PNG。
        jar 不可用时返回 None，由调用方决定降级处理。
        """
        if not file_path or not os.path.exists(file_path):
            return None
        try:
            from app.services.ofd_service import get_ofd_converter
            converter = get_ofd_converter()
            if not converter.is_available():
                logger.error(f"OFD 转换器不可用（jar/java/pdftoppm 缺失），无法渲染 {file_path}")
                return None

            with open(file_path, "rb") as f:
                file_data = f.read()
            png_bytes = converter.convert_to_png(file_data)
            if not png_bytes or len(png_bytes) < 1000:
                logger.error(f"OFD 转换失败: {file_path}")
                return None

            tmp_dir = os.path.join(settings.report_dir, ".tmp")
            os.makedirs(tmp_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(file_path))[0]
            out_path = os.path.join(tmp_dir, f"invoice_ofd_{base}.png")
            with open(out_path, "wb") as f:
                f.write(png_bytes)
            logger.info(f"OFD via ofdrw jar: {file_path} → {len(png_bytes)} bytes")
            return out_path
        except Exception as e:
            logger.error(f"OFD to image failed for {file_path}: {e}")
            return None

    # ===== ZIP：完整报销包 =====
    def _generate_zip(
        self,
        invoices: list[Invoice],
        reimbursement_id: int = None,
        excel_path: str = None,
        pdf_path: str = None,
    ) -> str:
        filepath = os.path.join(settings.report_dir, f"reimbursement_{reimbursement_id}.zip")

        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf:
            if excel_path and os.path.exists(excel_path):
                zf.write(excel_path, os.path.basename(excel_path))

            if pdf_path and os.path.exists(pdf_path):
                zf.write(pdf_path, os.path.basename(pdf_path))

            for idx, inv in enumerate(invoices, 1):
                if not inv.file_path or not os.path.exists(inv.file_path):
                    logger.warning(f"Invoice #{inv.id} file missing, skipping from ZIP: {inv.file_path}")
                    continue
                subcategory = _clean_filename_part(inv.fee_subcategory, "未分类")
                exp_date = inv.expense_date.isoformat() if isinstance(inv.expense_date, date) else (
                    inv.issue_date or "未知日期"
                )
                amount = str(inv.total_with_tax or "0")
                number = _clean_filename_part(inv.invoice_number, "无票号")
                ext = os.path.splitext(inv.file_path)[1].lower()
                arcname = f"原始发票/{idx:03d}_{subcategory}_{exp_date}_{amount}_{number}{ext}"
                zf.write(inv.file_path, arcname)

        return filepath
