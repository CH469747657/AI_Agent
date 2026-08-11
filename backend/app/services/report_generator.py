"""报表生成服务（Excel + PDF + ZIP）

技术路线:
  Excel: openpyxl — 按报销单模板格式输出（日期/星期/油费/补贴/其他费用/公司汇款/停车费/住宿/打印/高速）
  PDF:   WeasyPrint — HTML/CSS 模板 → PDF
  ZIP:   Python zipfile — 原始票据按分类归档

数据源:
  ReimbursementItem    — 每张凭证一行（费用明细行）
  ReimbursementDaySubsidy — 每个有费用发生的天一行（补贴）
  Invoice              — 原始票据文件（用于 ZIP 打包）
"""

import os
import zipfile
import logging
from datetime import date, timedelta
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, FeeCategory
from app.models.reimbursement import (
    Reimbursement,
    ReimbursementItem,
    ReimbursementDaySubsidy,
)
from app.config import settings

logger = logging.getLogger(__name__)

# ===== 常量 =====

_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]

# 费用子类别 → Excel 列映射（列索引: A=1, B=2, ... K=11）
# 模板列: A日期 B星期 C油费 D补贴 E其他费用 F说明 G公司汇款 H停车费 I住宿 J打印 K高速
_SUBCATEGORY_COL_MAP = {
    "油费": 3,        # C
    "停车费": 8,      # H (隐藏列)
    "停车": 8,        # H
    "住宿": 9,        # I (隐藏列)
    "差旅-住宿": 9,   # I
    "打印": 10,       # J (隐藏列)
    "办公费": 10,     # J (打印/办公归入同一列)
    "高速": 11,       # K (隐藏列)
    "过路费": 11,     # K
    "公司汇款": 7,    # G
}


def _subclass_to_col(subcategory: str | None) -> int:
    """费用子类别 → Excel 列索引，默认归入 E 列（其他费用）"""
    if not subcategory:
        return 5  # E — 其他费用
    # 精确匹配
    if subcategory in _SUBCATEGORY_COL_MAP:
        return _SUBCATEGORY_COL_MAP[subcategory]
    # 模糊匹配
    for keyword, col in _SUBCATEGORY_COL_MAP.items():
        if keyword in subcategory:
            return col
    return 5  # E — 其他费用


