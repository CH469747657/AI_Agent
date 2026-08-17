# 报销单补贴计算规则调整 — 员工自主上报出差日 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把补贴触发源从"发票费用发生日"改为"员工在对话框标记的出差日"，新增 `reimbursement_travel_days` 表 + 5 个 API + 月历弹层组件。

**Architecture:** 后端新增 `ReimbursementTravelDay` 模型 + `/api/portal/travel-days/*` 端点，员工端用 `get_current_employee_async` 鉴权；`subsidy_engine.recompute_subsidies` 改读 `travel_days` 而非 `items.item_date`，签名/调用方不动；`reimbursement_service.serialize_reimbursement_detail` 加 `travel_days` 字段；前端新组件 `TravelDayPicker` 月历弹层多选，在 `ChatWidget` 输入区加日历按钮（仅 employee role），三端报销单详情加"出差日" section。迁移策略 A：按现有 `day_subsidies` 回填 `travel_days`。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (async) + Alembic + pytest (后端) / React + TypeScript + Vite + Tailwind + phosphor-icons (前端)

## Global Constraints

- 周期范围规则：周期键 `YYYY-MM`，周期起止按 21 日切（`cycle_engine.billing_cycle(cycle_key)` → `(date, date)`，如 `"2026-08"` → `(date(2026,7,21), date(2026,8,20))`）
- 员工鉴权用 `get_current_employee_async`（来自 `app.routers.portal_auth`，返回 `Employee` 对象，含 `.employee_no` / `.id` / `.name` / `.department`）
- 周期归属用 `cycle_key_of(d: date) -> str`（费用发生日所属周期键），`current_cycle_key(today) -> str`（当前周期键）
- 获取/创建报销单用 `aggregation_service.get_or_create_reimbursement(db, applicant_id, cycle_key)` → `Reimbursement`
- 补贴标准：工作日 60 / 节假日 80，`subsidy_engine.WORKDAY_RATE = Decimal("60")` / `RESTDAY_RATE = Decimal("80")`
- Alembic 迁移文件命名：`00NN_描述.py`，当前最新是 `0006_verify_settings.py`，下一个用 `0007_reimbursement_travel_days.py`
- 前端 design-system 颜色：`bg-background`/`bg-muted`/`border-border`/`text-foreground`/`text-muted-foreground`/`bg-primary-700`/`text-primary-700`/`bg-primary-50`，按钮 phosphor-icons
- `boss` role 已识别（`ChatWidget.useRoleAndUserId` 已加 `/boss/*` 分支），日历按钮只对 `role === "employee"` 渲染
- 现有 `subsidy_engine.recompute_subsidies(db, reimbursement, holidays=None)` 签名保留，只改内部数据源
- `serialize_reimbursement_detail` 现已返回 `items` / `day_subsidies` / `attachments`，新加 `travel_days` 字段
- Alembic head 已迁移到 `0006`，本计划新建 `0007`

---

## 文件结构

### 后端

| 文件 | 责任 |
|---|---|
| `backend/app/models/reimbursement.py` (修改) | 加 `ReimbursementTravelDay` 模型类 |
| `backend/alembic/versions/0007_reimbursement_travel_days.py` (新建) | 建表 + 数据迁移（按 day_subsidies 回填） |
| `backend/app/schemas/__init__.py` (修改) | 加 `TravelDayCreateRequest` / `TravelDayResponse` |
| `backend/app/routers/travel_days.py` (新建) | 5 个端点：员工 GET/POST/DELETE × 2 + 管理端 GET |
| `backend/app/main.py` (修改) | 注册两个 travel_days router（员工端 + 管理端） |
| `backend/app/services/subsidy_engine.py` (修改) | `recompute_subsidies` 改读 `travel_days` |
| `backend/app/services/reimbursement_service.py` (修改) | `serialize_reimbursement_detail` 加 `travel_days` 字段 |
| `backend/tests/test_travel_days.py` (新建) | 8 个单元测试用例 |
| `backend/tests/test_subsidy_engine.py` (修改) | 更新旧断言 |
| `backend/scripts/e2e_travel_days_test.py` (新建) | E2E 验证脚本 |

### 前端

| 文件 | 责任 |
|---|---|
| `frontend/src/types/index.ts` (修改) | 加 `TravelDay` 类型 |
| `frontend/src/api/client.ts` (修改) | `portalApi` 加 travelDay API（list/create/deleteByDate） |
| `frontend/src/components/TravelDayPicker.tsx` (新建) | 月历弹层多选组件 |
| `frontend/src/components/ChatWidget.tsx` (修改) | 输入区加日历按钮 + 集成 picker（仅 employee role） |
| `frontend/src/pages/portal/MyReimbursements.tsx` (修改) | 详情页加"出差日" section（员工端带删除按钮） |
| `frontend/src/pages/Reimbursements.tsx` (修改) | 详情页加"出差日" section（管理端只读） |
| `frontend/src/pages/boss/ReimbursementDetail.tsx` (修改) | 详情页加"出差日" section（超管只读） |

---

## Task 1：后端模型 + 迁移 + 数据回填

**Files:**
- Modify: `backend/app/models/reimbursement.py`（末尾追加 `ReimbursementTravelDay` 类）
- Create: `backend/alembic/versions/0007_reimbursement_travel_days.py`
- Test: `backend/tests/test_travel_days.py`（仅一个迁移冒烟测试，其余测试在 Task 4 写）

**Interfaces:**
- Produces: `ReimbursementTravelDay` 模型类，含字段 `id, reimbursement_id, travel_date, note, weekday, day_type, base_rate, applicant_id`；`UniqueConstraint(reimbursement_id, travel_date)`
- Produces: Alembic 迁移 `0007_reimbursement_travel_days`，建表 + 从 `day_subsidies` 回填 `included=true` 的行到 `travel_days`
- Consumes: `Reimbursement` 模型（`applicant_id` 字段）、`ReimbursementDaySubsidy`（数据回填源）

- [ ] **Step 1: 在 `backend/app/models/reimbursement.py` 末尾追加 `ReimbursementTravelDay` 类**

```python
class ReimbursementTravelDay(Base, TimestampMixin):
    """报销单出差日 — 员工在对话框标记的出差日，触发补贴核算

    与 ReimbursementDaySubsidy 的关系：
    - travel_days 是触发源（员工主动标记）
    - day_subsidies 是补贴计算结果（由 subsidy_engine.recompute_subsidies 生成）
    - 一个 travel_day 对应一行 day_subsidy
    """

    __tablename__ = "reimbursement_travel_days"
    __table_args__ = (
        UniqueConstraint("reimbursement_id", "travel_date", name="uq_travel_day_reimb_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reimbursement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reimbursements.id", ondelete="CASCADE"), index=True, nullable=False
    )
    travel_date: Mapped[date] = mapped_column(Date, nullable=False, comment="出差日期")
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注，如北京出差/返程")
    weekday: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="0=周一…6=周日")
    day_type: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="workday/weekend/holiday")
    base_rate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="当日标准60或80")
    applicant_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="标记人 employee_no")
```

- [ ] **Step 2: 创建 Alembic 迁移文件 `backend/alembic/versions/0007_reimbursement_travel_days.py`**

