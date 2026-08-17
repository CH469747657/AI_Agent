# 报销单模块重构设计 — 对齐模板 + 关联规则增强

**日期**：2026-08-17
**范围**：Excel 输出对齐 `报销单模板.xlsx` + 关联规则增强（用途/出差时间必填、关联前预校验）；不动前端 UI

## 背景

现有 `report_generator._generate_excel` 输出 13 列宽表（费用日期/星期/发票类型/发票代码/发票号码/销方/费用分类/金额/税率/税额/说明/验真/查重），与 `报销单模板.xlsx` 的 5 列窄表（日期/星期/补贴/其他费用及内容说明）+ 上下两段布局完全不同。需求要求新生成的报销单严格遵循模板格式，并对发票关联增加用途/出差时间必填校验。

## 现状摸底

- 周期引擎（`cycle_engine.py`）：21-20 自然月滚动，已实现 `billing_cycle`、`current_cycle_key`、`cycle_key_of`
- 补贴引擎（`subsidy_engine.py`）：60/80 标准 + 节假日判定，已实现 `recompute_subsidies`、`recompute_totals`
- 关联校验（`reimbursement_service._assert_invoice_linkable`）：已校验未重复关联 + 查重 + 验真 + 非标票据已确认
- 定时任务（`scheduler_service._cycle_lock_job`）：每月 21 日 00:05 归集游离发票 + 封账 + 生成报表
- 归集逻辑（`aggregation_service.attach_invoice_to_cycle`）：以 `expense_date`（系统三级推断）重判周期

## 模板结构

`报销单模板.xlsx` 仅 1 个 Sheet "报销单"，5 列（A=日期 / B=星期 / C=补贴 / D=其他费用 / E=内容说明），布局：

| 区域 | 行 | 列 | 内容 |
|------|-----|------|------|
| 标题 1 | 1 | A1:E1（合并） | 公司名 |
| 标题 2 | 2 | A2:E2（合并） | "项目出差报销费用清单" |
| 报销人 | 3 | A3:E3（合并） | "报销人：  XXX" |
| 周期 | 4 | A4:E4（合并） | "（2026年6月21日-7月20日）" |
| 表头 | 5 | A5/B5/C5/D5:E5（D5:E5 合并） | 日期/星期/补贴/其他费用及内容说明 |
| 上半段 | 6 ~ N | A/B/C/D/E | 一天一行，仅列有费用的天 |
| 下半段 | N+1 ~ M | D/E | 同日 ≥2 张发票的费用行（金额+说明） |
| 小计 | M+1 | B/C/D | B="小计"，C=`=SUM(C6:C{N})`，D=`=SUM(D6:D{M})` |
| 合计 | M+2 | B/C37:D37 | B="合计"，C37:D37 合并，值 `=C{小计行}+D{小计行}` |

字体：宋体 14（标题 1/2）、宋体 12（其余）。列宽：A≈15.67、B≈8.51、C≈7.49、D≈14.53、E≈38.17。全部居中、细边框。

## 数据模型变更

`app/models/invoice.py` 新增 2 列（均可空，不破坏历史数据）：

```python
business_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="出差日期（员工手动标注，用于报销单模板日期列）")
purpose: Mapped[str | None] = mapped_column(Text, nullable=True, comment="用途说明（关联报销单前必填）")
```

保留：
- `user_description`（用户附加描述）— 与 `purpose` 解耦，用途不变
- `expense_date`（系统三级推断日期）— 保留作兜底；但**报表上半段以 `business_date` 为准**
- `expense_date_source` — 保留

`ReimbursementItem.item_date` 改为存 `invoice.business_date`（关联时取自发票，**缺失时置 `None`，不兜底 `expense_date`**）；`weekday` 由 `business_date` 推算。其他模型无变更。

迁移：`backend/migrations/versions/20260817_add_invoice_business_date_purpose.py`，Alembic 加 2 列。

## 关联规则增强

`reimbursement_service._assert_invoice_linkable` 签名扩展：

