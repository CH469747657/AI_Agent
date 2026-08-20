# 修复 modify_field 日期字段映射错误 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `_handle_modify_field` 把"日期"写进 `issue_date` 而非 `expense_date` 的错误，使用户修改日期后报销单费用行日期正确。

**Architecture:** 单函数改动。field_map 把"日期"/"date"从 `issue_date` 改映射到 `expense_date`；写入逻辑按字段类型分支——`expense_date` 走 `_parse_expense_date` 解析 + 同步设 `expense_date_source="note"`，其他字段保持原 `setattr` 通用路径。

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy, pytest, unittest.mock

## Global Constraints

- `_parse_expense_date` 是 `ActionExecutor` 的 `@staticmethod`，签名 `(raw: str | None) -> Optional[date]`，解析失败返回 None
- `expense_date` 是 `Date` 类型，`issue_date` 是 `varchar(20)`——写入逻辑必须按字段类型分支
- 写 `expense_date` 时必须同步设 `expense_date_source="note"`（与 `_handle_fill_invoice_desc` line 449、`_apply_indexed_descriptions` line 613 保持一致）
- 测试用 MagicMock 模式构造 invoice 和 db（参考 `backend/tests/test_modify_after_refresh.py` 的 `_make_invoice` helper）
- 不改 `_handle_upload_invoice` / `_handle_fill_invoice_desc` / `_apply_indexed_descriptions`（它们的回写逻辑已正确）

---

## File Structure

- Modify: `backend/app/dialog/action_executor.py` — `_handle_modify_field` 内 field_map（约 line 1164-1172）+ 写入逻辑（约 line 1175-1183）
- Test: `backend/tests/test_modify_field_date.py` — 新建测试文件，覆盖日期字段映射 + 解析失败 + 其他字段不受影响

---

### Task 1: 写日期字段映射失败的测试

**Files:**
- Create: `backend/tests/test_modify_field_date.py`

