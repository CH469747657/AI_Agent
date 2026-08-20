# 修复 modify_field 日期字段映射错误

## 背景

智能问数对话框里，用户通过 `emp_modify_field` 意图修改发票"日期"字段时，系统写入的是 `invoices.issue_date`（开票日期，varchar），而生成报销单明细行用的是 `invoices.expense_date`（费用发生日期，date）。两者脱节导致：

- 用户说"日期改为8月10日"，`issue_date` 被改，`expense_date` 不变
- 生成报销单时 `determine_expense_date` 三级判定仍走 upload_time 兜底
- Excel 报表费用行日期错误（填成上传日期而非用户指定日期）

## 根因

`backend/app/dialog/action_executor.py` 的 `_handle_modify_field`（约 line 1164-1172）field_map：

```python
field_map = {
    ...
    "日期": "issue_date", "date": "issue_date",   # ← 错误映射
    ...
}
```

"日期"在报销业务语境下指费用发生日期（`expense_date`），不是开票日期（`issue_date`）。

## 修复方案

### 改动 1：field_map 映射

`"日期"` 和 `"date"` 从 `issue_date` 改为 `expense_date`：

```python
field_map = {
    "金额": "total_with_tax", "amount": "total_with_tax",
    "日期": "expense_date", "date": "expense_date",
    "销售方": "seller_name", "seller": "seller_name",
    "税号": "seller_tax_id", "tax_id": "seller_tax_id",
    "发票号": "invoice_number", "invoice_number": "invoice_number",
    "用途": "user_description", "description": "user_description",
    "备注": "user_description",
}
```

### 改动 2：写入逻辑按字段类型分支

当前 line 1175-1177 是通用 `setattr(invoice, model_attr, fv)`，但 `expense_date` 是 date 类型、`field_value` 是字符串，需特殊处理：

```python
if model_attr == "expense_date":
    parsed = self._parse_expense_date(fv)
    if not parsed:
        return {"text": f"日期格式无法解析：{fv}，请用 YYYY-MM-DD 或 X月Y日 格式。", "data": {}}
    invoice.expense_date = parsed
    invoice.expense_date_source = "note"
else:
    setattr(invoice, model_attr, fv)
await db.commit()
```

写 `expense_date` 时同步设 `expense_date_source="note"`（用户口述来源），与 `_handle_fill_invoice_desc`（line 449）和 `_apply_indexed_descriptions`（line 613）保持一致。

## 不做

- 不改 `_handle_upload_invoice` / `_handle_fill_invoice_desc` / `_apply_indexed_descriptions`（它们的 `expense_date` 回写逻辑已正确）
- 不重构 per-invoice slots（dialog context 状态模型改动，超出本次范围）
- 不加"开票日期"别名（YAGNI，当前无此需求）
- 不改 `issue_date` 的其他写入路径（OCR/VLM 提取仍写 issue_date，正确）

## 验证

### 用例：849/850 回写

1. 对话框对发票 849 说"日期改为8月10日"
2. 查 DB：`invoices.expense_date=2026-08-10, expense_date_source=note`（849）
3. 对 850 说"日期改为8月14日"
4. 查 DB：`invoices.expense_date=2026-08-14, expense_date_source=note`（850）
5. 重新生成报销单 235 的 Excel
6. 校验 Excel：849 费用行在 8/10、850 费用行在 8/14，不再堆在 8/20

### 回归

- `emp_modify_field` 改其他字段（金额/销售方/税号/发票号/用途）仍走 `setattr` 通用路径，不受影响
- 现有 `test_aggregate_reports.py` / `test_subsidy_engine.py` 不涉及 modify_field，不受影响

## 影响文件

- `backend/app/dialog/action_executor.py` — `_handle_modify_field` 内 field_map + 写入逻辑（约 15 行）