```python
"""add reimbursement_travel_days table + backfill from day_subsidies

Revision ID: 0007_reimbursement_travel_days
Revises: 0006_verify_settings
Create Date: 2026-08-17 12:00:00.000000

新增表：reimbursement_travel_days
数据迁移：把 reimbursement_day_subsidies 中 included=true 的行回填到 travel_days
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_reimbursement_travel_days"
down_revision = "0006_verify_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reimbursement_travel_days",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reimbursement_id", sa.Integer(), nullable=False),
        sa.Column("travel_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("weekday", sa.SmallInteger(), nullable=True),
        sa.Column("day_type", sa.String(length=16), nullable=True),
        sa.Column("base_rate", sa.Float(), nullable=True),
        sa.Column("applicant_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["reimbursement_id"], ["reimbursements.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("reimbursement_id", "travel_date", name="uq_travel_day_reimb_date"),
    )
    op.create_index(
        "ix_reimbursement_travel_days_reimbursement_id",
        "reimbursement_travel_days",
        ["reimbursement_id"],
    )

    # 数据回填：day_subsidies 中 included=true 的行 → travel_days
    op.execute(
        """
        INSERT INTO reimbursement_travel_days
            (reimbursement_id, travel_date, note, weekday, day_type, base_rate, applicant_id, created_at, updated_at)
        SELECT
            rds.reimbursement_id,
            rds.subsidy_date,
            NULL,
            rds.weekday,
            rds.day_type,
            rds.base_rate,
            r.applicant_id,
            NOW(),
            NOW()
        FROM reimbursement_day_subsidies rds
        JOIN reimbursements r ON r.id = rds.reimbursement_id
        WHERE rds.included = true
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reimbursement_travel_days_reimbursement_id",
        table_name="reimbursement_travel_days",
    )
    op.drop_table("reimbursement_travel_days")
```

- [ ] **Step 3: 同步代码到容器**

Run:
```bash
docker cp backend/app/models/reimbursement.py ai-reimbursement-agent-backend-1:/app/app/models/reimbursement.py && docker cp backend/alembic/versions/0007_reimbursement_travel_days.py ai-reimbursement-agent-backend-1:/app/alembic/versions/0007_reimbursement_travel_days.py
```
Expected: 无输出（成功）

- [ ] **Step 4: 跑迁移**

Run:
```bash
docker exec ai-reimbursement-agent-backend-1 alembic upgrade head
```
Expected: `INFO  [alembic.runtime.migration] Running upgrade 0006_verify_settings -> 0007_reimbursement_travel_days, add reimbursement_travel_days table + backfill from day_subsidies`

- [ ] **Step 5: 验证表结构 + 数据回填**

Run:
```bash
docker exec ai-reimbursement-agent-backend-1 python -c "
import asyncio
from sqlalchemy import select, func
from app.database import get_async_sessionmaker
from app.models.reimbursement import ReimbursementTravelDay, ReimbursementDaySubsidy

async def main():
    async with get_async_sessionmaker()() as db:
        td_count = (await db.execute(select(func.count(ReimbursementTravelDay.id)))).scalar()
        ds_included = (await db.execute(select(func.count(ReimbursementDaySubsidy.id)).where(ReimbursementDaySubsidy.included == True))).scalar()
        print(f'travel_days count: {td_count}')
        print(f'day_subsidies included=true count: {ds_included}')
        assert td_count == ds_included, f'mismatch: {td_count} vs {ds_included}'
        print('OK: counts match')

asyncio.run(main())
"
```
Expected: `travel_days count: N`、`day_subsidies included=true count: N`、`OK: counts match`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/reimbursement.py backend/alembic/versions/0007_reimbursement_travel_days.py
git commit -m "feat(travel-day): add ReimbursementTravelDay model + migration + backfill"
```

---

## Task 2：补贴引擎改造（TDD）

**Files:**
- Modify: `backend/app/services/subsidy_engine.py`（`recompute_subsidies` 改读 travel_days）
- Modify: `backend/tests/test_subsidy_engine.py`（更新断言）

**Interfaces:**
- Produces: `subsidy_engine.recompute_subsidies` 签名不变，内部数据源从 `ReimbursementItem.item_date` 改为 `ReimbursementTravelDay.travel_date`
- Consumes: `ReimbursementTravelDay` 模型（Task 1）

- [ ] **Step 1: 看现有 `test_subsidy_engine.py` 中依赖 items 触发补贴的测试**

Run:
```bash
grep -n "def test_\|item_date\|reimbursement_item\|ReimbursementItem" backend/tests/test_subsidy_engine.py | head -30
```
Expected: 列出现有测试函数名 + 找出依赖 `ReimbursementItem` 触发补贴的测试

- [ ] **Step 2: 修改 `test_subsidy_engine.py` 中依赖 items 触发补贴的测试，改为依赖 travel_days**

测试改造原则：原本"插入 item → 期望 day_subsidy 出现"的测试，改为"插入 travel_day → 期望 day_subsidy 出现"。具体修改看现有测试内容，保留断言结构，把数据源从 `ReimbursementItem` 改为 `ReimbursementTravelDay`。

参考改造示例（具体测试名按现有来）：
```python
# 旧：
# inv = Invoice(...)
# db.add(inv); await db.flush()
# item = ReimbursementItem(reimbursement_id=reimb.id, invoice_id=inv.id, item_date=date(2026,8,15), ...)
# db.add(item)
# await recompute_subsidies(db, reimb)
# assert day_subsidy exists for 8/15

# 新：
from app.models.reimbursement import ReimbursementTravelDay
td = ReimbursementTravelDay(
    reimbursement_id=reimb.id,
    travel_date=date(2026, 8, 15),
    weekday=4,
    day_type="workday",
    base_rate=60.0,
    applicant_id=applicant_id,
)
db.add(td)
await recompute_subsidies(db, reimb)
# assert day_subsidy exists for 8/15
```

- [ ] **Step 3: 加一个新测试 `test_subsidy_only_counts_travel_days` 验证规则变化**

在 `backend/tests/test_subsidy_engine.py` 末尾追加：

```python
async def test_subsidy_only_counts_travel_days(db_session, sample_reimbursement):
    """有发票但无 travel_days → subsidy_total=0（新规则）"""
    from app.models.invoice import Invoice, InvoiceStatus
    from app.models.reimbursement import ReimbursementItem

    # 插入发票 + item，但不标 travel_day
    inv = Invoice(
        user_id=sample_reimbursement.applicant_id,
        seller_name="测试销售方",
        amount="100.00",
        total_with_tax="100.00",
        status=InvoiceStatus.confirmed,
    )
    db_session.add(inv)
    await db_session.flush()
    item = ReimbursementItem(
        reimbursement_id=sample_reimbursement.id,
        invoice_id=inv.id,
        item_date=date(2026, 8, 15),
        weekday=4,
        fee_category="personal",
        fee_subcategory="差旅-交通",
        amount=100.0,
        is_late_charge=False,
        sort_order=0,
    )
    db_session.add(item)
    await db_session.flush()

    # 旧规则：会自动生成 8/15 的 day_subsidy
    # 新规则：无 travel_day → 无 day_subsidy → subsidy_total=0
    subsidy_total = await recompute_subsidies(db_session, sample_reimbursement)
    assert subsidy_total == 0, f"无 travel_day 时补贴应=0，实际 {subsidy_total}"
```

- [ ] **Step 4: 跑测试验证失败（旧实现仍按 items 触发）**

Run:
```bash
docker cp backend/tests/test_subsidy_engine.py ai-reimbursement-agent-backend-1:/app/tests/test_subsidy_engine.py && docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_subsidy_engine.py -v 2>&1 | tail -20
```
Expected: `test_subsidy_only_counts_travel_days` FAIL（旧实现按 items 触发，补贴 > 0）

- [ ] **Step 5: 修改 `backend/app/services/subsidy_engine.py` 的 `recompute_subsidies`，改读 travel_days**

把 `recompute_subsidies` 函数中"收集有费用的日期"段落从：

```python
# 1. 收集有费用的日期
result = await db.execute(
    select(ReimbursementItem.item_date).where(
        ReimbursementItem.reimbursement_id == reimbursement.id,
        ReimbursementItem.item_date.isnot(None),
    ).distinct()
)
dates_with_expense = {row for row in result.scalars().all() if row}
```

改为：

```python
# 1. 收集出差日（员工标记的 travel_days）
from app.models.reimbursement import ReimbursementTravelDay
result = await db.execute(
    select(ReimbursementTravelDay.travel_date).where(
        ReimbursementTravelDay.reimbursement_id == reimbursement.id,
    ).distinct()
)
dates_with_expense = {row for row in result.scalars().all() if row}
```

注意：变量名 `dates_with_expense` 保留不动（只改数据源），后续 upsert 逻辑不动。

- [ ] **Step 6: 跑测试验证通过**

Run:
```bash
docker cp backend/app/services/subsidy_engine.py ai-reimbursement-agent-backend-1:/app/app/services/subsidy_engine.py && docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_subsidy_engine.py -v 2>&1 | tail -20
```
Expected: 所有测试 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/subsidy_engine.py backend/tests/test_subsidy_engine.py
git commit -m "refactor(subsidy): recompute_subsidies reads travel_days not items"
```

