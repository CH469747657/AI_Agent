"""一次性脚本：根据数据库已有发票数据，按模板格式生成每个人的报销单 Excel

用法：
    docker exec ai-reimbursement-agent-backend-1 python /app/scripts/generate_template_reimbursements.py
    或本地：
    cd backend && python scripts/generate_template_reimbursements.py

输出：reports/template/<applicant_id>_<cycle_key>.xlsx
"""

import os
import sys
import asyncio
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

# 让 backend 模块可导入
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from sqlalchemy import select

from app.database import get_async_sessionmaker
from app.models.reimbursement import (
    Reimbursement,
    ReimbursementItem,
    ReimbursementDaySubsidy,
)
from app.models.invoice import Invoice
from app.models.holiday import Holiday
from app.services.subsidy_engine import day_type, subsidy_rate
from app.config import settings


WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


def _fmt_cycle_range(reimb: Reimbursement) -> str:
    """（2026年6月21日-7月20日）"""
    s, e = reimb.cycle_start, reimb.cycle_end
    if not s or not e:
        return ""
    s_str = f"{s.year}年{s.month}月{s.day}日"
    e_str = f"{e.year}年{e.month}月{e.day}日" if s.year != e.year else f"{e.month}月{e.day}日"
    return f"（{s_str}-{e_str}）"


def _fmt_date(d: date) -> str:
    """'2026年7月29日' — 不，模板里 A 列填的是 Excel 日期序列号（数字）+ 单元格 number_format。我们直接放 date 对象，让 openpyxl 自动序列化"""
    return d.isoformat() if d else ""


def _parse_amount(val) -> float:
    if not val:
        return 0.0
    try:
        return float(str(val).replace(",", "").replace("￥", "").replace("¥", "").replace("元", ""))
    except (ValueError, TypeError):
        return 0.0