```python
def _assert_invoice_linkable(
    inv: Invoice,
    *,
    cycle_start: date | None = None,
    cycle_end: date | None = None,
) -> None:
    # 1. 未关联其他报销单（现有）
    if inv.reimbursement_id is not None:
        raise HTTPException(400, f"发票 #{inv.id} 已关联到其他报销单，无法重复关联。")

    # 2. 查重：必须 UNIQUE
    if inv.duplicate_status != DuplicateStatus.unique:
        raise HTTPException(400, f"发票 #{inv.id} 查重状态为「{…}」，仅查重唯一的票据可关联。")

    # 3. 增值税专/普发票验真：必须 VALID
    if inv.receipt_type in (ReceiptType.vat_normal, ReceiptType.vat_special):
        if inv.verify_status != VerifyStatus.valid:
            raise HTTPException(400, f"发票 #{inv.id} 验真状态为「{…}」，仅验真通过的发票可关联。")

    # 4. 非标票据仍需 status=CONFIRMED（保留）
    if inv.is_nonstandard and inv.status != InvoiceStatus.confirmed:
        raise HTTPException(400, …)

    # 5. NEW 用途必填
    if not (inv.purpose and inv.purpose.strip()):
        raise HTTPException(400, f"发票 #{inv.id} 未填「用途」，关联报销单前必须补充。")

    # 6. NEW 出差时间必填
    if not inv.business_date:
        raise HTTPException(400, f"发票 #{inv.id} 未填「出差时间」，关联报销单前必须补充。")

    # 7. NEW 跨期检查：business_date 必须落在 [cycle_start, cycle_end]
    if cycle_start and cycle_end:
        if not (cycle_start <= inv.business_date <= cycle_end):
            raise HTTPException(400, f"发票 #{inv.id} 出差时间 {inv.business_date} 不在报销周期 {cycle_start}~{cycle_end} 内。")
```

调用方调整：
- `link_invoices`：把目标报销单的 `cycle_start`/`cycle_end` 透传给 `_assert_invoice_linkable`
- `aggregation_service.attach_invoice_to_cycle`：以 `business_date` 重判目标周期；`business_date` 缺失则用 `current_cycle_key` 兜底（归入当前未封账周期）+ 标 `is_late_charge=True`

## Excel 报表重写

`report_generator._generate_excel` 完全重写为模板格式。所有样式、列宽、合并、字体严格对齐 `报销单模板.xlsx`。

### 上半段行生成规则

```
对报销单的所有 ReimbursementItem 按 business_date 分组
对每个有 business_date 的天 d（且 d 落在 [cycle_start, cycle_end]）:
    weekday = d.weekday()
    day_type = day_type(d, holidays)  # workday/weekend/holiday
    rate = 60 if day_type in ("workday",) else 80
    items_that_day = [it for it in items if it.item_date == d]

    上半段一行:
        A = d (date)
        B = 星期 ["一","二","三","四","五","六","日"][weekday]
        C = rate
        if len(items_that_day) == 1:
            D = items_that_day[0].amount
            E = items_that_day[0].description or purpose
        else:  # ≥2 张
            D = ""  # 留空
            E = ""
            # 这些 items 移至下半段
```

排序：上半段按日期升序。

### 下半段行生成规则

```
对每个"同日 ≥2 张发票"的天 d（按日期升序）:
    for it in items_that_day（按 sort_order 排序）:
        D = it.amount
        E = it.description or it.fee_subcategory or ""
```

### 小计与合计

- 小计行（B 列="小计"）：C 列 `=SUM(C6:C{上半段末行})`（补贴小计），D 列 `=SUM(D6:D{下半段末行})`（费用小计）
- 合计行（B 列="合计"）：C37:D37 合并，值 `=C{小计行}+D{小计行}`（补贴小计 + 费用小计）

> 模板原合计行公式为 `=C{小计行}`（只取补贴小计），但语义上合计应为补贴+费用合计。本设计采用 `=C{小计行}+D{小计行}`。