class ReportGenerator:
    """报销报表生成器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_all(self, reimbursement_id: int) -> dict:
        """生成完整报销包：Excel + PDF + ZIP"""
        # 获取报销单
        result = await self.db.execute(
            select(Reimbursement).where(Reimbursement.id == reimbursement_id)
        )
        reimbursement = result.scalars().first()
        if not reimbursement:
            raise ValueError(f"Reimbursement #{reimbursement_id} not found")

        # 单独查询 items 和 day_subsidies（避免 relationship uselist 问题）
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

        # 获取关联的发票（用于 ZIP 打包）
        result = await self.db.execute(
            select(Invoice).where(Invoice.reimbursement_id == reimbursement_id)
        )
        invoices = list(result.scalars().all())

        # 生成三种格式（PDF 失败不阻断 Excel/ZIP）
        excel_path = self._generate_excel(reimbursement)
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
    def _generate_excel(self, reimbursement: Reimbursement) -> str:
        """生成 Excel 报销单（对齐模板格式）

        模板布局:
          行1: 公司名称（A:G 合并）
          行2: "项目出差报销费用清单"（A:G 合并）
          行3: "报销人：xxx"（A:G 合并）
          行4: "（起止时间段）"（A:G 合并）
          行5: 表头 — 日期|星期|油费|补贴|其他费用金额+说明(E:F合并)|公司汇款|停车费(隐藏)|住宿(隐藏)|打印(隐藏)|高速(隐藏)
          行6+: 数据行，按天填写
          倒数第2行: 小计（SUM公式）
          最后一行: 合计（C:E合并，SUM公式，粗体）
        """
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = "报销单"

        # === 样式定义 ===
        thin_border = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin"),
        )
        font_title = Font(name="宋体", size=14)
        font_normal = Font(name="宋体", size=12)
        font_bold = Font(name="宋体", size=12, bold=True)
        align_center = Alignment(horizontal="center", vertical="center")
        align_center_wrap = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # === 标题区（行1-4）===
        company_name = settings.company_name
        ws.merge_cells("A1:G1")
        c = ws.cell(row=1, column=1, value=company_name)
        c.font = font_title
        c.alignment = align_center

        ws.merge_cells("A2:G2")
        c = ws.cell(row=2, column=1, value="项目出差报销费用清单")
        c.font = font_title
        c.alignment = align_center

        ws.merge_cells("A3:G3")
        c = ws.cell(row=3, column=1, value=f"报销人：  {reimbursement.applicant_name or reimbursement.applicant_id}")
        c.font = font_normal
        c.alignment = align_center

        ws.merge_cells("A4:G4")
        cycle_range = self._format_cycle_range(reimbursement)
        c = ws.cell(row=4, column=1, value=cycle_range)
        c.font = font_normal
        c.alignment = align_center

        # === 表头行（行5）===
        HEADER_ROW = 5
        headers = {
            1: "日期", 2: "星期", 3: "油费", 4: "补贴",
            5: "其他费用", 6: "及内容说明", 7: "公司汇款",
            8: "停车费", 9: "住宿", 10: "打印", 11: "高速",
        }
        # E5:F5 合并 → "其他费用及内容说明"
        ws.merge_cells(start_row=HEADER_ROW, start_column=5, end_row=HEADER_ROW, end_column=6)
        ws.cell(row=HEADER_ROW, column=5, value="其他费用及内容说明")

        for col, label in headers.items():
            if col == 6:
                continue  # 合并到 E
            cell = ws.cell(row=HEADER_ROW, column=col, value=label)
            cell.font = font_normal
            cell.alignment = align_center
            cell.border = thin_border
        # 合并区域 E5 也需要边框
        ws.cell(row=HEADER_ROW, column=5).border = thin_border
        ws.cell(row=HEADER_ROW, column=6).border = thin_border

        # === 数据行 ===
        # 将 items 和 day_subsidies 按日期聚合
        rows_data = self._merge_items_and_subsidies(reimbursement)

        DATA_START = HEADER_ROW + 1  # 行6
        for i, row_info in enumerate(rows_data):
            row_num = DATA_START + i
            # A: 日期
            if row_info["date"]:
                cell = ws.cell(row=row_num, column=1, value=row_info["date"])
                cell.number_format = "m/d"
            # B: 星期
            cell = ws.cell(row=row_num, column=2, value=row_info["weekday_str"] or "")
            # C-K: 各列金额
            for col_idx, amount in row_info["amounts"].items():
                if amount and amount != 0:
                    cell = ws.cell(row=row_num, column=col_idx, value=amount)
            # F: 说明（描述）
            if row_info["description"]:
                cell = ws.cell(row=row_num, column=6, value=row_info["description"])
                cell.alignment = align_center_wrap

            # 给整行加边框
            for col in range(1, 12):
                cell = ws.cell(row=row_num, column=col)
                cell.border = thin_border
                if col == 6 and row_info["description"]:
                    cell.alignment = align_center_wrap
                else:
                    cell.alignment = align_center
                if not cell.font or cell.font.name != "宋体":
                    cell.font = font_normal

        # === 小计行 ===
        data_end_row = DATA_START + len(rows_data) - 1  # 最后一条数据行
        if len(rows_data) == 0:
            data_end_row = DATA_START  # 空数据时 SUM 范围 = 空行 → 0
        subtotal_row = data_end_row + 1
        # 空行后放小计（如果数据区不满）
        cell = ws.cell(row=subtotal_row, column=2, value="小计")
        cell.font = font_bold
        cell.alignment = align_center
        # SUM 公式 — 每列
        col_letters = {3: "C", 4: "D", 5: "E", 7: "G", 8: "H", 9: "I", 10: "J", 11: "K"}
        for col_idx, letter in col_letters.items():
            if len(rows_data) == 0:
                formula = 0
            else:
                formula = f"=SUM({letter}{DATA_START}:{letter}{data_end_row})"
            cell = ws.cell(row=subtotal_row, column=col_idx, value=formula)
            cell.font = font_normal
            cell.alignment = align_center
        for col in range(1, 12):
            ws.cell(row=subtotal_row, column=col).border = thin_border
            if not ws.cell(row=subtotal_row, column=col).font or ws.cell(row=subtotal_row, column=col).font.name != "宋体":
                ws.cell(row=subtotal_row, column=col).font = font_normal

        # === 合计行 ===
        total_row = subtotal_row + 1
        ws.merge_cells(start_row=total_row, start_column=3, end_row=total_row, end_column=5)
        cell = ws.cell(row=total_row, column=2, value="合计")
        cell.font = font_bold
        cell.alignment = align_center
        # C{total} = SUM(C{subtotal}:E{subtotal}) → 合计 = 油费+补贴+其他费用 小计之和
        formula = f"=SUM(C{subtotal_row}:E{subtotal_row})"
        cell = ws.cell(row=total_row, column=3, value=formula)
        cell.font = font_bold
        cell.alignment = align_center
        # G 列公司汇款合计
        cell = ws.cell(row=total_row, column=7, value=f"=G{subtotal_row}")
        cell.font = font_normal
        cell.alignment = align_center
        for col in range(1, 12):
            ws.cell(row=total_row, column=col).border = thin_border

        # === 列宽 ===
        col_widths = {
            "A": 15.5,  # 日期
            "B": 8.5,   # 星期
            "C": 9.5,   # 油费
            "D": 7.5,   # 补贴
            "E": 14.5,  # 其他费用金额
            "F": 38.0,  # 费用内容说明
            "G": 11.0,  # 公司汇款
            "H": 11.5,  # 停车费（隐藏）
            "I": 9.0,   # 住宿（隐藏）
            "J": 9.0,   # 打印（隐藏）
            "K": 9.0,   # 高速（隐藏）
        }
        for col_letter, width in col_widths.items():
            ws.column_dimensions[col_letter].width = width

        # 隐藏 H/I/J/K 列
        for col_letter in ["H", "I", "J", "K"]:
            ws.column_dimensions[col_letter].hidden = True

        # === 保存 ===
        filepath = os.path.join(settings.report_dir, f"reimbursement_{reimbursement.id}.xlsx")
        wb.save(filepath)
        return filepath

    def _merge_items_and_subsidies(self, reimbursement: Reimbursement) -> list[dict]:
        """将 ReimbursementItem 和 ReimbursementDaySubsidy 按日期合并为表格行

        遍历整个报销周期（cycle_start → cycle_end）的每一天，
        有费用的日期填入金额，无费用的日期保留空行（仅日期+星期）。

        返回: [{"date": date|None, "weekday_str": str, "amounts": {col_idx: amount}, "description": str}]
        """
        items = getattr(reimbursement, "_items_cache", None) or []
        items: list[ReimbursementItem] = sorted(
            items, key=lambda x: (x.item_date or date.min, x.sort_order)
        )
        subsidies = getattr(reimbursement, "_day_subsidies_cache", None) or []
        subsidies: list[ReimbursementDaySubsidy] = sorted(
            subsidies, key=lambda x: x.subsidy_date
        )

        # 按日期分组合并 items
        date_items: dict[date, list[ReimbursementItem]] = defaultdict(list)
        no_date_items: list[ReimbursementItem] = []
        for item in items:
            if item.item_date:
                date_items[item.item_date].append(item)
            else:
                no_date_items.append(item)

        # 按日期分组 subsidies（只取 included=True）
        date_subsidies: dict[date, ReimbursementDaySubsidy] = {}
        for sub in subsidies:
            if sub.included and sub.subsidy_date:
                date_subsidies[sub.subsidy_date] = sub

        # 生成周期内所有日期（从 cycle_start 到 cycle_end 逐日遍历）
        cycle_start = reimbursement.cycle_start
        cycle_end = reimbursement.cycle_end
        if cycle_start and cycle_end:
            cycle_dates = []
            current = cycle_start
            while current <= cycle_end:
                cycle_dates.append(current)
                current += timedelta(days=1)
        else:
            # 无周期信息时退回旧行为：只列出有数据的日期
            cycle_dates = sorted(set(list(date_items.keys()) + list(date_subsidies.keys())))

        # 收集周期外的日期（有 items 或 subsidies 但不在周期范围内）
        all_expense_dates = set(date_items.keys()) | set(date_subsidies.keys())
        out_of_cycle_dates = sorted(all_expense_dates - set(cycle_dates))

        rows = []
        # 1. 周期内逐日遍历
        for d in cycle_dates:
            row = self._build_row_for_date(d, date_items, date_subsidies)
            rows.append(row)

        # 2. 周期外的有日期费用/补贴，追加在周期行之后
        for d in out_of_cycle_dates:
            row = self._build_row_for_date(d, date_items, date_subsidies)
            rows.append(row)

        # 3. 无日期的 items 追加到末尾（汇总性条目）
        for item in no_date_items:
            row = {
                "date": None,
                "weekday_str": "",
                "amounts": {},
                "description": "",
            }
            col = _subclass_to_col(item.fee_subcategory)
            amount = float(item.amount) if item.amount else 0
            row["amounts"][col] = amount
            if item.description:
                desc = item.description
                if item.is_late_charge:
                    desc = f"[跨期] {desc}"
                row["description"] = desc
            rows.append(row)

        return rows

    @staticmethod
    def _build_row_for_date(
        d: date,
        date_items: dict,
        date_subsidies: dict,
    ) -> dict:
        """为指定日期构建一行数据（费用 + 补贴）"""
        row = {
            "date": d,
            "weekday_str": _WEEKDAY_CN[d.weekday()] if d else "",
            "amounts": {},
            "description": "",
        }
        # 补贴 → D 列(4)
        sub = date_subsidies.get(d)
        if sub and sub.subsidy_amount:
            row["amounts"][4] = float(sub.subsidy_amount)

        # 费用明细
        day_items = date_items.get(d, [])
        descriptions = []
        for item in day_items:
            col = _subclass_to_col(item.fee_subcategory)
            amount = float(item.amount) if item.amount else 0
            if col in row["amounts"]:
                row["amounts"][col] += amount
            else:
                row["amounts"][col] = amount
            if item.description:
                desc = item.description
                if item.is_late_charge:
                    desc = f"[跨期] {desc}"
                descriptions.append(desc)

        if descriptions:
            row["description"] = "；".join(descriptions)

        return row

    def _format_cycle_range(self, reimbursement: Reimbursement) -> str:
        """格式化周期时间段为中文: （2026年6月21日-7月20日）"""
        start = reimbursement.cycle_start
        end = reimbursement.cycle_end
        if not start or not end:
            if reimbursement.cycle_key:
                return f"（{reimbursement.cycle_key}）"
            if reimbursement.period:
                return f"（{reimbursement.period}）"
            return ""
        # 格式: （2026年6月21日-7月20日）
        start_str = f"{start.year}年{start.month}月{start.day}日"
        if start.year == end.year:
            end_str = f"{end.month}月{end.day}日"
        else:
            end_str = f"{end.year}年{end.month}月{end.day}日"
        return f"（{start_str}-{end_str}）"

    # ===== PDF 报表 =====
    async def _generate_pdf(self, reimbursement: Reimbursement, invoices: list[Invoice]) -> str:
        """生成 PDF 明细报告（HTML → PDF）"""
        from weasyprint import HTML
        from jinja2 import Template

        _items = getattr(reimbursement, "_items_cache", None) or []
        items = sorted(
            _items,
            key=lambda x: (x.item_date or date.min, x.sort_order)
        )
        _subs = getattr(reimbursement, "_day_subsidies_cache", None) or []
        subsidies = sorted(
            _subs,
            key=lambda x: x.subsidy_date
        )

        expense_total = float(reimbursement.expense_total or 0)
        subsidy_total = float(reimbursement.subsidy_total or 0)
        total_amount = float(reimbursement.total_amount or (expense_total + subsidy_total))

        html_template = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 2cm; }
body { font-family: "Noto Sans CJK SC", "SimHei", sans-serif; }
.cover { text-align: center; padding: 60px 0; }
.cover h1 { font-size: 22pt; color: #1a5276; margin-bottom: 20px; }
.cover p { font-size: 13pt; margin: 8px 0; }
.amount-summary { margin: 20px 0; display: flex; justify-content: center; gap: 40px; }
.amount-box { text-align: center; }
.amount-box .label { font-size: 11pt; color: #666; }
.amount-box .value { font-size: 18pt; font-weight: bold; margin-top: 4px; }
.amount-box.total .value { color: #e74c3c; }
.summary { margin: 30px 0; }
.summary h2 { font-size: 14pt; color: #333; border-bottom: 2px solid #4472C4; padding-bottom: 4px; }
.summary table { width: 100%; border-collapse: collapse; margin: 10px 0; }
.summary th { background: #4472C4; color: white; padding: 6px 8px; text-align: center; font-size: 11pt; }
.summary td { border: 1px solid #ddd; padding: 5px 8px; font-size: 11pt; text-align: center; }
.summary td.desc { text-align: left; }
.late-charge { color: #e74c3c; font-size: 10pt; }
.subsidy-included { color: #27ae60; }
.subsidy-excluded { color: #999; text-decoration: line-through; }
</style></head><body>
<div class="cover">
  <h1>{{ company_name }}<br/>项目出差报销费用清单</h1>
  <p>报销人：{{ applicant_name }}</p>
  {% if department %}<p>部门：{{ department }}</p>{% endif %}
  <p>周期：{{ cycle_range }}</p>
  {% if reason %}<p>报销事由：{{ reason }}</p>{% endif %}
  <div class="amount-summary">
    <div class="amount-box"><div class="label">费用合计</div><div class="value">¥{{ expense_total }}</div></div>
    <div class="amount-box"><div class="label">补贴合计</div><div class="value">¥{{ subsidy_total }}</div></div>
    <div class="amount-box total"><div class="label">总金额</div><div class="value">¥{{ total_amount }}</div></div>
  </div>
</div>

<div class="summary">
  <h2>费用明细</h2>
  <table>
    <thead>
      <tr><th>日期</th><th>星期</th><th>费用子类</th><th>金额</th><th>说明</th></tr>
    </thead>
    <tbody>
      {% for item in items %}
      <tr>
        <td>{{ item.item_date_str }}</td>
        <td>{{ item.weekday_str }}</td>
        <td>{{ item.fee_subcategory or '其他' }}</td>
        <td>¥{{ item.amount_str }}</td>
        <td class="desc">{{ item.description or '' }}{% if item.is_late_charge %} <span class="late-charge">[跨期]</span>{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<div class="summary">
  <h2>日补贴明细</h2>
  <table>
    <thead>
      <tr><th>日期</th><th>星期</th><th>日类型</th><th>标准</th><th>补贴金额</th><th>状态</th></tr>
    </thead>
    <tbody>
      {% for sub in subsidies %}
      <tr>
        <td>{{ sub.date_str }}</td>
        <td>{{ sub.weekday_str }}</td>
        <td>{{ sub.day_type }}</td>
        <td>¥{{ sub.base_rate }}</td>
        <td>{{ sub.subsidy_class }}</td>
        <td>{% if sub.included %}<span class="subsidy-included">已计入</span>{% else %}<span class="subsidy-excluded">已取消</span>{% if sub.exclude_reason %}（{{ sub.exclude_reason }}）{% endif %}{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
</body></html>"""

        def _weekday_str(wd):
            if wd is None:
                return ""
            return _WEEKDAY_CN[wd] if 0 <= wd <= 6 else ""

        def _day_type_label(dt):
            labels = {"workday": "工作日", "rest_day": "休息日", "holiday": "法定节假日", "adjusted_workday": "调休补班"}
            return labels.get(dt, dt or "—")

        html_content = Template(html_template).render(
            company_name=settings.company_name,
            applicant_name=reimbursement.applicant_name or reimbursement.applicant_id,
            department=reimbursement.department or "",
            cycle_range=self._format_cycle_range(reimbursement).strip("（）") or reimbursement.cycle_key or "",
            reason=reimbursement.reason or "",
            expense_total=f"{expense_total:.2f}",
            subsidy_total=f"{subsidy_total:.2f}",
            total_amount=f"{total_amount:.2f}",
            items=[{
                "item_date_str": item.item_date.strftime("%m/%d") if item.item_date else "—",
                "weekday_str": _weekday_str(item.weekday) if item.weekday is not None else (
                    _WEEKDAY_CN[item.item_date.weekday()] if item.item_date else ""
                ),
                "fee_subcategory": item.fee_subcategory,
                "amount_str": f"{float(item.amount):.2f}" if item.amount else "0.00",
                "description": item.description or "",
                "is_late_charge": item.is_late_charge,
            } for item in items],
            subsidies=[{
                "date_str": sub.subsidy_date.strftime("%m/%d") if sub.subsidy_date else "—",
                "weekday_str": _weekday_str(sub.weekday) if sub.weekday is not None else (
                    _WEEKDAY_CN[sub.subsidy_date.weekday()] if sub.subsidy_date else ""
                ),
                "day_type": _day_type_label(sub.day_type),
                "base_rate": f"{float(sub.base_rate):.0f}" if sub.base_rate else "—",
                "subsidy_class": f"¥{float(sub.subsidy_amount):.2f}" if sub.subsidy_amount else "¥0.00",
                "included": sub.included,
                "exclude_reason": sub.exclude_reason,
            } for sub in subsidies],
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
        """打包完整报销包：Excel 报销单 + PDF 明细 + 原始发票"""
        suffix = f"_{reimbursement_id}" if reimbursement_id else ""
        filepath = os.path.join(settings.report_dir, f"reimbursement{suffix}.zip")

        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Excel 报销单
            if excel_path and os.path.exists(excel_path):
                zf.write(excel_path, os.path.basename(excel_path))

            # 2. PDF 明细
            if pdf_path and os.path.exists(pdf_path):
                zf.write(pdf_path, os.path.basename(pdf_path))

            # 3. 原始发票（按分类归档到子目录）
            for inv in invoices:
                if not inv.file_path or not os.path.exists(inv.file_path):
                    continue
                cat = inv.fee_subcategory or "未分类"
                exp_date = inv.expense_date or inv.issue_date or "未知日期"
                amount = inv.total_with_tax or "0"
                num = inv.invoice_number or "无票号"
                ext = os.path.splitext(inv.file_path)[1]
                arcname = f"原始发票/{cat}_{exp_date}_{amount}_{num}{ext}"
                zf.write(inv.file_path, arcname)

        return filepath