def build_xlsx(reimb: Reimbursement, items: list, holidays: dict) -> str:
    """生成模板格式的 xlsx 文件

    items: list[ReimbursementItem] — 已按 sort_order 排序
    holidays: {date: "holiday"|"workday"}
    返回：xlsx 文件路径
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "报销单"

    # —— 样式 ——
    thin = Side(style="thin")
    thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    font_title = Font(name="宋体", size=14)
    font_normal = Font(name="宋体", size=12)
    align_center = Alignment(horizontal="center", vertical="center")
    align_center_wrap = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # —— 1-4 行：标题 + 报销人 + 周期 ——
    ws.merge_cells("A1:E1")
    c = ws.cell(row=1, column=1, value=settings.company_name)
    c.font = font_title
    c.alignment = align_center

    ws.merge_cells("A2:E2")
    c = ws.cell(row=2, column=1, value="项目出差报销费用清单")
    c.font = font_title
    c.alignment = align_center

    ws.merge_cells("A3:E3")
    applicant = reimb.applicant_name or reimb.applicant_id
    c = ws.cell(row=3, column=1, value=f"报销人：  {applicant}")
    c.font = font_normal
    c.alignment = align_center

    ws.merge_cells("A4:E4")
    c = ws.cell(row=4, column=1, value=_fmt_cycle_range(reimb))
    c.font = font_normal
    c.alignment = align_center
    c.border = thin_border

    # —— 第 5 行：表头 ——
    ws.cell(row=5, column=1, value="日期").font = font_normal
    ws.cell(row=5, column=2, value="星期").font = font_normal
    ws.cell(row=5, column=3, value="补贴").font = font_normal
    ws.merge_cells("D5:E5")
    ws.cell(row=5, column=4, value="其他费用及内容说明").font = font_normal
    for col in range(1, 6):
        cell = ws.cell(row=5, column=col)
        cell.alignment = align_center_wrap
        cell.border = thin_border

    # —— 数据行构建 ——
    # 仅保留 item_date 落在周期内的明细
    in_cycle_items = []
    for it in items:
        if not it.item_date:
            continue
        if reimb.cycle_start and reimb.cycle_end:
            if not (reimb.cycle_start <= it.item_date <= reimb.cycle_end):
                continue
        in_cycle_items.append(it)

    # 按日期分组
    by_date: dict[date, list] = defaultdict(list)
    for it in in_cycle_items:
        by_date[it.item_date].append(it)

    upper_rows = []  # [(date, weekday_str, rate, amount_or_empty, desc_or_empty)]
    lower_rows = []  # [(amount, desc)]
    for d in sorted(by_date.keys()):
        its = by_date[d]
        # 排序：按 sort_order
        its.sort(key=lambda x: x.sort_order or 0)
        wd = WEEKDAY_CN[d.weekday()]
        dt = day_type(d, holidays)
        rate = 60 if dt == "workday" else 80

        if len(its) == 1:
            it = its[0]
            amt = float(it.amount) if it.amount is not None else 0.0
            desc = it.description or it.fee_subcategory or ""
            upper_rows.append((d, wd, rate, amt, desc))
        else:
            # ≥2 张：上半段 D/E 留空，所有 items 移到下半段
            upper_rows.append((d, wd, rate, None, None))
            for it in its:
                amt = float(it.amount) if it.amount is not None else 0.0
                desc = it.description or it.fee_subcategory or ""
                lower_rows.append((amt, desc))

    # —— 写入上半段 ——
    row = 6
    upper_first = row
    for d, wd, rate, amt, desc in upper_rows:
        ws.cell(row=row, column=1, value=d).font = font_normal
        ws.cell(row=row, column=1).number_format = "yyyy-mm-dd"
        ws.cell(row=row, column=2, value=wd).font = font_normal
        ws.cell(row=row, column=3, value=rate).font = font_normal
        if amt is not None:
            ws.cell(row=row, column=4, value=amt).font = font_normal
            ws.cell(row=row, column=4).number_format = "0.00"
        if desc:
            ws.cell(row=row, column=5, value=desc).font = font_normal
        for col in range(1, 6):
            cell = ws.cell(row=row, column=col)
            cell.alignment = align_center_wrap if col == 5 else align_center
            cell.border = thin_border
        row += 1
    upper_last = row - 1

    # —— 写入下半段 ——
    lower_first = row
    for amt, desc in lower_rows:
        ws.cell(row=row, column=4, value=amt).font = font_normal
        ws.cell(row=row, column=4).number_format = "0.00"
        ws.cell(row=row, column=5, value=desc).font = font_normal
        ws.cell(row=row, column=4).alignment = align_center
        ws.cell(row=row, column=5).alignment = align_center_wrap
        ws.cell(row=row, column=4).border = thin_border
        ws.cell(row=row, column=5).border = thin_border
        row += 1
    lower_last = row - 1

    # —— 小计行 ——
    subtotal_row = row
    ws.cell(row=subtotal_row, column=2, value="小计").font = font_normal
    ws.cell(row=subtotal_row, column=2).alignment = align_center
    # 补贴小计（C 列）：SUM 从 upper_first 到 upper_last
    if upper_first <= upper_last:
        ws.cell(row=subtotal_row, column=3, value=f"=SUM(C{upper_first}:C{upper_last})").font = font_normal
    else:
        ws.cell(row=subtotal_row, column=3, value=0).font = font_normal
    ws.cell(row=subtotal_row, column=3).alignment = align_center
    # 费用小计（D 列）：SUM 从 upper_first 到 lower_last（连续区间）
    if upper_first <= lower_last:
        ws.cell(row=subtotal_row, column=4, value=f"=SUM(D{upper_first}:D{lower_last})").font = font_normal
    else:
        ws.cell(row=subtotal_row, column=4, value=0).font = font_normal
    ws.cell(row=subtotal_row, column=4).alignment = align_center
    for col in range(1, 6):
        ws.cell(row=subtotal_row, column=col).border = thin_border

    # —— 合计行 ——
    total_row = subtotal_row + 1
    ws.cell(row=total_row, column=2, value="合计").font = font_normal
    ws.cell(row=total_row, column=2).alignment = align_center
    ws.merge_cells(start_row=total_row, start_column=3, end_row=total_row, end_column=4)
    ws.cell(row=total_row, column=3, value=f"=C{subtotal_row}+D{subtotal_row}").font = font_normal
    ws.cell(row=total_row, column=3).alignment = align_center
    for col in range(1, 6):
        ws.cell(row=total_row, column=col).border = thin_border

    # —— 列宽（与模板一致）——
    ws.column_dimensions["A"].width = 15.67
    ws.column_dimensions["B"].width = 8.51
    ws.column_dimensions["C"].width = 7.49
    ws.column_dimensions["D"].width = 14.53
    ws.column_dimensions["E"].width = 38.17

    # —— 输出 ——
    out_dir = os.path.join(settings.report_dir, "template")
    os.makedirs(out_dir, exist_ok=True)
    name_part = (reimb.applicant_id or "unknown").replace("/", "_")
    fname = f"{name_part}_{reimb.cycle_key or 'noperiod'}.xlsx"
    out_path = os.path.join(out_dir, fname)
    wb.save(out_path)
    return out_path


async def main():
    sm = get_async_sessionmaker()
    async with sm() as db:
        # 仅处理有 cycle_key 的报销单
        result = await db.execute(
            select(Reimbursement).where(Reimbursement.cycle_key.isnot(None)).order_by(
                Reimbursement.applicant_id, Reimbursement.cycle_start
            )
        )
        reimbursements = list(result.scalars().all())

        if not reimbursements:
            print("No cycle-bound reimbursements found.")
            return

        # 一次性加载所有节假日（2024-2027 兜底）
        result = await db.execute(
            select(Holiday).where(Holiday.holiday_date >= date(2024, 1, 1))
        )
        holidays = {h.holiday_date: h.day_type for h in result.scalars().all()}

        total_files = 0
        for reimb in reimbursements:
            # 加载明细行
            result = await db.execute(
                select(ReimbursementItem)
                .where(ReimbursementItem.reimbursement_id == reimb.id)
                .order_by(ReimbursementItem.sort_order, ReimbursementItem.item_date)
            )
            items = list(result.scalars().all())

            if not items:
                print(f"  [SKIP] 报销单 #{reimb.id} ({reimb.applicant_id} {reimb.cycle_key}) 无明细行")
                continue

            out_path = build_xlsx(reimb, items, holidays)
            total_files += 1
            print(f"  [OK] #{reimb.id:3d} {reimb.applicant_id:20s} {reimb.cycle_key} → {out_path}")

        print(f"\n生成完成：共 {total_files} 个文件，输出目录 {os.path.join(settings.report_dir, 'template')}")


if __name__ == "__main__":
    asyncio.run(main())