### 样式

```python
font_normal = Font(name="宋体", size=12)
font_title  = Font(name="宋体", size=14)   # 标题 1/2
font_label  = Font(name="宋体", size=12)    # 报销人/周期/小计/合计
align_center = Alignment(horizontal="center", vertical="center")
align_center_wrap = Alignment(horizontal="center", vertical="center", wrap_text=True)
thin_border = Border(left=Side("thin"), right=Side("thin"), top=Side("thin"), bottom=Side("thin"))
```

列宽：A=15.67、B=8.51、C=7.49、D=14.53、E=38.17。

### 文件命名

保留 `reports/reimbursement_{id}.xlsx`，覆盖写入。

## 周期归集与定时任务

### attach_invoice_to_cycle 改造

```python
async def attach_invoice_to_cycle(db, invoice, today=None):
    today = today or date.today()

    # 判定日期：现有三级推断
    edate, src = determine_expense_date(invoice, today)
    invoice.expense_date = edate
    invoice.expense_date_source = src

    # 用于归入周期的日期：business_date 优先
    cycle_anchor = invoice.business_date or edate

    target_ck = cycle_key_of(cycle_anchor) if cycle_anchor else current_cycle_key(today)
    curr_ck = current_cycle_key(today)

    # 后续逻辑同现有：检查目标周期是否封账 → 归入对应报销单 → 创建明细行 → recompute_all
    # ReimbursementItem.item_date：business_date 缺失时置 None（不兜底 expense_date），
    # 这样报表上半段会自动跳过未填出差时间的明细行（见 §3.1 "上半段行生成规则"）
    item_date = invoice.business_date  # 不兜底；缺失则 None
    weekday = item_date.weekday() if item_date else None
    ...
```

未填 `business_date` 的发票（定时归集可能产生）：
- 定时归集仍把它们归入当前未封账周期，标 `is_late_charge=True`
- 明细行 `item_date = None`；报表生成时跳过这些行（不进入上下半段，金额不计入小计）
- 归集后补填 `business_date` 后 recompute 报表即可显示（届时 `ReimbursementItem.item_date` 也会被刷新）

### 定时任务时间校准

`scheduler_service._cycle_lock_job` 触发从 `CronTrigger(day=21, hour=0, minute=5)` 改为 `CronTrigger(day=21, hour=0, minute=0)`。

### 智能问数 / 手动提前生成

- `POST /api/reimbursements`（管理员手动创建）：保留，`invoice_ids` 非空时走 `_assert_invoice_linkable`（含新加的用途/出差时间/跨期校验）
- 智能问数路径（dialog intent → 调用 `create_reimbursement`）：保留，无需新增 intent
- 手动创建或智能问数触发的报销单走与定时任务一致的 Excel 生成路径，输出模板格式

## API 与服务层接口

### 新增 PATCH

```
PATCH /api/invoices/{invoice_id}/business-info
Body: { "purpose": "string|null", "business_date": "YYYY-MM-DD|null" }
```

实现：`backend/app/routers/invoices.py` 新增端点，调用 `invoice_service.update_business_info`。

校验：
- 发票存在
- 若已关联到报销单：报销单必须为 DRAFT，否则拒绝
- `business_date` 必须为合法日期

补填后：若已关联到报销单，更新对应 `ReimbursementItem.item_date` + `weekday` + `description`，并触发 `_recompute_for_reimbursement`（重算补贴与总额）。

### 修改关联接口

- `POST /api/reimbursements/{id}/invoices`：调用 `_assert_invoice_linkable` 时透传 `cycle_start`/`cycle_end`
- `POST /api/reimbursements`（手动创建）：同上

### 服务层

- `reimbursement_service._assert_invoice_linkable`：签名扩展（见上）
- `reimbursement_service.link_invoices`：透传 cycle
- `aggregation_service.attach_invoice_to_cycle`：`item_date` 优先取 `business_date`
- `invoice_service.update_business_info`（新增）