---

## Task 3：schemas + 序列化加 travel_days

**Files:**
- Modify: `backend/app/schemas/__init__.py`（加 `TravelDayCreateRequest` / `TravelDayResponse`）
- Modify: `backend/app/services/reimbursement_service.py`（`serialize_reimbursement_detail` 加 `travel_days` 字段）

**Interfaces:**
- Produces: `TravelDayCreateRequest { travel_date: date, note: str | None }`、`TravelDayResponse { id, reimbursement_id, travel_date, note, weekday, day_type, base_rate, applicant_id }`
- Produces: `serialize_reimbursement_detail` 返回的 dict 多一个 `travel_days` 列表
- Consumes: `ReimbursementTravelDay` 模型（Task 1）

- [ ] **Step 1: 在 `backend/app/schemas/__init__.py` 中加两个 schema**

在 `ReimbursementDaySubsidyResponse` 类之后追加：

```python
class TravelDayCreateRequest(BaseModel):
    """员工标记出差日请求"""
    travel_date: date
    note: str | None = None


class TravelDayResponse(BaseModel):
    """出差日记录"""
    id: int
    reimbursement_id: int
    travel_date: date
    note: str | None = None
    weekday: int | None = None
    day_type: str | None = None
    base_rate: float | None = None
    applicant_id: str
```

- [ ] **Step 2: 在 `backend/app/services/reimbursement_service.py` 的 `serialize_reimbursement_detail` 中加 `travel_days` 字段**

在函数内"日补贴"查询之后，追加"出差日"查询；在返回 dict 中加 `travel_days` 字段。

修改位置：`reimbursement_service.py:411` 后（day_subsidies 查询之后）追加：

```python
    # 出差日（员工标记）
    from app.models.reimbursement import ReimbursementTravelDay
    td_result = await db.execute(
        select(ReimbursementTravelDay)
        .where(ReimbursementTravelDay.reimbursement_id == reimbursement.id)
        .order_by(ReimbursementTravelDay.travel_date)
    )
    travel_days = list(td_result.scalars().all())
```

然后在返回 dict 中，在 `"day_subsidies": [...]` 之后追加：

```python
        "travel_days": [
            {
                "id": td.id,
                "reimbursement_id": td.reimbursement_id,
                "travel_date": td.travel_date.isoformat() if td.travel_date else None,
                "note": td.note,
                "weekday": td.weekday,
                "day_type": td.day_type,
                "base_rate": td.base_rate,
                "applicant_id": td.applicant_id,
            }
            for td in travel_days
        ],
```

- [ ] **Step 3: 同步并冒烟验证**

Run:
```bash
docker cp backend/app/schemas/__init__.py ai-reimbursement-agent-backend-1:/app/app/schemas/__init__.py && docker cp backend/app/services/reimbursement_service.py ai-reimbursement-agent-backend-1:/app/app/services/reimbursement_service.py && docker exec ai-reimbursement-agent-backend-1 python -c "
from app.schemas import TravelDayCreateRequest, TravelDayResponse
import asyncio
from app.services.reimbursement_service import serialize_reimbursement_detail
print('schemas OK')
print(TravelDayCreateRequest.model_fields.keys())
print(TravelDayResponse.model_fields.keys())
"
```
Expected: 输出 `schemas OK` + 两个 schema 的字段名列表

- [ ] **Step 4: 重启 backend + 冒烟调一个报销单详情**

Run:
```bash
docker compose restart backend 2>&1 | tail -2 && sleep 4 && TOKEN=$(curl -s -X POST http://localhost:18080/api/portal/auth/login -H 'Content-Type: application/json' -d '{"employee_no":"EMP001","password":"123456"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])") && curl -s "http://localhost:18080/api/portal/reimbursements" -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data:
    print('reimb id:', data[0]['id'])
else:
    print('no reimbursements')
"
```
Expected: 重启成功 + 输出某报销单 ID 或 "no reimbursements"

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/__init__.py backend/app/services/reimbursement_service.py
git commit -m "feat(travel-day): add schemas + serialize_reimbursement_detail returns travel_days"
```

---

## Task 4：travel_days 路由（TDD）

**Files:**
- Create: `backend/app/routers/travel_days.py`（5 个端点）
- Modify: `backend/app/main.py`（注册两个 router）
- Create: `backend/tests/test_travel_days.py`（8 个测试用例）

**Interfaces:**
- Produces: 5 个端点：
  - `GET /api/portal/travel-days`（员工，返回本周期报销单的所有 travel_days）
  - `POST /api/portal/travel-days`（员工，body `{travel_date, note?}`，标记一个出差日）
  - `DELETE /api/portal/travel-days/{id}`（员工，按 id 删除，仅本人）
  - `DELETE /api/portal/travel-days/by-date/{date}`（员工，按日期删除）
  - `GET /api/admin/travel-days?reimbursement_id=N`（管理员/超级管理员，穿透查看）
- Consumes: `get_current_employee_async`（`app.routers.portal_auth`，返回 `Employee`）、`get_or_create_reimbursement`（`app.services.aggregation_service`）、`cycle_key_of` / `current_cycle_key`（`app.services.cycle_engine`）、`recompute_all`（`app.services.subsidy_engine`）、`TravelDayCreateRequest` / `TravelDayResponse`（Task 3）

- [ ] **Step 1: 写 `backend/tests/test_travel_days.py` 的 8 个测试用例**

```python
"""出差日 API + 权限边界测试"""

import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.config import settings
from app.services.auth_service import hash_password
from app import database as db_module


@pytest.fixture
def client():
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_engine_after():
    yield
    db_module.get_engine.cache_clear()
    db_module.get_async_sessionmaker.cache_clear()