**Interfaces:**
- Consumes: `app.dialog.action_executor.get_action_executor`（返回 ActionExecutor 实例）、`app.dialog.models.DialogContext` / `UserRole`、`app.models.invoice.Invoice` / `ReceiptType` / `InvoiceStatus`、`_parse_expense_date` 静态方法
- Produces: 测试文件，验证 `_handle_modify_field` 对"日期"字段写入 `expense_date` 而非 `issue_date`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_modify_field_date.py`：

```python
"""修改发票日期字段映射测试

验证 _handle_modify_field 把"日期"写进 expense_date（费用发生日期）
而非 issue_date（开票日期），并同步设 expense_date_source="note"。
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.dialog.action_executor import get_action_executor
from app.dialog.models import DialogContext, UserRole
from app.models.invoice import Invoice, ReceiptType, InvoiceStatus


def _make_invoice(inv_id: int, desc: str = "测试用途", amount: str = "100.00"):
    return Invoice(
        id=inv_id,
        receipt_type=ReceiptType.vat_normal,
        seller_name="测试销售方",
        total_with_tax=amount,
        user_description=desc,
        user_id="TEST_USER",
        file_type="jpg",
        status=InvoiceStatus.reviewing,
        reimbursement_id=None,
        created_at=datetime(2026, 8, 19, 17, 4, 12),
    )


class TestModifyFieldDateMapping:
    """修改日期字段：应写 expense_date + source=note，不写 issue_date"""

    async def test_modify_date_writes_expense_date(self, mock_db):
        """用户说"日期改为2026-08-10" → expense_date=2026-08-10, source=note"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "日期")
        ctx.fill_slot("field_value", "2026-08-10")
        ctx.batch_invoice_ids = [849]

        inv = _make_invoice(849, "住宿费", "1500")
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = inv
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        # 关键断言：expense_date 被写，issue_date 不被写
        assert inv.expense_date == date(2026, 8, 10)
        assert inv.expense_date_source == "note"
        assert inv.issue_date is None or inv.issue_date == ""
        assert "2026-08-10" in result["text"]

    async def test_modify_date_chinese_format(self, mock_db):
        """用户说"8月14日" → 补当前年份，expense_date=2026-08-14"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "日期")
        ctx.fill_slot("field_value", "8月14日")
        ctx.batch_invoice_ids = [850]

        inv = _make_invoice(850, "餐饮费", "540")
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = inv
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        assert inv.expense_date == date(2026, 8, 14)
        assert inv.expense_date_source == "note"
        assert "不支持" not in result["text"]

    async def test_modify_date_invalid_format_returns_error(self, mock_db):
        """日期格式无法解析 → 返回错误提示，不写 expense_date"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "日期")
        ctx.fill_slot("field_value", "不是日期")
        ctx.batch_invoice_ids = [849]

        inv = _make_invoice(849, "住宿费", "1500")
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = inv
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        # 关键断言：不写 expense_date，返回格式错误提示
        assert inv.expense_date is None
        assert "日期格式无法解析" in result["text"]
        # 不应 commit
        mock_db.commit.assert_not_called()

    async def test_modify_other_field_uses_setattr(self, mock_db):
        """改"用途"仍走 setattr 通用路径，不受日期分支影响"""
        ctx = DialogContext(user_id="TEST_USER", role=UserRole.EMPLOYEE)
        ctx.fill_slot("invoice_index", 1)
        ctx.fill_slot("field_name", "用途")
        ctx.fill_slot("field_value", "打车费")
        ctx.batch_invoice_ids = [849]

        inv = _make_invoice(849, "住宿费", "1500")
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = inv
        mock_db.execute = AsyncMock(return_value=execute_result)
        mock_db.commit = AsyncMock()

        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, mock_db, None)

        assert inv.user_description == "打车费"
        assert "已将发票" in result["text"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_modify_field_date.py -v`

Expected: 4 个测试 FAIL
- `test_modify_date_writes_expense_date`：`inv.expense_date` 为 None（当前写的是 issue_date）
- `test_modify_date_chinese_format`：同上
- `test_modify_date_invalid_format_returns_error`：当前无格式校验，会 `setattr(invoice, "issue_date", "不是日期")` 成功，断言失败
- `test_modify_other_field_uses_setattr`：PASS（其他字段不受影响，作为回归基线）

- [ ] **Step 3: Commit 测试**

```bash
git add backend/tests/test_modify_field_date.py
git commit -m "test: 新增 modify_field 日期字段映射测试（4 用例，3 预期失败）"
```

---

### Task 2: 修复 field_map 映射和写入逻辑

**Files:**
- Modify: `backend/app/dialog/action_executor.py:1164-1183`

**Interfaces:**
- Consumes: `self._parse_expense_date`（Task 1 已验证可用）
- Produces: `_handle_modify_field` 对"日期"字段正确写 `expense_date` + `expense_date_source="note"`

- [ ] **Step 1: 修改 field_map 映射**

在 `backend/app/dialog/action_executor.py` 约 line 1164-1172，把"日期"/"date"从 `issue_date` 改为 `expense_date`：

```python
        # 映射字段名到模型属性
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

- [ ] **Step 2: 修改写入逻辑按字段类型分支**

在 `backend/app/dialog/action_executor.py` 约 line 1175-1183，把通用 `setattr` 改为对 `expense_date` 特殊处理：

```python
        if hasattr(invoice, model_attr):
            if model_attr == "expense_date":
                parsed = self._parse_expense_date(fv)
                if not parsed:
                    return {
                        "text": f"日期格式无法解析：{fv}，请用 YYYY-MM-DD 或 X月Y日 格式。",
                        "data": {},
                    }
                invoice.expense_date = parsed
                invoice.expense_date_source = "note"
            else:
                setattr(invoice, model_attr, fv)
            await db.commit()
            text = f"✅ 已将发票 #{invoice_id} 的{fn}修改为 {fv}。"
            # 仅返回本次修改的发票详情（场景B：单次操作）
            text += "\n\n" + self._build_single_invoice_table(invoice)
            return {"text": text, "data": {"invoice_id": invoice_id}}
        else:
            return {"text": f"不支持修改字段「{fn}」。可修改：金额、日期、销售方、税号、发票号、用途。", "data": {}}
```

- [ ] **Step 3: 运行测试确认通过**

Run: `docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_modify_field_date.py -v`

Expected: 4 个测试 PASS

- [ ] **Step 4: 运行回归测试**

Run: `docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_modify_after_refresh.py tests/test_batch_modify_indexed.py tests/test_action_invoice.py -v`

Expected: 全部 PASS（modify_field 其他字段路径不受影响）

- [ ] **Step 5: Commit 修复**

```bash
git add backend/app/dialog/action_executor.py
git commit -m "fix(dialog): modify_field 日期字段映射到 expense_date 而非 issue_date

用户说\"日期改为8月10日\"时，原代码写 issue_date（开票日期），
而报销单用 expense_date（费用发生日期），导致日期不生效。
改为写 expense_date + source=note，并加日期格式校验。"
```

---

### Task 3: 端到端验证 849/850 回写

**Files:**
- 无代码改动，仅手动验证

**Interfaces:**
- Consumes: Task 2 修复后的 `_handle_modify_field`、`ReportGenerator.generate_all`

- [ ] **Step 1: 复制修复后的代码到容器**

```bash
docker cp backend/app/dialog/action_executor.py ai-reimbursement-agent-backend-1:/app/app/dialog/action_executor.py
```

- [ ] **Step 2: 对 849 改日期为 8月10日**

通过对话 API 或直接 DB 操作，模拟用户对发票 849 说"日期改为8月10日"。

直接 DB 验证修复后的逻辑（绕过 LLM）：

```bash
docker exec ai-reimbursement-agent-backend-1 python -c "
import asyncio
from app.database import get_async_sessionmaker
from app.dialog.action_executor import get_action_executor
from app.dialog.models import DialogContext, UserRole

async def main():
    async with get_async_sessionmaker()() as db:
        ctx = DialogContext(user_id='EMP001', role=UserRole.EMPLOYEE)
        ctx.fill_slot('invoice_index', 1)
        ctx.fill_slot('field_name', '日期')
        ctx.fill_slot('field_value', '8月10日')
        ctx.batch_invoice_ids = [849]
        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, db, None)
        print('RESULT:', result['text'][:200])

asyncio.run(main())
"
```

Expected: 输出含"已将发票 #849 的日期修改为 8月10日"

- [ ] **Step 3: 查 DB 确认 849 回写**

```bash
docker exec ai-reimbursement-agent-db-1 psql -U reimburse -d reimbursement -c "SELECT id, expense_date, expense_date_source, issue_date FROM invoices WHERE id=849;"
```

Expected: `expense_date=2026-08-10, expense_date_source=note, issue_date` 为空

- [ ] **Step 4: 对 850 改日期为 8月14日**

```bash
docker exec ai-reimbursement-agent-backend-1 python -c "
import asyncio
from app.database import get_async_sessionmaker
from app.dialog.action_executor import get_action_executor
from app.dialog.models import DialogContext, UserRole

async def main():
    async with get_async_sessionmaker()() as db:
        ctx = DialogContext(user_id='EMP001', role=UserRole.EMPLOYEE)
        ctx.fill_slot('invoice_index', 1)
        ctx.fill_slot('field_name', '日期')
        ctx.fill_slot('field_value', '8月14日')
        ctx.batch_invoice_ids = [850]
        executor = get_action_executor()
        result = await executor._handle_modify_field(ctx, db, None)
        print('RESULT:', result['text'][:200])

asyncio.run(main())
"
```

- [ ] **Step 5: 查 DB 确认 850 回写**

```bash
docker exec ai-reimbursement-agent-db-1 psql -U reimburse -d reimbursement -c "SELECT id, expense_date, expense_date_source FROM invoices WHERE id IN (849, 850);"
```

Expected:
- 849: `expense_date=2026-08-10, source=note`
- 850: `expense_date=2026-08-14, source=note`

- [ ] **Step 6: 重新生成报销单 235 的 Excel**

```bash
docker exec ai-reimbursement-agent-backend-1 python -c "
import asyncio
from app.database import get_async_sessionmaker
from app.services.report_generator import ReportGenerator

async def main():
    async with get_async_sessionmaker()() as db:
        gen = ReportGenerator(db)
        paths = await gen.generate_all(235)
        print('PATHS:', paths)

asyncio.run(main())
"
```

- [ ] **Step 7: 校验 Excel 日期回填**

```bash
cd /Users/chen/文档2026/skill技能测试/AI报销/ai-reimbursement-agent && .venv/bin/python -c "
from openpyxl import load_workbook
wb = load_workbook('reports/reimbursement_235.xlsx')
ws = wb.active
for row in ws.iter_rows(values_only=True):
    print(row)
"
```

Expected: 费用行日期为 2026-08-10（849 住宿费）和 2026-08-14（850 餐饮费），不再堆在 8/20。补贴行 8/9-8/14 不变。

- [ ] **Step 8: 重建镜像让改动持久化**

```bash
docker compose build backend 2>&1 | tail -3
docker compose up -d backend 2>&1 | tail -3
```

等待约 35 秒（build_index 耗时），验证：

```bash
sleep 35 && curl -s -o /dev/null -w "backend health: HTTP %{http_code}\n" http://localhost:18080/health
```

Expected: HTTP 200

- [ ] **Step 9: 验证容器内代码是修复版**

```bash
docker exec ai-reimbursement-agent-backend-1 grep -n '"日期": "expense_date"' /app/app/dialog/action_executor.py
```

Expected: 输出含 `"日期": "expense_date"` 的行

---

## Self-Review

**1. Spec coverage:**
- spec 改动1（field_map 映射）→ Task 2 Step 1 ✓
- spec 改动2（写入逻辑按字段类型分支）→ Task 2 Step 2 ✓
- spec 验证用例（849/850 回写 + Excel 校验）→ Task 3 ✓
- spec 不做项（不改其他 handler、不重构 per-invoice slots）→ 未涉及，符合 ✓

**2. Placeholder scan:** 无 TBD/TODO，所有步骤含完整代码和命令 ✓

**3. Type consistency:** `_parse_expense_date` 签名 `(str | None) -> Optional[date]` 在 Task 1 测试和 Task 2 实现一致 ✓；`expense_date` / `expense_date_source` 字段名在测试、实现、DB 校验一致 ✓