### 报表接口

`report_generator._generate_excel` 完全重写。`generate_all(reimbursement_id)` 签名不变，仍生成 Excel + PDF + ZIP。PDF 和 ZIP 不动。

### 数据库迁移

`backend/migrations/versions/20260817_add_invoice_business_date_purpose.py`：

```python
def upgrade():
    op.add_column("invoices", sa.Column("business_date", sa.Date(), nullable=True, comment="出差日期"))
    op.add_column("invoices", sa.Column("purpose", sa.Text(), nullable=True, comment="用途说明"))

def downgrade():
    op.drop_column("invoices", "purpose")
    op.drop_column("invoices", "business_date")
```

## 测试与验收

### 单元测试（`backend/tests/test_reimbursement_template.py` 新建）

1. `test_assert_invoice_linkable_rejects_missing_purpose` — 发票无 `purpose` → 拒绝
2. `test_assert_invoice_linkable_rejects_missing_business_date` — 无 `business_date` → 拒绝
3. `test_assert_invoice_linkable_rejects_out_of_cycle_business_date` — `business_date` 超周期 → 拒绝
4. `test_assert_invoice_linkable_passes_vat_normal_with_valid_verify` — 增值税普票 VALID + UNIQUE + 用途 + 出差时间 → 通过
5. `test_assert_invoice_linkable_rejects_vat_normal_without_valid_verify` — 增值税普票 PENDING → 拒绝
6. `test_assert_invoice_linkable_passes_nonstandard_confirmed` — 非标票据 CONFIRMED + 用途 + 出差时间 → 通过
7. `test_assert_invoice_linkable_rejects_duplicate_invoice` — DUPLICATE → 拒绝
8. `test_assert_invoice_linkable_rejects_already_linked` — `reimbursement_id IS NOT NULL` → 拒绝

### Excel 模板生成测试（`backend/tests/test_report_template.py` 新建）

1. `test_excel_matches_template_layout` — Sheet 标题、A1-A4、表头、字体、列宽、合并
2. `test_excel_single_invoice_per_day_keeps_in_upper_section` — 3 张发票分落 3 天 → 上半段 3 行，下半段 0 行
3. `test_excel_multi_invoice_same_day_moves_to_lower_section` — 3 张发票同天 → 上半段 1 行（D/E 空）+ 下半段 3 行
4. `test_excel_subsidy_60_for_workday_80_for_weekend_holiday` — 工作日 60、周末/节假日 80、调休补班 60
5. `test_excel_subtotal_formula_correct` — 小计行 C/D 列 SUM 公式
6. `test_excel_total_row_formula_correct` — 合计行 `=C{小计行}+D{小计行}`
7. `test_excel_only_in_cycle_dates_listed` — 跨期发票的明细行不进入上半段
8. `test_excel_missing_business_date_item_excluded` — 未填 `business_date` 的明细行不进入上下半段，金额不计入小计

### 集成测试（扩充 `backend/tests/test_aggregation_integration.py`）

1. `test_aggregate_pending_invoice_without_business_date_still_attaches_to_current_cycle` — 归集无 `business_date` 发票 → 归入当前周期 + late_charge
2. `test_aggregate_pending_invoice_with_business_date_attaches_to_correct_cycle` — `business_date` 落在下一周期 → 归入下一周期报销单
3. `test_attach_invoice_item_date_uses_business_date` — `ReimbursementItem.item_date == invoice.business_date`
4. `test_update_business_info_after_attach_recomputes` — 补填 `business_date` 后 item 更新 + 补贴重算

### 手动验收

用 `reports/reimbursement_71.xlsx` 作基线对比，手动查看新生成的 xlsx 在 Excel 中打开是否与模板视觉效果一致。

### 回归

- 现有 `backend/tests/test_*` 全量回归，确保 `_assert_invoice_linkable` 签名扩展不破坏现有调用
- `test_subsidy_engine.py`、`test_cycle_engine.py` 不受影响（这两层逻辑未动）