@pytest.fixture(autouse=True)
def setup_creds(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password_hash", hash_password("123456"))
    monkeypatch.setattr(settings, "boss_username", "zhang")
    monkeypatch.setattr(settings, "boss_password_hash", hash_password("zhang"))


EMP_NO = "EMP001"


def _emp_token(client):
    """员工登录拿 token（EMP001 / 123456）"""
    from app.services.auth_service import hash_password as hp
    # 确保员工有密码
    import asyncio
    from app.database import get_async_sessionmaker
    from app.models.employee import Employee

    async def _set_pwd():
        async with get_async_sessionmaker()() as db:
            emp = (await db.execute(select(Employee).where(Employee.employee_no == EMP_NO))).scalar_one_or_none()
            if emp and not emp.password_hash:
                emp.password_hash = hp("123456")
                await db.commit()

    asyncio.run(_set_pwd())
    resp = client.post("/api/portal/auth/login", json={"employee_no": EMP_NO, "password": "123456"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _admin_token(client):
    resp = client.post("/api/admin/auth/login", json={"username": "admin", "password": "123456"})
    return resp.json()["access_token"]


def _boss_token(client):
    resp = client.post("/api/boss/auth/login", json={"username": "zhang", "password": "zhang"})
    return resp.json()["access_token"]


def _today_in_cycle():
    """返回当前周期内一个日期字符串 YYYY-MM-DD"""
    from app.services.cycle_engine import current_cycle_key, billing_cycle
    today = date.today()
    ck = current_cycle_key(today)
    start, end = billing_cycle(ck)
    # 取周期中点
    return start.isoformat()


def test_mark_travel_day_creates_subsidy_row(client):
    token = _emp_token(client)
    d = _today_in_cycle()
    resp = client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": "北京出差"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["travel_date"] == d
    assert body["note"] == "北京出差"
    assert body["applicant_id"] == EMP_NO


def test_mark_outside_cycle_rejected(client):
    """travel_date 落在当前周期外 → 400"""
    token = _emp_token(client)
    # 用 1999-01-01，肯定在当前周期外
    resp = client.post(
        "/api/portal/travel-days",
        json={"travel_date": "1999-01-01", "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400, resp.text


def test_mark_duplicate_date_rejected(client):
    token = _emp_token(client)
    d = _today_in_cycle()
    # 第一次标记
    resp1 = client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 200
    # 第二次标记同一天 → 409
    resp2 = client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 409, resp2.text


def test_employee_can_list_own_travel_days(client):
    token = _emp_token(client)
    d = _today_in_cycle()
    client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.get("/api/portal/travel-days", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(td["travel_date"] == d for td in body)


def test_delete_travel_day_by_date(client):
    token = _emp_token(client)
    d = _today_in_cycle()
    client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.delete(
        f"/api/portal/travel-days/by-date/{d}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    # 验证已删除
    list_resp = client.get("/api/portal/travel-days", headers={"Authorization": f"Bearer {token}"})
    assert not any(td["travel_date"] == d for td in list_resp.json())


def test_admin_can_list_any_travel_days(client):
    """admin 端 GET /api/admin/travel-days?reimbursement_id=N"""
    emp_token = _emp_token(client)
    d = _today_in_cycle()
    # 员工标一个
    client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": "测试"},
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    # 拿 reimbursement_id
    reimb_resp = client.get(
        "/api/portal/reimbursements",
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    reimb_id = reimb_resp.json()[0]["id"]

    admin_token = _admin_token(client)
    resp = client.get(
        f"/api/admin/travel-days?reimbursement_id={reimb_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert any(td["travel_date"] == d for td in resp.json())


def test_boss_can_list_but_not_write(client):
    """boss GET → 200, POST → 403"""
    emp_token = _emp_token(client)
    d = _today_in_cycle()
    client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    reimb_resp = client.get(
        "/api/portal/reimbursements",
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    reimb_id = reimb_resp.json()[0]["id"]

    boss_token = _boss_token(client)
    # GET 通过
    get_resp = client.get(
        f"/api/admin/travel-days?reimbursement_id={reimb_id}",
        headers={"Authorization": f"Bearer {boss_token}"},
    )
    assert get_resp.status_code == 200
    # POST 拒绝（路由级 get_current_employee_async）
    post_resp = client.post(
        "/api/portal/travel-days",
        json={"travel_date": d, "note": None},
        headers={"Authorization": f"Bearer {boss_token}"},
    )
    assert post_resp.status_code in (401, 403)


def test_unauth_cannot_access(client):
    """无 token → 401"""
    resp = client.get("/api/portal/travel-days")
    assert resp.status_code == 401
```

- [ ] **Step 2: 跑测试验证失败（路由未实现）**

Run:
```bash
docker cp backend/tests/test_travel_days.py ai-reimbursement-agent-backend-1:/app/tests/test_travel_days.py && docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_travel_days.py -v 2>&1 | tail -25
```
Expected: 全部 FAIL（404 路由不存在）

- [ ] **Step 3: 创建 `backend/app/routers/travel_days.py`**

```python
"""出差日 API 路由

员工端（/api/portal/travel-days*）：
- GET    /api/portal/travel-days           — 列出本周期报销单的出差日
- POST   /api/portal/travel-days           — 标记一个出差日
- DELETE /api/portal/travel-days/{id}      — 按 id 删除（仅本人）
- DELETE /api/portal/travel-days/by-date/{date} — 按日期删除

管理端（/api/admin/travel-days）：
- GET    /api/admin/travel-days?reimbursement_id=N — 穿透查看任意报销单的出差日
"""

import logging
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.employee import Employee
from app.models.reimbursement import Reimbursement, ReimbursementTravelDay
from app.routers.portal_auth import get_current_employee_async
from app.routers.admin_auth import get_current_admin_or_boss
from app.schemas import TravelDayCreateRequest, TravelDayResponse
from app.services.aggregation_service import get_or_create_reimbursement
from app.services.cycle_engine import cycle_key_of, current_cycle_key, billing_cycle
from app.services.subsidy_engine import recompute_all, day_type, subsidy_rate, load_holidays

logger = logging.getLogger(__name__)


portal_router = APIRouter()
admin_router = APIRouter()


async def _get_or_create_my_reimbursement(
    db: AsyncSession, employee: Employee, travel_date: date
) -> Reimbursement:
    """按 travel_date 找该员工该周期的报销单，不存在则创建草稿"""
    ck = cycle_key_of(travel_date)
    return await get_or_create_reimbursement(db, employee.employee_no, ck)


async def _check_cycle_bounds(reimb: Reimbursement, travel_date: date) -> None:
    """travel_date 必须落在报销单周期内"""
    if not reimb.cycle_start or not reimb.cycle_end:
        raise HTTPException(status_code=500, detail="报销单周期未初始化")
    if not (reimb.cycle_start <= travel_date <= reimb.cycle_end):
        raise HTTPException(
            status_code=400,
            detail=f"出差日期 {travel_date} 不在周期 {reimb.cycle_start} ~ {reimb.cycle_end} 内",
        )


@portal_router.get("", response_model=List[TravelDayResponse])
async def list_my_travel_days(
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """列出当前员工所有报销单的出差日（按日期升序）"""
    result = await db.execute(
        select(ReimbursementTravelDay)
        .where(ReimbursementTravelDay.applicant_id == employee.employee_no)
        .order_by(ReimbursementTravelDay.travel_date)
    )
    return list(result.scalars().all())


@portal_router.post("", response_model=TravelDayResponse)
async def mark_travel_day(
    req: TravelDayCreateRequest,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """标记一个出差日"""
    reimb = await _get_or_create_my_reimbursement(db, employee, req.travel_date)
    await _check_cycle_bounds(reimb, req.travel_date)

    # 节假日 + 周期年份
    cycle_year = (reimb.cycle_start or date.today()).year
    holidays = await load_holidays(db, cycle_year)
    dt = day_type(req.travel_date, holidays)
    rate = subsidy_rate(req.travel_date, holidays)

    td = ReimbursementTravelDay(
        reimbursement_id=reimb.id,
        travel_date=req.travel_date,
        note=req.note,
        weekday=req.travel_date.weekday(),
        day_type=dt,
        base_rate=float(rate),
        applicant_id=employee.employee_no,
    )
    db.add(td)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"出差日 {req.travel_date} 已标记")

    # 触发补贴重算
    await recompute_all(db, reimb, holidays)
    await db.commit()
    await db.refresh(td)
    return td


@portal_router.delete("/{travel_day_id}")
async def delete_travel_day(
    travel_day_id: int,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """按 id 删除出差日（仅本人）"""
    result = await db.execute(
        select(ReimbursementTravelDay).where(ReimbursementTravelDay.id == travel_day_id)
    )
    td = result.scalars().first()
    if not td:
        raise HTTPException(status_code=404, detail="出差日不存在")
    if td.applicant_id != employee.employee_no:
        raise HTTPException(status_code=403, detail="不能删除他人的出差日")

    reimb_id = td.reimbursement_id
    await db.delete(td)

    # 重算所属报销单补贴
    reimb = (await db.execute(
        select(Reimbursement).where(Reimbursement.id == reimb_id)
    )).scalars().first()
    if reimb:
        cycle_year = (reimb.cycle_start or date.today()).year
        holidays = await load_holidays(db, cycle_year)
        await recompute_all(db, reimb, holidays)

    await db.commit()
    return {"deleted": True, "id": travel_day_id}


@portal_router.delete("/by-date/{travel_date}")
async def delete_travel_day_by_date(
    travel_date: date,
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """按日期删除出差日（员工端日历点取消更直观）"""
    result = await db.execute(
        select(ReimbursementTravelDay).where(
            ReimbursementTravelDay.applicant_id == employee.employee_no,
            ReimbursementTravelDay.travel_date == travel_date,
        )
    )
    td = result.scalars().first()
    if not td:
        raise HTTPException(status_code=404, detail=f"出差日 {travel_date} 不存在")

    reimb_id = td.reimbursement_id
    await db.delete(td)

    reimb = (await db.execute(
        select(Reimbursement).where(Reimbursement.id == reimb_id)
    )).scalars().first()
    if reimb:
        cycle_year = (reimb.cycle_start or date.today()).year
        holidays = await load_holidays(db, cycle_year)
        await recompute_all(db, reimb, holidays)

    await db.commit()
    return {"deleted": True, "travel_date": travel_date.isoformat()}


@admin_router.get("", response_model=List[TravelDayResponse])
async def list_travel_days_admin(
    reimbursement_id: int = Query(..., description="报销单 ID"),
    _: dict = Depends(get_current_admin_or_boss),
    db: AsyncSession = Depends(get_db),
):
    """管理员/超级管理员穿透查看指定报销单的出差日"""
    result = await db.execute(
        select(ReimbursementTravelDay)
        .where(ReimbursementTravelDay.reimbursement_id == reimbursement_id)
        .order_by(ReimbursementTravelDay.travel_date)
    )
    return list(result.scalars().all())
```

- [ ] **Step 4: 在 `backend/app/main.py` 注册两个 router**

在 `main.py` 中已有 boss router 注册的位置附近追加：

```python
# 出差日路由（员工端 + 管理端）
from app.routers.travel_days import portal_router as travel_portal_router
from app.routers.travel_days import admin_router as travel_admin_router
app.include_router(travel_portal_router, prefix="/api/portal/travel-days", tags=["员工端-出差日"])
app.include_router(travel_admin_router, prefix="/api/admin/travel-days", tags=["管理端-出差日"])
```

- [ ] **Step 5: 同步代码 + 重启 + 跑测试**

Run:
```bash
docker cp backend/app/routers/travel_days.py ai-reimbursement-agent-backend-1:/app/app/routers/travel_days.py && docker cp backend/app/main.py ai-reimbursement-agent-backend-1:/app/app/main.py && docker compose restart backend 2>&1 | tail -2 && sleep 5 && docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_travel_days.py -v 2>&1 | tail -25
```
Expected: 8/8 PASS（可能 1 个 mark_outside_cycle 因周期边界条件需要细调，按需修测试或路由）

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/travel_days.py backend/app/main.py backend/tests/test_travel_days.py
git commit -m "feat(travel-day): add 5 travel-day endpoints + 8 tests"
```

---

## Task 5：前端类型 + API 客户端

**Files:**
- Modify: `frontend/src/types/index.ts`（加 `TravelDay` 类型）
- Modify: `frontend/src/api/client.ts`（`portalApi` 加 travelDay API）

**Interfaces:**
- Produces: `TravelDay` 类型，含 `id, reimbursement_id, travel_date, note, weekday, day_type, base_rate, applicant_id`
- Produces: `portalApi.travelDays`（list / create / deleteByDate 三个方法）
- Consumes: 后端 `/api/portal/travel-days/*` 端点（Task 4）

- [ ] **Step 1: 在 `frontend/src/types/index.ts` 中加 `TravelDay` 类型**

在 `ReimbursementDaySubsidy` 类型之后追加：

```typescript
export interface TravelDay {
  id: number;
  reimbursement_id: number;
  travel_date: string;  // ISO date YYYY-MM-DD
  note: string | null;
  weekday: number | null;  // 0=周一…6=周日
  day_type: string | null;  // workday/weekend/holiday
  base_rate: number | null;
  applicant_id: string;
}
```

- [ ] **Step 2: 在 `frontend/src/api/client.ts` 的 `portalApi` 对象中加 travelDay API**

找到 `portalApi` 对象（约在 line 505 附近），在合适位置（例如其他报销单方法附近）追加三个方法：

```typescript
  /** 出差日：列出当前员工所有报销单的出差日 */
  listTravelDays: (): Promise<TravelDay[]> =>
    portalRequest<TravelDay[]>("/travel-days"),

  /** 出差日：标记一个出差日 */
  createTravelDay: async (
    travel_date: string,
    note?: string
  ): Promise<TravelDay> => {
    return portalRequest<TravelDay>("/travel-days", {
      method: "POST",
      body: JSON.stringify({ travel_date, note: note || null }),
    });
  },

  /** 出差日：按日期删除（员工端日历点取消更直观） */
  deleteTravelDayByDate: async (travel_date: string): Promise<void> => {
    await portalRequest<{ deleted: boolean }>(
      `/travel-days/by-date/${encodeURIComponent(travel_date)}`,
      { method: "DELETE" }
    );
  },
```

注意：如果 `portalRequest` 函数签名与 `request` 不同（看现有 `portalApi` 方法怎么写的），按现有风格调整调用方式。先确认 `portalRequest` 的签名：

Run: `grep -n "async function portalRequest\|function portalRequest" frontend/src/api/client.ts | head -3`

- [ ] **Step 3: 检查 `portalRequest` 是否已存在；如不存在，看现有 portalApi 方法是用什么发请求的**

Run:
```bash
grep -n "portalApi\|portalRequest\|portalFetch" frontend/src/api/client.ts | head -10
```
Expected: 看到 portalApi 内部请求封装的写法

如果 portalApi 方法用的是 `request<T>(...)`（与管理端共用同一个），但 portalApi 已有自己的 token 注入逻辑——参考已有 portalApi 方法（如 `myInvoices`、`dashboard`）的写法，照搬。

- [ ] **Step 4: 验证 TypeScript 编译**

Run:
```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -10
```
Expected: 无输出（编译通过）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat(travel-day): add TravelDay type + portalApi.travelDays"
```

---

## Task 6：TravelDayPicker 组件

**Files:**
- Create: `frontend/src/components/TravelDayPicker.tsx`

**Interfaces:**
- Produces: `TravelDayPicker` 组件，props: `{ open, onClose, cycleStart, cycleEnd, existingTravelDays, onSubmit }`
  - `open: boolean`
  - `onClose: () => void`
  - `cycleStart: string | null`（ISO date）
  - `cycleEnd: string | null`
  - `existingTravelDays: TravelDay[]`（来自后端 GET）
  - `onSubmit: (selected: { date: string; note: string | null }[], removed: string[]) => Promise<void>`
    - selected：本批次新选的天（含备注）
    - removed：本批次取消选中的天（date 字符串列表）
- Consumes: `TravelDay` 类型（Task 5）

- [ ] **Step 1: 创建 `frontend/src/components/TravelDayPicker.tsx`**

```tsx
import { useState, useMemo, useEffect } from "react";
import { X, Calendar, Check } from "@phosphor-icons/react";
import type { TravelDay } from "../types";

interface TravelDayPickerProps {
  open: boolean;
  onClose: () => void;
  cycleStart: string | null;
  cycleEnd: string | null;
  existingTravelDays: TravelDay[];
  onSubmit: (
    selected: { date: string; note: string | null }[],
    removed: string[]
  ) => Promise<void>;
}

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseISO(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function TravelDayPicker({
  open,
  onClose,
  cycleStart,
  cycleEnd,
  existingTravelDays,
  onSubmit,
}: TravelDayPickerProps) {
  // 当前显示的月份（年/月）
  const [viewYear, setViewYear] = useState<number>(new Date().getFullYear());
  const [viewMonth, setViewMonth] = useState<number>(new Date().getMonth());

  // 本批次选中的天（要新增的）
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // 本批次取消选中的天（要从后端删除的）
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // 已存在的出差日（来自后端，初始时显示为"实心蓝点"）
  const existingDates = useMemo(
    () => new Set(existingTravelDays.map((td) => td.travel_date)),
    [existingTravelDays]
  );

  // 打开时初始化视图月份为周期起始月
  useEffect(() => {
    if (open && cycleStart) {
      const d = parseISO(cycleStart);
      setViewYear(d.getFullYear());
      setViewMonth(d.getMonth());
      setSelected(new Set());
      setRemoved(new Set());
      setNote("");
    }
  }, [open, cycleStart]);

  if (!open) return null;

  const cycleStartD = cycleStart ? parseISO(cycleStart) : null;
  const cycleEndD = cycleEnd ? parseISO(cycleEnd) : null;

  // 某天是否可点（在周期内）
  const isClickable = (d: Date): boolean => {
    if (!cycleStartD || !cycleEndD) return false;
    return d >= cycleStartD && d <= cycleEndD;
  };

  // 某天是否已被标记（后端已有）
  const isExisting = (d: Date): boolean => existingDates.has(iso(d));

  // 某天是否本批次新选中
  const isSelected = (d: Date): boolean => selected.has(iso(d));

  // 某天是否本批次取消选中
  const isRemoved = (d: Date): boolean => removed.has(iso(d));

  const toggleDate = (d: Date) => {
    if (!isClickable(d)) return;
    const key = iso(d);
    if (isExisting(d)) {
      // 已存在的 → toggle removed
      setRemoved((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      });
    } else {
      // 不存在的 → toggle selected
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      });
    }
  };

  // 构建月历网格
  const firstDay = new Date(viewYear, viewMonth, 1);
  const lastDay = new Date(viewYear, viewMonth + 1, 0);
  const startWeekday = (firstDay.getDay() + 6) % 7;  // 周一=0
  const daysInMonth = lastDay.getDate();
  const cells: (Date | null)[] = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let i = 1; i <= daysInMonth; i++) {
    cells.push(new Date(viewYear, viewMonth, i));
  }

  const prevMonth = () => {
    setViewMonth((m) => {
      if (m === 0) {
        setViewYear((y) => y - 1);
        return 11;
      }
      return m - 1;
    });
  };
  const nextMonth = () => {
    setViewMonth((m) => {
      if (m === 11) {
        setViewYear((y) => y + 1);
        return 0;
      }
      return m + 1;
    });
  };

  const clearSelection = () => {
    setSelected(new Set());
    setRemoved(new Set());
  };

  const selectedList = Array.from(selected).sort();
  const removedList = Array.from(removed).sort();

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onSubmit(
        selectedList.map((date) => ({ date, note: note.trim() || null })),
        removedList
      );
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-t-2xl bg-background p-4 shadow-xl sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Calendar size={18} className="text-primary-700" />
            <h3 className="font-display text-sm font-bold text-foreground">标记出差日</h3>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={18} />
          </button>
        </div>

        {/* 月份切换 */}
        <div className="mb-2 flex items-center justify-between">
          <button onClick={prevMonth} className="rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-muted">
            ‹
          </button>
          <span className="text-sm font-medium text-foreground">
            {viewYear} 年 {viewMonth + 1} 月
          </span>
          <button onClick={nextMonth} className="rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-muted">
            ›
          </button>
        </div>

        {/* 星期标题 */}
        <div className="mb-1 grid grid-cols-7 gap-1 text-center text-[11px] text-muted-foreground">
          {WEEKDAYS.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>

        {/* 日期网格 */}
        <div className="grid grid-cols-7 gap-1">
          {cells.map((d, i) => {
            if (!d) return <div key={`empty-${i}`} />;
            const clickable = isClickable(d);
            const existing = isExisting(d);
            const sel = isSelected(d);
            const rm = isRemoved(d);
            return (
              <button
                key={iso(d)}
                onClick={() => toggleDate(d)}
                disabled={!clickable}
                className={`aspect-square rounded-md text-xs font-medium transition-colors ${
                  !clickable
                    ? "text-muted/40 cursor-not-allowed"
                    : rm
                      ? "bg-error-50 text-error-400 line-through"
                      : sel
                        ? "bg-primary-700 text-white"
                        : existing
                          ? "bg-primary-50 text-primary-700"
                          : "text-foreground hover:bg-muted"
                }`}
              >
                {d.getDate()}
              </button>
            );
          })}
        </div>

        {/* 备注 */}
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="备注（可选，如北京出差）"
          className="mt-3 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
        />

        {/* 已选列表 */}
        {selectedList.length > 0 && (
          <div className="mt-2 text-xs text-muted-foreground">
            已选 {selectedList.length} 天：{selectedList.join("、")}
          </div>
        )}
        {removedList.length > 0 && (
          <div className="mt-1 text-xs text-error-600">
            取消 {removedList.length} 天：{removedList.join("、")}
          </div>
        )}

        {/* 操作 */}
        <div className="mt-4 flex items-center justify-between gap-2">
          <button
            onClick={clearSelection}
            disabled={selected.size === 0 && removed.size === 0}
            className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted disabled:opacity-40"
          >
            清空选择
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || (selected.size === 0 && removed.size === 0)}
            className="flex items-center gap-1 rounded-md bg-primary-700 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-primary-800 disabled:opacity-40"
          >
            <Check size={14} />
            {submitting ? "提交中…" : "完成"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

Run:
```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -10
```
Expected: 无输出（编译通过）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TravelDayPicker.tsx
git commit -m "feat(travel-day): add TravelDayPicker month calendar component"
```

---

## Task 7：对话框集成日历按钮

**Files:**
- Modify: `frontend/src/components/ChatWidget.tsx`（输入区加日历按钮 + 集成 picker，仅 employee role）

**Interfaces:**
- Consumes: `TravelDayPicker` 组件（Task 6）、`portalApi.travelDays` API（Task 5）
- Produces: ChatWidget 输入区新增日历按钮（仅 employee role），点击弹 TravelDayPicker；提交后插入助手消息

- [ ] **Step 1: 在 `ChatWidget.tsx` 顶部 import 区追加**

```tsx
import { Calendar } from "@phosphor-icons/react";
import { TravelDayPicker } from "./TravelDayPicker";
import type { TravelDay } from "../types";
```

- [ ] **Step 2: 在 ChatWidget 组件 state 区（约 line 525 附近）追加**

```tsx
const [travelPickerOpen, setTravelPickerOpen] = useState(false);
const [travelDays, setTravelDays] = useState<TravelDay[]>([]);
```

- [ ] **Step 3: 加 useEffect 加载本周期 travel_days（仅 employee role 时）**

在现有 useEffect 附近追加：

```tsx
useEffect(() => {
  if (role !== "employee") return;
  portalApi.listTravelDays().then(setTravelDays).catch(() => {});
}, [role]);
```

- [ ] **Step 4: 加 `handleTravelDaysSubmit` 函数**

在组件内合适位置追加（在 handleSend 附近）：

```tsx
const handleTravelDaysSubmit = async (
  selected: { date: string; note: string | null }[],
  removed: string[]
) => {
  // 批量 POST 新选的
  const added: string[] = [];
  for (const item of selected) {
    try {
      await portalApi.createTravelDay(item.date, item.note || undefined);
      added.push(item.date);
    } catch (err) {
      // 单个失败不阻断其他
      console.error(`标记 ${item.date} 失败`, err);
    }
  }
  // 批量 DELETE 取消的
  for (const date of removed) {
    try {
      await portalApi.deleteTravelDayByDate(date);
    } catch (err) {
      console.error(`删除 ${date} 失败`, err);
    }
  }
  // 刷新
  try {
    const fresh = await portalApi.listTravelDays();
    setTravelDays(fresh);
  } catch {}
  // 插入助手消息
  const msgs: string[] = [];
  if (added.length > 0) {
    msgs.push(`已标记 ${added.length} 天为出差日：${added.join("、")}`);
  }
  if (removed.length > 0) {
    msgs.push(`已取消 ${removed.length} 天出差日：${removed.join("、")}`);
  }
  if (msgs.length > 0) {
    setMessages((prev) => [
      ...prev,
      {
        id: `travel-${Date.now()}`,
        role: "assistant",
        text: msgs.join("。") + "。",
        timestamp: Date.now(),
      },
    ]);
  }
};
```

- [ ] **Step 5: 在输入区"无凭证报销"按钮之后追加日历按钮（仅 employee role 时显示）**

找到现有 ChatWidget 输入区结构（约 line 1133 "无凭证报销"按钮之后），追加：

```tsx
{role === "employee" && (
  <>
    <button
      onClick={() => setTravelPickerOpen(true)}
      disabled={isTyping}
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-primary-50 hover:text-primary-700 disabled:opacity-40"
      title="标记出差日"
    >
      <Calendar size={20} className="pointer-events-none" />
    </button>
    <TravelDayPicker
      open={travelPickerOpen}
      onClose={() => setTravelPickerOpen(false)}
      cycleStart={currentCycleStart}
      cycleEnd={currentCycleEnd}
      existingTravelDays={travelDays}
      onSubmit={handleTravelDaysSubmit}
    />
  </>
)}
```

注：`currentCycleStart` / `currentCycleEnd` 需要从某处获取。如果 ChatWidget 内部没有当前周期信息，从 `portalApi.dashboard()` 取一次（dashboard 返回 `cycle_start` / `cycle_end`）。在已有 useEffect 加载 dashboard 数据处一并 set。如果 ChatWidget 没有加载 dashboard，加一个简单 useEffect：

```tsx
const [currentCycleStart, setCurrentCycleStart] = useState<string | null>(null);
const [currentCycleEnd, setCurrentCycleEnd] = useState<string | null>(null);

useEffect(() => {
  if (role !== "employee") return;
  portalApi.dashboard().then((d) => {
    setCurrentCycleStart(d.cycle_start);
    setCurrentCycleEnd(d.cycle_end);
  }).catch(() => {});
}, [role]);
```

- [ ] **Step 6: 验证 TypeScript 编译**

Run:
```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -10
```
Expected: 无输出（编译通过）。如有 "currentCycleStart undefined" 类错误，按 Step 5 末尾补 useEffect

- [ ] **Step 7: 浏览器手动冒烟（vite HMR 自动加载）**

1. 打开 `http://localhost:13000/portal/login`，用 `EMP001` / `123456` 登录
2. 进入 `/portal/home`，对话框输入区应在"无凭证报销"按钮右边看到日历图标
3. 点日历 → 弹层 → 选当前周期内 2 个日期 + 备注"北京出差" → 点完成
4. 对话框内出现"已标记 2 天为出差日：…"助手消息

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/ChatWidget.tsx
git commit -m "feat(travel-day): integrate calendar button in chat input (employee only)"
```

---

## Task 8：报销单详情加"出差日" section（三端）

**Files:**
- Modify: `frontend/src/pages/portal/MyReimbursements.tsx`（员工端，带删除按钮）
- Modify: `frontend/src/pages/Reimbursements.tsx`（管理端，只读）
- Modify: `frontend/src/pages/boss/ReimbursementDetail.tsx`（超管，只读）

**Interfaces:**
- Consumes: `TravelDay` 类型（Task 5）、`portalApi.travelDays` API（Task 5，员工端删除用）、报销单详情返回的 `travel_days` 字段（Task 3）

- [ ] **Step 1: 员工端 `MyReimbursements.tsx` 详情加"出差日" section**

在现有"日补贴"section 之前插入。先看现有"日补贴"section 在哪个组件、接收什么数据：

Run: `grep -n "日补贴\|day_subsidies" frontend/src/pages/portal/MyReimbursements.tsx | head -10`

找到"日补贴"section 的渲染位置，在它之前插入"出差日" section。具体代码：

```tsx
{/* 出差日 */}
{detail.travel_days && detail.travel_days.length > 0 && (
  <div className="rounded-xl border border-border bg-background p-4 shadow-sm">
    <h3 className="mb-3 flex items-center gap-1.5 font-display text-sm font-semibold text-foreground/70">
      <Calendar size={14} className="text-muted" />
      出差日（{detail.travel_days.length} 天）
    </h3>
    <div className="space-y-2">
      {detail.travel_days.map((td) => {
        // 当日发票数：从 detail.items 找 item_date 匹配
        const invoiceCount = (detail.items ||).filter(
          (it) => it.item_date === td.travel_date
        ).length;
        return (
          <div
            key={td.id}
            className="flex items-center justify-between gap-2 rounded-lg border border-border bg-background p-2.5"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-foreground">
                {td.travel_date}
                {td.day_type && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    · {td.day_type === "weekend" ? "周末" : td.day_type === "holiday" ? "节假日" : "工作日"}
                  </span>
                )}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {td.note || "—"} · 当日发票 {invoiceCount} 张
              </p>
            </div>
            <button
              onClick={async () => {
                try {
                  await portalApi.deleteTravelDayByDate(td.travel_date);
                  // 触发刷新——看现有组件如何刷新 detail（通常 setDetailId(null) + 重新打开，或调 load 函数）
                  // 复用现有刷新机制
                  window.dispatchEvent(new CustomEvent("chat-invoices-changed"));
                } catch (err) {
                  alert(err instanceof Error ? err.message : "删除失败");
                }
              }}
              className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-error-50 hover:text-error-600"
              title="删除出差日"
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  </div>
)}
```

注意：需在文件顶部 import 加 `import { Calendar, X } from "@phosphor-icons/react";`（如未 import）。`detail` 类型可能需要更新——看现有 `PortalReimbursementDetail` 类型，补加 `travel_days` 字段：

Run: `grep -n "PortalReimbursementDetail" frontend/src/types/index.ts | head -3`

找到类型定义后追加 `travel_days?: TravelDay[];`。

- [ ] **Step 2: 管理端 `Reimbursements.tsx` 详情加"出差日" section（只读，无删除按钮）**

类似员工端，但不渲染删除按钮。在现有详情页"日补贴"section 前插入：

```tsx
{detail.travel_days && detail.travel_days.length > 0 && (
  <div className="rounded-xl border border-border bg-background p-4">
    <h3 className="mb-3 font-display text-sm font-semibold text-foreground/70">
      出差日（{detail.travel_days.length} 天）
    </h3>
    <div className="space-y-2">
      {detail.travel_days.map((td) => {
        const invoiceCount = (detail.items || []).filter(
          (it) => it.item_date === td.travel_date
        ).length;
        return (
          <div
            key={td.id}
            className="flex items-center justify-between rounded-lg border border-border p-2.5"
          >
            <div>
              <p className="text-sm font-medium text-foreground">
                {td.travel_date}
                {td.day_type && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    · {td.day_type === "weekend" ? "周末" : td.day_type === "holiday" ? "节假日" : "工作日"}
                  </span>
                )}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {td.note || "—"} · 当日发票 {invoiceCount} 张
              </p>
            </div>
          </div>
        );
      })}
    </div>
  </div>
)}
```

- [ ] **Step 3: 超管端 `boss/ReimbursementDetail.tsx` 加"出差日" section（只读）**

类似管理端，加在"关联发票"section 之前。代码同 Step 2，但可能需要适配 `Reimbursement` 类型（看 boss 端用的是 `Reimbursement` 还是 `unknown`）——Task 5 已把 `getReimbursement` 返回类型改为 `Reimbursement`，但 `Reimbursement` 类型可能没有 `travel_days` 字段。在 `frontend/src/types/index.ts` 的 `Reimbursement` 接口加 `travel_days?: TravelDay[];`。

- [ ] **Step 4: 更新 `frontend/src/types/index.ts` 中 `Reimbursement` 接口**

找到 `Reimbursement` 接口，在末尾追加：

```typescript
  travel_days?: TravelDay[];
```

同时给 `PortalReimbursementDetail` 类型也加（如已存在）。

- [ ] **Step 5: 验证 TypeScript 编译**

Run:
```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -10
```
Expected: 无输出

- [ ] **Step 6: 浏览器手动冒烟**

1. 员工端：登录 → 对话框标出差日 → 进 `/portal/reimbursements` → 详情页有"出差日" section → 点 × 删除一个 → section 刷新
2. 管理端：登录 → `/reimbursements` 详情 → 看到"出差日" section，无 × 按钮
3. 超管端：`/boss/reimbursements/:id` → 看到"出差日" section，无 × 按钮

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/portal/MyReimbursements.tsx frontend/src/pages/Reimbursements.tsx frontend/src/pages/boss/ReimbursementDetail.tsx frontend/src/types/index.ts
git commit -m "feat(travel-day): show travel_days section in reimbursement detail (3 sides)"
```

---

## Task 9：E2E 脚本 + 全量回归

**Files:**
- Create: `backend/scripts/e2e_travel_days_test.py`
- 后端全量测试 + 前端 TS 编译 + admin/portal/boss 回归

- [ ] **Step 1: 写 `backend/scripts/e2e_travel_days_test.py`**

```python
"""出差日 E2E 验证脚本

用法（本机直接跑，依赖 backend 容器在 18080 端口监听）：
    python backend/scripts/e2e_travel_days_test.py

验证项：
1. 员工登录 → 拿 token
2. 标记本周期内一个出差日 → 200 + 返回 travel_day
3. 同一天重复标记 → 409
4. 标记周期外日期 → 400
5. GET /api/portal/travel-days → 列出已标记的天
6. GET 报销单详情 → travel_days 字段非空 + subsidy_total > 0
7. 按日期 DELETE → 200
8. GET 报销单详情 → travel_days 减少 + subsidy_total 减
9. admin GET /api/admin/travel-days?reimbursement_id=N → 200
10. boss POST /api/portal/travel-days → 401/403
"""

import sys
import json
import urllib.request
import urllib.error
from datetime import date

BASE = "http://127.0.0.1:18080"


def req(method: str, path: str, body=None, token=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "null")
        except json.JSONDecodeError:
            return e.code, None


def main():
    print("=" * 60)
    print("出差日 E2E 验证")
    print("=" * 60)

    # 1. 员工登录
    code, body = req("POST", "/api/portal/auth/login", {"employee_no": "EMP001", "password": "123456"})
    assert code == 200, f"[FAIL] 员工登录 期望 200，实际 {code}：{body}"
    emp_token = body["access_token"]
    print("[OK] 1. 员工登录成功")

    # 2. 拿当前周期内一个日期
    from datetime import date
    today = date.today()
    # 取本月 21 号附近，肯定在周期内
    test_date = today.replace(day=22) if today.day < 22 else today.replace(day=23)
    # 简化：直接用今天，今天一定在某周期内
    test_date = today
    d = test_date.isoformat()
    print(f"  测试日期: {d}")

    # 3. 标记
    code, body = req("POST", "/api/portal/travel-days", {"travel_date": d, "note": "E2E 测试"}, token=emp_token)
    assert code == 200, f"[FAIL] 标记出差日 期望 200，实际 {code}：{body}"
    assert body["travel_date"] == d
    print(f"[OK] 2. 标记出差日 {d}")

    # 4. 重复标记
    code, body = req("POST", "/api/portal/travel-days", {"travel_date": d, "note": None}, token=emp_token)
    assert code == 409, f"[FAIL] 重复标记 期望 409，实际 {code}"
    print(f"[OK] 3. 重复标记 → 409")

    # 5. 标记周期外
    code, _ = req("POST", "/api/portal/travel-days", {"travel_date": "1999-01-01", "note": None}, token=emp_token)
    assert code == 400, f"[FAIL] 周期外 期望 400，实际 {code}"
    print(f"[OK] 4. 周期外日期 → 400")

    # 6. GET 列表
    code, body = req("GET", "/api/portal/travel-days", token=emp_token)
    assert code == 200
    assert any(td["travel_date"] == d for td in body)
    print(f"[OK] 5. GET 列表 → {len(body)} 行")

    # 7. GET 报销单详情 → travel_days + subsidy_total
    code, body = req("GET", "/api/portal/reimbursements", token=emp_token)
    assert code == 200 and body
    reimb_id = body[0]["id"]
    code, detail = req("GET", f"/api/portal/reimbursements/{reimb_id}", token=emp_token)
    assert code == 200
    assert any(td["travel_date"] == d for td in detail.get("travel_days", [])), "travel_days 缺少已标日期"
    assert detail["subsidy_total"] > 0, f"subsidy_total 应>0，实际 {detail['subsidy_total']}"
    subsidy_before = detail["subsidy_total"]
    print(f"[OK] 6. 报销单详情 → travel_days 含 {d}, subsidy_total={subsidy_before}")

    # 8. DELETE by date
    code, body = req("DELETE", f"/api/portal/travel-days/by-date/{d}", token=emp_token)
    assert code == 200, f"[FAIL] 删除 期望 200，实际 {code}"
    print(f"[OK] 7. DELETE by date → 200")

    # 9. 验证 subsidy_total 减少
    code, detail = req("GET", f"/api/portal/reimbursements/{reimb_id}", token=emp_token)
    assert code == 200
    assert detail["subsidy_total"] < subsidy_before, f"subsidy_total 应减少，{subsidy_before} → {detail['subsidy_total']}"
    print(f"[OK] 8. subsidy_total {subsidy_before} → {detail['subsidy_total']}")

    # 10. admin GET
    code, body = req("POST", "/api/admin/auth/login", {"username": "admin", "password": "123456"})
    admin_token = body["access_token"]
    code, body = req("GET", f"/api/admin/travel-days?reimbursement_id={reimb_id}", token=admin_token)
    assert code == 200
    print(f"[OK] 9. admin GET /api/admin/travel-days → 200")

    # 11. boss POST → 403
    code, body = req("POST", "/api/boss/auth/login", {"username": "zhang", "password": "zhang"})
    boss_token = body["access_token"]
    code, _ = req("POST", "/api/portal/travel-days", {"travel_date": d, "note": None}, token=boss_token)
    assert code in (401, 403), f"[FAIL] boss POST 期望 401/403，实际 {code}"
    print(f"[OK] 10. boss POST → {code}")

    print("=" * 60)
    print("✓ 全部 10 项出差日 E2E 验证通过")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n✗ {e}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 2: 跑 E2E 脚本**

Run:
```bash
python3 backend/scripts/e2e_travel_days_test.py
```
Expected: `✓ 全部 10 项出差日 E2E 验证通过`

- [ ] **Step 3: 后端全量回归**

Run:
```bash
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_travel_days.py tests/test_subsidy_engine.py tests/test_boss_auth.py -v 2>&1 | tail -30
```
Expected: 全 PASS（已知预存在失败的 test_classifier / test_diff_engine 等不在范围）

- [ ] **Step 4: 前端 TS 编译 + 三端登录回归**

Run:
```bash
cd frontend && npx tsc --noEmit && cd .. && echo "---admin---" && curl -s -X POST http://localhost:18080/api/admin/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"123456"}' | python3 -c "import sys,json;print('admin:',json.load(sys.stdin).get('token_type'))" && echo "---portal---" && curl -s -X POST http://localhost:18080/api/portal/auth/login -H 'Content-Type: application/json' -d '{"employee_no":"EMP001","password":"123456"}' | python3 -c "import sys,json;print('portal:',json.load(sys.stdin).get('token_type'))" && echo "---boss---" && curl -s -X POST http://localhost:18080/api/boss/auth/login -H 'Content-Type: application/json' -d '{"username":"zhang","password":"zhang"}' | python3 -c "import sys,json;print('boss:',json.load(sys.stdin).get('token_type'))"
```
Expected: TS 无输出 + admin/portal/boss 都打印 `bearer`

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/e2e_travel_days_test.py
git commit -m "test(travel-day): e2e validation script + full regression"
```

---

## 全部完成后的总结

跑一遍最终验证清单：
- [ ] Alembic head 是 `0007_reimbursement_travel_days`
- [ ] `reimbursement_travel_days` 表存在 + 数据已回填
- [ ] `subsidy_engine.recompute_subsidies` 读 travel_days（测试 PASS）
- [ ] 5 个 travel-days 端点工作（test_travel_days.py 8/8 PASS）
- [ ] 前端 TravelDayPicker 月历组件可用
- [ ] 员工端对话框有日历按钮（仅 employee role）
- [ ] 三端报销单详情有"出差日" section
- [ ] E2E 10/10 通过
- [ ] admin/portal/boss 登录回归正常
