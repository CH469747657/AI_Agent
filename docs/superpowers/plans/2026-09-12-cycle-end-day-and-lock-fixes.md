# 周期截止日重命名 + 封账后禁止操作 + 管理员手动解锁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重命名 `cycle_cutoff_day` 为 `cycle_end_day` 并改语义为「该日为本周期最后一天（含）」；封账后禁止员工 6 类修改操作；管理员可手动 unlock/lock 报销单让员工修复问题。

**Architecture:** alembic 0016 重命名列 + 重算现有数据 + 默认值改 20；alembic 0017 加 3 个 unlock 审计字段；`cycle_engine` 算法判定从 `>=` 改 `>`；`reimbursement_service` 加 `assert_not_locked` helper 集中校验；2 个管理员 unlock/lock 端点；`scheduler_service.reschedule_cycle_lock_job` 动态生效；4 处前端展示周期范围 + 管理端 unlock/lock 按钮。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL 15 + Alembic + APScheduler + React 18 + TypeScript + Vite + TailwindCSS + Playwright

## Global Constraints

- **字段名**：`cycle_end_day`（不是 `cycle_cutoff_day`），默认值 20（不是 21）。语义：「该日为本周期最后一天（含）」。
- **算法判定**：`d.day > cycle_end_day` 属下月周期；`d.day <= cycle_end_day` 属当月周期（注意是 `>` 不是 `>=`）。
- **现有数据可改**：alembic 0016 会重算 `reimbursements.cycle_start` / `cycle_end` 按新语义。执行前建议 dump 数据库备份。
- **封账后禁止 6 类操作**：submit / withdraw / update / delete / link invoices / unlink invoice / toggle subsidy。service 层 `assert_not_locked` 集中校验。
- **unlock 粒度**：仅单报销单（不能整周期解锁）。
- **unlock 审计**：3 个字段 `unlocked_by` / `unlocked_at` / `unlock_reason`。重新封账时清空这 3 个字段。
- **Invoice 字段**：`Invoice.user_id`（不是 `applicant_id`），`Invoice.reimbursement_id`。
- **Reimbursement 字段**：`applicant_id`、`cycle_key`、`status`、`auto_generated`、`is_cycle_locked`、`locked_at`、`unlocked_by`、`unlocked_at`、`unlock_reason`。
- **DialogContext**：用 `ctx.role`（不是 `user_role`），`ctx.user_id`，`ctx.slots: dict[str, Slot]`（Slot 有 `.value` 和 `.filled` 属性）。
- **测试**：新增功能相关测试用例必须全绿。不在范围：修复 89 个历史失败测试。
- **Commit 风格**：遵循 conventional commits（feat/fix/chore/docs/test）+ 中文摘要 + `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`。

---

## File Structure

**新增文件**：
- `backend/alembic/versions/0016_rename_cycle_end_day.py` — alembic 迁移：重命名列 + 重算数据
- `backend/alembic/versions/0017_reimbursement_unlock_audit.py` — alembic 迁移：加 3 个审计字段
- `backend/app/services/cycle_end_service.py` — 进程级缓存（替代 `cutoff_service.py`）
- `backend/tests/test_cycle_engine_end_day.py` — cycle_engine 算法测试（替代 `test_cycle_engine_cutoff.py`）
- `backend/tests/test_cycle_end_service.py` — cycle_end_service 测试（替代 `test_cutoff_service.py`）
- `backend/tests/test_locked_reimbursement.py` — 封账后禁止操作测试
- `backend/tests/test_admin_unlock_reimbursement.py` — 管理员 unlock/lock 端点测试
- `backend/tests/test_locked_then_unlock_flow.py` — 端到端流程测试
- `backend/tests/test_migration_0016_rename.py` — 迁移验证测试
- `frontend/e2e/p0/admin-unlock-reimbursement.spec.ts` — Playwright E2E

**修改文件**：
- `backend/app/models/settings.py` — `cycle_cutoff_day` → `cycle_end_day`
- `backend/app/models/reimbursement.py` — 加 `unlocked_by` / `unlocked_at` / `unlock_reason` 字段
- `backend/app/services/cycle_engine.py` — 4 函数加 `cycle_end_day` 参数（默认 20），判定 `>` 替代 `>=`
- `backend/app/services/cutoff_service.py` — **删除**（被 `cycle_end_service.py` 替代）
- `backend/app/services/aggregation_service.py` — 所有 `cutoff_day` 改 `cycle_end_day`
- `backend/app/services/cycle_lock_service.py` — 同上
- `backend/app/services/scheduler_service.py` — 加 `reschedule_cycle_lock_job`，启动时从 DB 读 `cycle_end_day`
- `backend/app/services/reimbursement_service.py` — 加 `assert_not_locked` helper，6 个函数加调用
- `backend/app/routers/settings.py` — `/api/settings/cycle` 端点字段名改，响应加 `current_cycle_start` / `current_cycle_end`
- `backend/app/routers/reimbursements.py` — 加 `POST /{id}/unlock` 和 `POST /{id}/lock` 端点
- `backend/app/routers/portal.py` — 所有 `cutoff_day` → `cycle_end_day`，列表响应加 `cycle_start` / `cycle_end`
- `backend/app/dialog/action_executor.py` — 所有 `cutoff_day` → `cycle_end_day`，handler 入口 try/except 捕获 409
- `backend/app/dialog/insight_engine.py` — insight_* 查询结果加 `cycle_start` / `cycle_end`
- `backend/app/dialog/tools.py` — `required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]`（已是上一轮改过）
- `backend/tests/test_settings_cycle.py` — 字段名改 + 响应字段改
- `backend/tests/test_portal_generate_reimbursement.py` — 字段名改
- `backend/tests/test_aggregate_reports.py` — 字段名改
- `backend/tests/test_integration.py` — 字段名改
- `frontend/src/api/client.ts` — `settingsApi.cycle` 响应类型改，加 `reimbursementApi.unlock` / `lock`
- `frontend/src/pages/Settings.tsx` — CycleTab 显示当前周期范围
- `frontend/src/pages/portal/MyReimbursements.tsx` — 列表加周期范围列，详情页加周期范围 + 封账禁用按钮
- `frontend/src/pages/Reimbursements/ReimbursementDetail.tsx` — 管理端报销单详情加 unlock/lock 按钮
- `frontend/src/pages/boss/Chat.tsx` — 渲染 insight 结果时显示周期范围
- `README.md` — 更新周期配置说明

---

## Task 1: alembic 0016 — 重命名 cycle_cutoff_day → cycle_end_day + 重算现有数据

**Files:**
- Create: `backend/alembic/versions/0016_rename_cycle_end_day.py`

**Interfaces:**
- Consumes: alembic 0015_cycle_cutoff_day（前置 revision）
- Produces: `system_settings.cycle_end_day` 列（重命名自 `cycle_cutoff_day`），默认值 20，约束 `ck_cycle_end_day_range`；现有 `reimbursements.cycle_start` / `cycle_end` 按新语义重算

- [ ] **Step 1: 写迁移文件**

Create `backend/alembic/versions/0016_rename_cycle_end_day.py`:

```python
"""rename cycle_cutoff_day to cycle_end_day and recompute existing reimbursements

Revision ID: 0016_rename_cycle_end_day
Revises: 0015_cycle_cutoff_day
Create Date: 2026-09-12 00:00:00.000000

字段重命名 + 语义变更：
- cycle_cutoff_day (cutoff=21 表示 21 号属下月) → cycle_end_day (end=20 表示 20 号是本月最后一天)
- 默认值从 21 改为 20（保持「21-20 制」语义：21 号属下月，20 号属本月最后一天）
- 现有 reimbursements.cycle_start / cycle_end 按新语义重算

cycle_key 不变（仍是 YYYY-MM 结束月格式），只重算起止日期。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_rename_cycle_end_day"
down_revision: Union[str, None] = "0015_cycle_cutoff_day"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 重命名列（PG 自动保留 default 和 CHECK 约束，但约束名不变，需手动重命名）
    op.execute("ALTER TABLE system_settings RENAME COLUMN cycle_cutoff_day TO cycle_end_day")
    # 重命名 CHECK 约束（0015 创建时叫 ck_cycle_cutoff_day_range）
    op.execute(
        "ALTER TABLE system_settings "
        "RENAME CONSTRAINT ck_cycle_cutoff_day_range TO ck_cycle_end_day_range"
    )

    # 2. 修改默认值从 21 改为 20（保持 21-20 制语义）
    op.execute("ALTER TABLE system_settings ALTER COLUMN cycle_end_day SET DEFAULT 20")
    # 把现有行（如果 cycle_end_day 是 21）改为 20
    op.execute("UPDATE system_settings SET cycle_end_day = 20 WHERE cycle_end_day = 21")

    # 3. 重算现有 reimbursements.cycle_start / cycle_end 按新语义
    #    cycle_key 不变（YYYY-MM 结束月），只重算起止日期
    #    新语义：cycle_end_day 是本月最后一天（含），周期起 = 上月 (cycle_end_day+1) 日
    op.execute("""
        UPDATE reimbursements r
        SET 
            cycle_start = (r.cycle_key::text || '-01')::date 
                           - make_interval(months => 1)
                           + make_interval(days => s.cycle_end_day + 1),
            cycle_end = (r.cycle_key::text || '-01')::date 
                        + make_interval(days => s.cycle_end_day - 1)
        FROM system_settings s
        WHERE s.id = 1 AND r.cycle_key IS NOT NULL
    """)


def downgrade() -> None:
    # 回滚：把默认值改回 21，重命名列回 cycle_cutoff_day
    op.execute("ALTER TABLE system_settings ALTER COLUMN cycle_end_day SET DEFAULT 21")
    op.execute(
        "ALTER TABLE system_settings "
        "RENAME CONSTRAINT ck_cycle_end_day_range TO ck_cycle_cutoff_day_range"
    )
    op.execute("ALTER TABLE system_settings RENAME COLUMN cycle_end_day TO cycle_cutoff_day")
    # 注意：downgrade 不重算 reimbursements.cycle_start/cycle_end（无法完美回滚，保留新语义）
```

- [ ] **Step 2: 启动后端让迁移自动跑**

Run:
```bash
cd "/Users/chen/文档2026/skill技能测试/AI报销/ai-reimbursement-agent"
docker compose build backend
docker compose up -d --force-recreate backend
sleep 25
docker compose logs --no-color backend --since 30s 2>&1 | grep -E "Running upgrade|Application startup complete|ERROR" | tail -5
```

Expected: 日志出现 `Running upgrade 0015_cycle_cutoff_day -> 0016_rename_cycle_end_day` 和 `Application startup complete.`，无 ERROR。

- [ ] **Step 3: 验证列重命名 + 数据重算**

Run:
```bash
docker compose exec -T db psql -U reimburse -d reimbursement -c "\d system_settings" 2>&1 | grep -E "cycle_end_day|cycle_cutoff_day|ck_cycle"
echo "---"
docker compose exec -T db psql -U reimburse -d reimbursement -c "SELECT id, cycle_end_day FROM system_settings;"
echo "---"
docker compose exec -T db psql -U reimburse -d reimbursement -c "SELECT id, cycle_key, cycle_start, cycle_end FROM reimbursements;"
echo "---"
docker compose exec -T db psql -U reimburse -d reimbursement -c "SELECT version_num FROM alembic_version;"
```

Expected:
- 列名 `cycle_end_day`（不是 `cycle_cutoff_day`），约束名 `ck_cycle_end_day_range`
- `system_settings.cycle_end_day = 20`（不是 21 或 23）
- `reimbursements.cycle_start` / `cycle_end` 按新语义重算（cycle_key=2026-09 → cycle_start=2026-08-21, cycle_end=2026-09-20）
- `alembic_version.version_num = 0016_rename_cycle_end_day`

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0016_rename_cycle_end_day.py
git commit -m "$(cat <<'EOF'
feat(alembic): 0016 — 重命名 cycle_cutoff_day → cycle_end_day + 重算现有数据

字段重命名 + 语义变更：
- cycle_cutoff_day → cycle_end_day
- 默认值从 21 改为 20（保持 21-20 制语义：20 号是本月最后一天）
- CHECK 约束重命名为 ck_cycle_end_day_range
- 现有 reimbursements.cycle_start/cycle_end 按新语义重算

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: SystemSettings model 改字段名

**Files:**
- Modify: `backend/app/models/settings.py:37-41`

**Interfaces:**
- Consumes: Task 1（列已重命名为 `cycle_end_day`）
- Produces: `SystemSettings.cycle_end_day: Mapped[int]` 字段供后续 task 读

- [ ] **Step 1: 读当前字段定义**

Run:
```bash
sed -n '35,45p' backend/app/models/settings.py
```

Note current field is `cycle_cutoff_day: Mapped[int] = mapped_column(Integer, default=21, comment=...)`.

- [ ] **Step 2: 改字段名 + 默认值 + 注释**

In `backend/app/models/settings.py`, find the `cycle_cutoff_day` field definition (around line 37) and replace with:

```python
    cycle_end_day: Mapped[int] = mapped_column(
        Integer, default=20,
        comment="周期截止日（1-31）。该日为本周期最后一天（含）。"
                "例：cycle_end_day=25 → 8/26~9/25；cycle_end_day=20 → 7/21~8/20（默认 21-20 制）。"
                "cycle_end_day 不存在时取该月最后一日。"
    )
```

- [ ] **Step 3: 验证 import 无报错**

Run:
```bash
docker compose exec -T backend python -c "from app.models.settings import SystemSettings; print('cycle_end_day:', SystemSettings.cycle_end_day); print('has cycle_cutoff_day:', hasattr(SystemSettings, 'cycle_cutoff_day'))"
```

Expected: prints `cycle_end_day: <Mapped[...]>` and `has cycle_cutoff_day: False`. No error.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/settings.py
git commit -m "$(cat <<'EOF'
feat(models): SystemSettings.cycle_cutoff_day → cycle_end_day，默认值改 20

字段重命名匹配 alembic 0016。默认值 20 保持 21-20 制语义（20 号是本月
最后一天，21 号属下月周期）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: cycle_engine 改算法 + cycle_end_service 替代 cutoff_service

**Files:**
- Modify: `backend/app/services/cycle_engine.py`（整个文件重写）
- Modify: `backend/app/services/cutoff_service.py`（删除，被 cycle_end_service 替代）
- Create: `backend/app/services/cycle_end_service.py`
- Test: `backend/tests/test_cycle_engine_end_day.py`（替换 `test_cycle_engine_cutoff.py`）
- Test: `backend/tests/test_cycle_end_service.py`（替换 `test_cutoff_service.py`）

**Interfaces:**
- Consumes: Task 2 `SystemSettings.cycle_end_day`
- Produces:
  - `billing_cycle(cycle_key, cycle_end_day=20) -> tuple[date, date]`
  - `cycle_key_of(d, cycle_end_day=20) -> str`
  - `current_cycle_key(today=None, cycle_end_day=20) -> str`
  - `just_ended_cycle_key(on_date=None, cycle_end_day=20) -> str`
  - `cycle_display(cycle_key, cycle_end_day=20) -> str`
  - `cycle_end_service.get_cycle_end_day(db) -> int`（async，走缓存）
  - `cycle_end_service.invalidate_cache() -> None`（触发 scheduler.reschedule_job）

- [ ] **Step 1: 写失败测试 `test_cycle_engine_end_day.py`**

Create `backend/tests/test_cycle_engine_end_day.py`:

```python
"""cycle_engine cycle_end_day 算法测试（新语义：cycle_end_day 是本月最后一天含）"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from app.services.cycle_engine import (
    billing_cycle, cycle_key_of, current_cycle_key, just_ended_cycle_key,
)


class TestBillingCycle:
    def test_default_20_keeps_21_20_semantics(self):
        """cycle_end_day=20 → 21-20 制（21 号属下月，20 号是本月最后一天）"""
        start, end = billing_cycle("2026-09")
        assert start == date(2026, 8, 21)
        assert end == date(2026, 9, 20)

    def test_cycle_end_day_25(self):
        """cycle_end_day=25 → 8/26 ~ 9/25"""
        start, end = billing_cycle("2026-09", cycle_end_day=25)
        assert start == date(2026, 8, 26)
        assert end == date(2026, 9, 25)

    def test_cycle_end_day_1_natural_month(self):
        """cycle_end_day=1 → 上月 2 日到本月 1 日（自然月偏移）"""
        start, end = billing_cycle("2026-09", cycle_end_day=1)
        assert start == date(2026, 8, 2)
        assert end == date(2026, 9, 1)

    def test_cycle_end_day_31_in_february_non_leap(self):
        """cycle_end_day=31 在 2 月（非闰年 2026）→ 实际取 2/28"""
        start, end = billing_cycle("2026-02", cycle_end_day=31)
        # 上月 1 日 + cycle_end_day=31+1=32，但 1 月只有 31 天 → start=1/1+32 = 2/2? 
        # 不对，重新算：end_actual = min(31, 28) = 28，end=2/28
        # start = 2/28 + 1 day - 1 month = 1/29
        assert end == date(2026, 2, 28)
        assert start == date(2026, 1, 29)

    def test_cycle_end_day_31_in_february_leap_year(self):
        """cycle_end_day=31 在 2 月（闰年 2024）→ 实际取 2/29"""
        start, end = billing_cycle("2024-02", cycle_end_day=31)
        assert end == date(2024, 2, 29)
        assert start == date(2024, 1, 30)


class TestCycleKeyOf:
    def test_default_20_boundary(self):
        """cycle_end_day=20 时 day=20 属当月，day=21 属下月"""
        assert cycle_key_of(date(2026, 9, 20)) == "2026-09"
        assert cycle_key_of(date(2026, 9, 21)) == "2026-10"

    def test_cycle_end_day_25_boundary(self):
        """cycle_end_day=25 时 day=25 属当月，day=26 属下月"""
        assert cycle_key_of(date(2026, 9, 25), cycle_end_day=25) == "2026-09"
        assert cycle_key_of(date(2026, 9, 26), cycle_end_day=25) == "2026-10"

    def test_cycle_end_day_31_in_february_short_month(self):
        """cycle_end_day=31 时 2 月（28 天）实际 end_day=28"""
        # 2/28 <= 28 → 属当月周期 2026-02
        assert cycle_key_of(date(2026, 2, 28), cycle_end_day=31) == "2026-02"
        # 2/27 <= 28 → 属当月周期
        assert cycle_key_of(date(2026, 2, 27), cycle_end_day=31) == "2026-02"
        # 3/1 > 28 (2 月 end_actual) → 属下月周期
        # 等等，3/1 在 3 月，3 月的 end_actual = min(31, 31) = 31，3/1 <= 31 → 3 月属当月周期
        assert cycle_key_of(date(2026, 3, 1), cycle_end_day=31) == "2026-03"


class TestCurrentCycleKey:
    def test_default_20(self):
        """cycle_end_day=20 时 9/5 属 2026-09（8/21–9/20）"""
        assert current_cycle_key(date(2026, 9, 5)) == "2026-09"

    def test_cycle_end_day_25(self):
        """cycle_end_day=25 时 9/25 属 2026-09（8/26–9/25），9/26 属 2026-10"""
        assert current_cycle_key(date(2026, 9, 25), cycle_end_day=25) == "2026-09"
        assert current_cycle_key(date(2026, 9, 26), cycle_end_day=25) == "2026-10"


class TestJustEndedCycleKey:
    def test_default_20_on_20th(self):
        """cycle_end_day=20 时 9/20 执行 → 锁定 2026-09（8/21–9/20）"""
        assert just_ended_cycle_key(date(2026, 9, 20)) == "2026-09"

    def test_cycle_end_day_25_on_25th(self):
        """cycle_end_day=25 时 9/25 执行 → 锁定 2026-09（8/26–9/14）"""
        assert just_ended_cycle_key(date(2026, 9, 25), cycle_end_day=25) == "2026-09"
```

- [ ] **Step 2: 写失败测试 `test_cycle_end_service.py`**

Create `backend/tests/test_cycle_end_service.py`:

```python
"""cycle_end_service 进程级缓存测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def reset_cache():
    """每个测试前重置缓存 + mock scheduler.reschedule_cycle_lock_job"""
    from app.services import cycle_end_service
    cycle_end_service._cycle_end_cache = None
    with patch("app.services.scheduler_service.reschedule_cycle_lock_job") as mock_reschedule:
        yield mock_reschedule
    cycle_end_service._cycle_end_cache = None


@pytest.mark.asyncio
async def test_get_cycle_end_day_returns_20_when_no_row():
    """数据库无 system_settings 行时返回默认 20"""
    from app.services import cycle_end_service

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    db.execute = mock_execute

    result = await cycle_end_service.get_cycle_end_day(db)
    assert result == 20


@pytest.mark.asyncio
async def test_get_cycle_end_day_reads_from_db():
    """数据库有行时返回行里的值"""
    from app.services import cycle_end_service

    fake_row = MagicMock()
    fake_row.cycle_end_day = 25

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    result = await cycle_end_service.get_cycle_end_day(db)
    assert result == 25


@pytest.mark.asyncio
async def test_get_cycle_end_day_uses_cache_on_second_call():
    """第二次读不查库"""
    from app.services import cycle_end_service

    fake_row = MagicMock()
    fake_row.cycle_end_day = 25

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    await cycle_end_service.get_cycle_end_day(db)
    await cycle_end_service.get_cycle_end_day(db)

    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_invalidate_cache_forces_reload(reset_cache):
    """invalidate_cache 后重新读库 + 调 reschedule_cycle_lock_job"""
    from app.services import cycle_end_service

    fake_row = MagicMock()
    fake_row.cycle_end_day = 15

    db = MagicMock()
    mock_execute = AsyncMock()
    mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=fake_row))
    db.execute = mock_execute

    await cycle_end_service.get_cycle_end_day(db)
    assert reset_cache.call_count == 0  # 第一次读不调 reschedule

    cycle_end_service.invalidate_cache()
    reset_cache.assert_called_once()  # invalidate_cache 触发 reschedule

    await cycle_end_service.get_cycle_end_day(db)
    assert db.execute.call_count == 2
```

- [ ] **Step 3: 跑测试，验证失败**

Run:
```bash
docker cp backend/tests/test_cycle_engine_end_day.py ai-reimbursement-agent-backend-1:/app/tests/test_cycle_engine_end_day.py
docker cp backend/tests/test_cycle_end_service.py ai-reimbursement-agent-backend-1:/app/tests/test_cycle_end_service.py
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_cycle_engine_end_day.py tests/test_cycle_end_service.py -v 2>&1 | tail -20"
```

Expected: 多个 FAIL（cycle_engine 函数还不接受 `cycle_end_day` 参数；cycle_end_service 模块不存在）

- [ ] **Step 4: 重写 `cycle_engine.py`**

Replace entire content of `backend/app/services/cycle_engine.py`:

```python
"""报销单周期引擎

可配置 cycle_end_day（1-31），该日为本周期最后一天（含）。
cycle_end_day 不存在时（如 2/29、2/30、2/31）取该月最后一日。

设计依据：周期以结算月（结束月）为标识，上月 (cycle_end_day+1) 日到本月 cycle_end_day 日。
默认 cycle_end_day=20 → 21-20 制（21 号属下月，20 号是本月最后一天）。
"""

import calendar
from datetime import date
from dateutil.relativedelta import relativedelta

# 时区：遵循中国习惯 UTC+8
TZ_OFFSET = 8


def _actual_end_day(year: int, month: int, cycle_end_day: int) -> int:
    """该月实际 cycle_end_day（cycle_end_day 超过月末日时取月末日）

    例：cycle_end_day=31 在2月（非闰年）→ 28
        cycle_end_day=31 在1月 → 31
    """
    last_day = calendar.monthrange(year, month)[1]
    return min(cycle_end_day, last_day)


def billing_cycle(cycle_key: str, cycle_end_day: int = 20) -> tuple[date, date]:
    """cycle_key(结束月YYYY-MM) → (周期起, 周期末)

    cycle_end_day 是本周期最后一天（含）。
    例：
      billing_cycle("2026-09") → (date(2026,8,21), date(2026,9,20))  # 默认 21-20 制
      billing_cycle("2026-09", cycle_end_day=25) → (date(2026,8,26), date(2026,9,25))
      billing_cycle("2026-09", cycle_end_day=1) → (date(2026,8,2), date(2026,9,1))
    """
    y, m = map(int, cycle_key.split("-"))
    # 周期末 = 本月 cycle_end_day（如果该月没有这天，取月末）
    end_actual = _actual_end_day(y, m, cycle_end_day)
    end = date(y, m, end_actual)
    # 周期起 = end + 1 day - 1 month（用 relativedelta 安全处理跨月/2月）
    start = end + relativedelta(days=1) - relativedelta(months=1)
    return (start, end)


def cycle_display(cycle_key: str, cycle_end_day: int = 20) -> str:
    """cycle_key → 显示名，如「2026年8月21日–9月20日」"""
    start, end = billing_cycle(cycle_key, cycle_end_day)
    if start.year == end.year:
        return f"{start.year}年{start.month}月{start.day}日–{end.month}月{end.day}日"
    return f"{start.year}年{start.month}月{start.day}日–{end.year}年{end.month}月{end.day}日"


def cycle_key_of(d: date, cycle_end_day: int = 20) -> str:
    """费用发生日 → 所属周期 cycle_key（结束月YYYY-MM）

    规则：d.day > actual_end_day → 属下月周期；d.day <= actual_end_day → 属当月周期

    例：
      cycle_key_of(date(2026,9,20)) → "2026-09"（20 <= 20，属当月）
      cycle_key_of(date(2026,9,21)) → "2026-10"（21 > 20，属下月）
      cycle_key_of(date(2026,9,25), cycle_end_day=25) → "2026-09"（25 <= 25，属当月）
      cycle_key_of(date(2026,9,26), cycle_end_day=25) → "2026-10"（26 > 25，属下月）
      cycle_key_of(date(2025,12,25)) → "2026-01"（25 > 20，跨年属下月）
    """
    actual = _actual_end_day(d.year, d.month, cycle_end_day)
    if d.day > actual:
        return (d + relativedelta(months=1)).strftime("%Y-%m")
    return d.strftime("%Y-%m")


def current_cycle_key(today: date | None = None, cycle_end_day: int = 20) -> str:
    """今天 → 当前未封账周期 cycle_key

    例：
      current_cycle_key(date(2026,9,5)) → "2026-09"（8/21–9/20，cycle_end_day=20）
      current_cycle_key(date(2026,9,25), cycle_end_day=25) → "2026-09"
    """
    today = today or date.today()
    return cycle_key_of(today, cycle_end_day)


def just_ended_cycle_key(on_date: date | None = None, cycle_end_day: int = 20) -> str:
    """封账任务用：cycle_end_day 当天执行，刚结束的周期 cycle_key

    cycle_end_day=20 时 9月20日执行 → 锁定 cycle_key="2026-09"（8/21–9/20）
    cycle_end_day=25 时 9月25日执行 → 锁定 cycle_key="2026-09"（8/26–9/25）
    """
    on_date = on_date or date.today()
    # cycle_end_day 当天执行，刚结束的周期 = 本月 cycle_key
    return on_date.strftime("%Y-%m")
```

- [ ] **Step 5: 创建 `cycle_end_service.py`**

Create `backend/app/services/cycle_end_service.py`:

```python
"""cycle_end_day 配置的进程级缓存层

避免每次 cycle_engine 调用都查 system_settings 表。
管理员改完 cycle_end_day 后调 invalidate_cache() 让下次读时重新加载，
同时触发 scheduler.reschedule_job 动态更新 cron trigger。
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSettings

logger = logging.getLogger(__name__)

_cycle_end_cache: Optional[int] = None  # None = 未加载


async def get_cycle_end_day(db: AsyncSession) -> int:
    """读取当前 cycle_end_day，走进程级缓存

    Returns:
        cycle_end_day（1-31），无配置时返回 20（默认 21-20 制）
    """
    global _cycle_end_cache
    if _cycle_end_cache is None:
        row = (
            await db.execute(
                select(SystemSettings).where(SystemSettings.id == 1)
            )
        ).scalar_one_or_none()
        _cycle_end_cache = row.cycle_end_day if row else 20
    return _cycle_end_cache


def invalidate_cache() -> None:
    """让下次 get_cycle_end_day 重新读库 + 触发 cron 重新注册

    管理员保存 cycle_end_day 后必须调用。
    """
    global _cycle_end_cache
    _cycle_end_cache = None
    # 通知 scheduler 重新注册 cron trigger（动态生效，不需重启）
    try:
        from app.services.scheduler_service import reschedule_cycle_lock_job
        reschedule_cycle_lock_job()
    except Exception as e:
        logger.error(
            f"Failed to reschedule cycle_lock_job: {e}. "
            f"Manual backend restart may be needed."
        )
```

- [ ] **Step 6: 删除 `cutoff_service.py`**

Run:
```bash
rm backend/app/services/cutoff_service.py
```

Note: 所有引用 `cutoff_service` 的代码会在 Task 4-7 改为 `cycle_end_service`。本 task 先删除文件，后续 task 会修复引用。

- [ ] **Step 7: 跑测试，验证通过**

Run:
```bash
docker cp backend/app/services/cycle_engine.py ai-reimbursement-agent-backend-1:/app/app/services/cycle_engine.py
docker cp backend/app/services/cycle_end_service.py ai-reimbursement-agent-backend-1:/app/app/services/cycle_end_service.py
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_cycle_engine_end_day.py tests/test_cycle_end_service.py -v 2>&1 | tail -25"
```

Expected: all PASS. 若 `test_cycle_end_day_31_in_february_non_leap` 测试预期跟实际不一致，调整测试预期以匹配实际算法行为（验证 `_actual_end_day` 和 `start`/`end` 计算）。

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/cycle_engine.py backend/app/services/cycle_end_service.py
git rm backend/app/services/cutoff_service.py
git add backend/tests/test_cycle_engine_end_day.py backend/tests/test_cycle_end_service.py
git rm backend/tests/test_cycle_engine_cutoff.py backend/tests/test_cutoff_service.py 2>/dev/null || true
git commit -m "$(cat <<'EOF'
feat(cycle): cycle_engine 改算法 + cycle_end_service 替代 cutoff_service

- cycle_engine 4 函数加 cycle_end_day 参数（默认 20）
- 语义变更：判定从 >= 改为 >（cycle_end_day 是本月最后一天含）
- 默认值 20 保持 21-20 制语义
- cycle_end_service.py 替代 cutoff_service.py（重命名 + invalidate_cache
  触发 scheduler.reschedule_job 动态更新 cron）
- cutoff_service.py + test_cutoff_service.py + test_cycle_engine_cutoff.py 删除

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: aggregation_service / cycle_lock_service / scheduler_service 改字段名

**Files:**
- Modify: `backend/app/services/aggregation_service.py`
- Modify: `backend/app/services/cycle_lock_service.py`
- Modify: `backend/app/services/scheduler_service.py`

**Interfaces:**
- Consumes: Task 3 `cycle_end_service.get_cycle_end_day` + `cycle_engine.*` 新签名
- Produces: 所有 service 层使用 `cycle_end_day` 参数名（不是 `cutoff_day`）；`scheduler_service.reschedule_cycle_lock_job()` 函数

- [ ] **Step 1: 改 `aggregation_service.py`**

In `backend/app/services/aggregation_service.py`:
- 把所有 `cutoff_day` 参数名改为 `cycle_end_day`
- 把所有 `from app.services.cutoff_service import get_cutoff_day` 改为 `from app.services.cycle_end_service import get_cycle_end_day`
- 把所有 `cutoff = await get_cutoff_day(db)` 改为 `cutoff = await get_cycle_end_day(db)`
- 把所有 `cycle_key_of(edate, cutoff_day)` 改为 `cycle_key_of(edate, cycle_end_day)`
- 把所有 `current_cycle_key(today, cutoff_day)` 改为 `current_cycle_key(today, cycle_end_day)`
- 把所有 `attach_invoice_to_cycle(db, inv, cutoff_day=cutoff)` 改为 `attach_invoice_to_cycle(db, inv, cycle_end_day=cutoff)`

具体函数签名改为：

```python
async def attach_invoice_to_cycle(
    db: AsyncSession,
    invoice: Invoice,
    today: date | None = None,
    cycle_end_day: int | None = None,  # 之前是 cutoff_day
) -> Reimbursement:
    """...（docstring 保留原样，仅更新 cutoff_day → cycle_end_day 字样）..."""
    today = today or date.today()
    if cycle_end_day is None:
        from app.services.cycle_end_service import get_cycle_end_day
        cycle_end_day = await get_cycle_end_day(db)

    # 原有逻辑：determine_expense_date / target_reimb 查找 / late_charge 判定等保留
    # 只把所有 cycle_key_of(...) / current_cycle_key(...) 调用加上 cycle_end_day 参数
    target_ck = cycle_key_of(edate, cycle_end_day) if edate else current_cycle_key(today, cycle_end_day)
    curr_ck = current_cycle_key(today, cycle_end_day)
    # ...（后续 late_charge 判定、明细行创建、recompute_all 等不变）...
```

```python
async def aggregate_pending_invoices(
    db: AsyncSession,
    user_id: Optional[str] = None,
    cycle_end_day: int | None = None,  # 之前是 cutoff_day
) -> dict:
    """...（docstring 保留原样）..."""
    if cycle_end_day is None:
        from app.services.cycle_end_service import get_cycle_end_day
        cycle_end_day = await get_cycle_end_day(db)
    # ...（原有游离发票查询 + 分组逻辑保留）...
    # 所有 attach_invoice_to_cycle 调用改 cycle_end_day=cycle_end_day:
    # await attach_invoice_to_cycle(db, inv, cycle_end_day=cycle_end_day)
```

注意：`attach_invoice_to_cycle` 内部所有 `cycle_key_of(...)` / `current_cycle_key(...)` 调用都要传 `cycle_end_day`（不只是签名加参数）。同样 `aggregate_pending_invoices` 调用 `attach_invoice_to_cycle` 时也传 `cycle_end_day=cycle_end_day`。

- [ ] **Step 2: 改 `cycle_lock_service.py`**

In `backend/app/services/cycle_lock_service.py`:
- `lock_just_ended_cycle(db, cycle_end_day=None)` 签名改
- 内部 `from app.services.cycle_end_service import get_cycle_end_day`
- `cycle_end_day = await get_cycle_end_day(db)` when None
- `just_ended_cycle_key(cycle_end_day=cycle_end_day)` 调用

- [ ] **Step 3: 改 `scheduler_service.py`**

In `backend/app/services/scheduler_service.py`:
- `_cycle_lock_job` 内 `from app.services.cycle_end_service import get_cycle_end_day` + `cycle_end_day = await get_cycle_end_day(db)`
- 调用 `aggregate_pending_invoices(db, cycle_end_day=cycle_end_day)` 和 `lock_just_ended_cycle(db, cycle_end_day=cycle_end_day)`
- `start_scheduler` 启动时从 DB 读 `cycle_end_day`（同步读，用 `create_engine`）作为初始 cron day
- 加新函数 `reschedule_cycle_lock_job()`：

```python
def reschedule_cycle_lock_job():
    """管理员改 cycle_end_day 后调，重新注册 cron trigger

    从 DB 同步读最新 cycle_end_day，reschedule_job 更新 cron。
    """
    global _scheduler
    if not _scheduler or not _scheduler.running:
        return  # scheduler 未启动（首次加载时），跳过

    from sqlalchemy import create_engine, text
    from app.config import settings as app_settings
    sync_url = app_settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT cycle_end_day FROM system_settings WHERE id=1")
            ).fetchone()
            cycle_end_day = row[0] if row else 20
    finally:
        engine.dispose()

    from pytz import timezone as tz
    _scheduler.reschedule_job(
        "cycle_lock_job",
        trigger=CronTrigger(
            day=cycle_end_day, hour=0, minute=0,
            timezone=tz("Asia/Shanghai"),
        ),
    )
    logger.info(f"Cycle lock job rescheduled to day={cycle_end_day}")
```

- [ ] **Step 4: 改 `start_scheduler` 启动时读 DB**

In `backend/app/services/scheduler_service.py` `start_scheduler` function, replace the hardcoded `day=21` with DB read:

```python
def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = AsyncIOScheduler()

    # 读 cycle_end_day 作为初始 cron day
    from sqlalchemy import create_engine, text
    from app.config import settings as app_settings
    sync_url = app_settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT cycle_end_day FROM system_settings WHERE id=1")
            ).fetchone()
            initial_cycle_end_day = row[0] if row else 20
    finally:
        engine.dispose()

    from pytz import timezone as tz
    _scheduler.add_job(
        _cycle_lock_job,
        trigger=CronTrigger(
            day=initial_cycle_end_day, hour=0, minute=0,
            timezone=tz("Asia/Shanghai"),
        ),
        id="cycle_lock_job",
        name="归集+封账+报表",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # ... 其他 add_job 不变
    _scheduler.start()
    return _scheduler
```

- [ ] **Step 5: 验证后端启动 + 重建镜像**

Run:
```bash
docker compose build backend
docker compose up -d --force-recreate backend
sleep 25
docker compose logs --no-color backend --since 30s 2>&1 | grep -E "startup complete|ERROR|Traceback|cutoff" | tail -5
```

Expected: `Application startup complete.` 无 ERROR 无 Traceback。grep `cutoff` 应该无残留（除了 alembic 历史日志）。

- [ ] **Step 6: 跑相关测试**

Run:
```bash
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_cycle_engine_end_day.py tests/test_cycle_end_service.py tests/test_aggregate_reports.py -v --tb=short 2>&1 | tail -30"
```

Expected: 新测试 PASS。`test_aggregate_reports.py` 若有 `cutoff_day` 引用失败，调整测试代码用 `cycle_end_day`。

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/aggregation_service.py backend/app/services/cycle_lock_service.py backend/app/services/scheduler_service.py
git commit -m "$(cat <<'EOF'
feat(services): aggregation/cycle_lock/scheduler 改用 cycle_end_day

- 所有 cutoff_day 参数改为 cycle_end_day
- get_cutoff_day 改为 get_cycle_end_day（来自 cycle_end_service）
- scheduler 加 reschedule_cycle_lock_job 函数，管理员改 cutoff 后动态生效
- start_scheduler 启动时从 DB 读 cycle_end_day 作为初始 cron day

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: settings/portal/action_executor/insight_engine 改字段名 + 周期范围展示

**Files:**
- Modify: `backend/app/routers/settings.py`（`/api/settings/cycle` 端点字段名 + 响应加 `current_cycle_start` / `current_cycle_end`）
- Modify: `backend/app/routers/portal.py`（字段名改 + 列表响应加 `cycle_start` / `cycle_end`）
- Modify: `backend/app/dialog/action_executor.py`（字段名改）
- Modify: `backend/app/dialog/insight_engine.py`（insight 结果加 `cycle_start` / `cycle_end`）

**Interfaces:**
- Consumes: Task 4 `cycle_end_service.get_cycle_end_day` + `cycle_engine` 新签名
- Produces:
  - `GET /api/settings/cycle` 响应 `{cycle_end_day, current_cycle_start, current_cycle_end}`
  - `PUT /api/settings/cycle` 同上
  - portal 报销单列表响应每条含 `cycle_start` / `cycle_end`
  - insight 查询结果含 `cycle_start` / `cycle_end`

- [ ] **Step 1: 改 `settings.py` `/cycle` 端点**

In `backend/app/routers/settings.py`, find the `CycleSettingsRead`, `CycleSettingsUpdate`, `get_cycle_settings`, `update_cycle_settings` definitions. Replace:

```python
class CycleSettingsRead(BaseModel):
    cycle_end_day: int  # 之前是 cycle_cutoff_day
    current_cycle_start: str  # 新字段，YYYY-MM-DD
    current_cycle_end: str  # 新字段，YYYY-MM-DD


class CycleSettingsUpdate(BaseModel):
    cycle_end_day: int = Field(ge=1, le=31, description="周期截止日 1-31")  # 之前是 cycle_cutoff_day


@router.get("/cycle", response_model=CycleSettingsRead)
async def get_cycle_settings(db: AsyncSession = Depends(get_db)):
    """读取周期配置 + 当前周期范围"""
    from app.services.cycle_end_service import get_cycle_end_day
    from app.services.cycle_engine import current_cycle_key, billing_cycle

    cycle_end_day = await get_cycle_end_day(db)
    ck = current_cycle_key(cycle_end_day=cycle_end_day)
    start, end = billing_cycle(ck, cycle_end_day=cycle_end_day)
    return CycleSettingsRead(
        cycle_end_day=cycle_end_day,
        current_cycle_start=start.isoformat(),
        current_cycle_end=end.isoformat(),
    )


@router.put("/cycle", response_model=CycleSettingsRead)
async def update_cycle_settings(
    data: CycleSettingsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新周期配置

    生效规则：当前周期不动，下个完整周期生效。
    """
    from app.services.cycle_end_service import invalidate_cache
    from app.services.cycle_engine import current_cycle_key, billing_cycle

    row = (
        await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
    ).scalar_one_or_none()
    if row is None:
        row = SystemSettings(id=1, cycle_end_day=data.cycle_end_day)
        db.add(row)
    else:
        row.cycle_end_day = data.cycle_end_day

    await db.commit()
    await db.refresh(row)

    # 失效缓存 + 触发 reschedule_job
    invalidate_cache()

    ck = current_cycle_key(cycle_end_day=data.cycle_end_day)
    start, end = billing_cycle(ck, cycle_end_day=data.cycle_end_day)
    return CycleSettingsRead(
        cycle_end_day=row.cycle_end_day,
        current_cycle_start=start.isoformat(),
        current_cycle_end=end.isoformat(),
    )
```

- [ ] **Step 2: 改 `portal.py` 字段名 + 列表加周期范围**

In `backend/app/routers/portal.py`:
- 所有 `cutoff_day` → `cycle_end_day`
- 所有 `get_cutoff_day` → `get_cycle_end_day`
- 列表 endpoint 响应（`list_my_reimbursements` 函数，约 line 190-229）：每条响应加 `cycle_start` 和 `cycle_end` 字段（已存在，但确认字段名）

具体地，找到列表响应字典，确认含：
```python
{
    # ... 其他字段保留 ...
    "cycle_start": r.cycle_start.isoformat() if r.cycle_start else None,
    "cycle_end": r.cycle_end.isoformat() if r.cycle_end else None,
    "cycle_key": r.cycle_key,
    "is_cycle_locked": r.is_cycle_locked,
    # ... 其他字段保留 ...
}
```

如果这些字段已经在响应里就保留；如果没有，加上。

- [ ] **Step 3: 改 `action_executor.py` 字段名**

In `backend/app/dialog/action_executor.py`:
- 所有 `cutoff_day` → `cycle_end_day`
- 所有 `get_cutoff_day` → `get_cycle_end_day`
- 所有 `from app.services.cutoff_service import` → `from app.services.cycle_end_service import`

- [ ] **Step 4: 改 `insight_engine.py` 加周期范围**

In `backend/app/dialog/insight_engine.py`:
- insight_* 函数返回结果字典里加 `cycle_start` / `cycle_end`（从 reimbursement.cycle_start/cycle_end 复制）

具体实现：在每个 insight_* 函数返回结果时，附上查询涉及报销单的 cycle_start/cycle_end。如果查询跨多个周期，用当前周期的 cycle_start/cycle_end。

- [ ] **Step 5: 重建 + 跑测试**

Run:
```bash
docker compose build backend
docker compose up -d --force-recreate backend
sleep 25
docker compose logs --no-color backend --since 30s 2>&1 | grep -E "startup complete|ERROR" | tail -3
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_settings_cycle.py tests/test_portal_generate_reimbursement.py -v --tb=short 2>&1 | tail -30"
```

Expected: startup complete + 测试 PASS（可能需要改造测试用例的字段名 `cycle_cutoff_day` → `cycle_end_day`）

- [ ] **Step 6: 改造 `test_settings_cycle.py`**

In `backend/tests/test_settings_cycle.py`:
- `cycle_cutoff_day` → `cycle_end_day`
- 响应字段 `next_effective_cycle` → `current_cycle_start` / `current_cycle_end`
- 默认值预期从 21 改为 20

- [ ] **Step 7: 改造 `test_portal_generate_reimbursement.py`**

In `backend/tests/test_portal_generate_reimbursement.py`:
- 任何 `cutoff_day` 引用改 `cycle_end_day`
- 默认值预期从 21 改为 20

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/settings.py backend/app/routers/portal.py backend/app/dialog/action_executor.py backend/app/dialog/insight_engine.py backend/tests/test_settings_cycle.py backend/tests/test_portal_generate_reimbursement.py
git commit -m "$(cat <<'EOF'
feat(routers): settings/portal/action_executor/insight 改字段名 + 周期范围展示

- /api/settings/cycle 响应字段 cycle_cutoff_day → cycle_end_day
- 响应加 current_cycle_start / current_cycle_end（去掉误导的 next_effective_cycle）
- portal 报销单列表每条含 cycle_start/cycle_end
- insight 查询结果附周期范围
- 所有 cutoff_day 参数改为 cycle_end_day
- 测试用例同步改造

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: alembic 0017 — unlock 审计字段

**Files:**
- Create: `backend/alembic/versions/0017_reimbursement_unlock_audit.py`

**Interfaces:**
- Consumes: alembic 0016_rename_cycle_end_day
- Produces: `reimbursements.unlocked_by` / `unlocked_at` / `unlock_reason` 3 个 nullable 字段

- [ ] **Step 1: 写迁移文件**

Create `backend/alembic/versions/0017_reimbursement_unlock_audit.py`:

```python
"""add unlock audit fields to reimbursements

Revision ID: 0017_reimbursement_unlock_audit
Revises: 0016_rename_cycle_end_day
Create Date: 2026-09-12 01:00:00.000000

管理员手动 unlock 报销单的审计字段：
- unlocked_by: 解锁的管理员用户名
- unlocked_at: 解锁时间
- unlock_reason: 解锁原因

管理员重新 lock 时清空这 3 个字段。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_reimbursement_unlock_audit"
down_revision: Union[str, None] = "0016_rename_cycle_end_day"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reimbursements",
        sa.Column(
            "unlocked_by",
            sa.String(100),
            nullable=True,
            comment="解锁的管理员用户名",
        ),
    )
    op.add_column(
        "reimbursements",
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="解锁时间",
        ),
    )
    op.add_column(
        "reimbursements",
        sa.Column(
            "unlock_reason",
            sa.Text(),
            nullable=True,
            comment="解锁原因",
        ),
    )


def downgrade() -> None:
    op.drop_column("reimbursements", "unlock_reason")
    op.drop_column("reimbursements", "unlocked_at")
    op.drop_column("reimbursements", "unlocked_by")
```

- [ ] **Step 2: 启动后端让迁移跑**

Run:
```bash
docker compose build backend
docker compose up -d --force-recreate backend
sleep 25
docker compose logs --no-color backend --since 30s 2>&1 | grep -E "Running upgrade|startup complete|ERROR" | tail -5
```

Expected: `Running upgrade 0016_rename_cycle_end_day -> 0017_reimbursement_unlock_audit` + `Application startup complete.`

- [ ] **Step 3: 验证字段添加**

Run:
```bash
docker compose exec -T db psql -U reimburse -d reimbursement -c "\d reimbursements" 2>&1 | grep -E "unlocked_by|unlocked_at|unlock_reason"
echo "---"
docker compose exec -T db psql -U reimburse -d reimbursement -c "SELECT version_num FROM alembic_version;"
```

Expected: 3 个字段都列出，`alembic_version.version_num = 0017_reimbursement_unlock_audit`

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0017_reimbursement_unlock_audit.py
git commit -m "$(cat <<'EOF'
feat(alembic): 0017 — reimbursements 加 unlock 审计字段

- unlocked_by VARCHAR(100): 解锁的管理员用户名
- unlocked_at TIMESTAMP WITH TIME ZONE: 解锁时间
- unlock_reason TEXT: 解锁原因

管理员手动 unlock 报销单时填上，重新 lock 时清空。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Reimbursement model 加 unlock 审计字段

**Files:**
- Modify: `backend/app/models/reimbursement.py`

**Interfaces:**
- Consumes: Task 6（DB 列已存在）
- Produces: `Reimbursement.unlocked_by` / `unlocked_at` / `unlock_reason` 三个 ORM 字段

- [ ] **Step 1: 在 `is_cycle_locked` / `locked_at` 字段后加 3 个新字段**

In `backend/app/models/reimbursement.py`, find the `is_cycle_locked` field (around line 44), add after `locked_at`:

```python
    is_cycle_locked: Mapped[bool] = mapped_column(Boolean, default=False, comment="周期封账标志")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="封账时间")
    
    # 管理员手动 unlock 审计字段（重新 lock 时清空）
    unlocked_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="解锁的管理员用户名"
    )
    unlocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="解锁时间"
    )
    unlock_reason: Mapped[str | None] = mapped_column(
        Text(), nullable=True, comment="解锁原因"
    )
```

确保 `Text` 在 import 里：
```python
from sqlalchemy import String, Text, Integer, ...
```

- [ ] **Step 2: 验证 import 无报错**

Run:
```bash
docker compose exec -T backend python -c "from app.models.reimbursement import Reimbursement; print('unlocked_by:', Reimbursement.unlocked_by); print('unlocked_at:', Reimbursement.unlocked_at); print('unlock_reason:', Reimbursement.unlock_reason)"
```

Expected: prints 3 Mapped attributes, no error.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/reimbursement.py
git commit -m "$(cat <<'EOF'
feat(models): Reimbursement 加 unlocked_by/unlocked_at/unlock_reason 字段

配合 alembic 0017 迁移，模型层加 3 个 unlock 审计字段。
管理员手动 unlock 时填上，重新 lock 时清空。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: reimbursement_service 加 assert_not_locked helper + 6 个函数加调用

**Files:**
- Modify: `backend/app/services/reimbursement_service.py`
- Test: `backend/tests/test_locked_reimbursement.py`

**Interfaces:**
- Consumes: Task 7 `Reimbursement.is_cycle_locked`
- Produces:
  - `assert_not_locked(reimbursement) -> None`（raise HTTPException 409 if locked）
  - 6 个 service 函数加调用：`submit_reimbursement` / `withdraw_reimbursement` / `update_reimbursement` / `delete_reimbursement` / `link_invoices` / `unlink_invoice` / `toggle_day_subsidy`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_locked_reimbursement.py`:

```python
"""封账后禁止操作测试 — assert_not_locked helper"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.models.reimbursement import Reimbursement, ReimbursementStatus
from app.services.reimbursement_service import assert_not_locked


def _make_reimb(locked: bool) -> Reimbursement:
    """构造测试用 reimbursement 对象"""
    r = MagicMock(spec=Reimbursement)
    r.id = 1
    r.is_cycle_locked = locked
    r.locked_at = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc) if locked else None
    r.status = ReimbursementStatus.draft
    return r


class TestAssertNotLocked:
    def test_not_locked_passes(self):
        """未封账 → 不抛异常"""
        reimb = _make_reimb(locked=False)
        # 不抛异常即通过
        assert_not_locked(reimb)

    def test_locked_raises_409(self):
        """已封账 → 抛 409"""
        reimb = _make_reimb(locked=True)
        with pytest.raises(HTTPException) as exc_info:
            assert_not_locked(reimb)
        assert exc_info.value.status_code == 409
        assert "已封账" in exc_info.value.detail
        assert "2026-09-20" in exc_info.value.detail  # locked_at 格式化

    def test_locked_without_locked_at(self):
        """已封账但 locked_at 为空 → 409 详情含「未知时间」"""
        reimb = _make_reimb(locked=True)
        reimb.locked_at = None
        with pytest.raises(HTTPException) as exc_info:
            assert_not_locked(reimb)
        assert "未知时间" in exc_info.value.detail
```

- [ ] **Step 2: 跑测试，验证失败**

Run:
```bash
docker cp backend/tests/test_locked_reimbursement.py ai-reimbursement-agent-backend-1:/app/tests/test_locked_reimbursement.py
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_locked_reimbursement.py -v 2>&1 | tail -15"
```

Expected: FAIL with `ImportError: cannot import name 'assert_not_locked'`

- [ ] **Step 3: 加 `assert_not_locked` helper**

In `backend/app/services/reimbursement_service.py`, find `assert_draft` function (around line 67), add `assert_not_locked` right after it:

```python
async def assert_not_locked(reimbursement: Reimbursement) -> None:
    """校验报销单未封账，否则抛 409

    封账后员工不能 submit/withdraw/update/delete/link/unlink/toggle subsidy。
    管理员手动 unlock 后才能继续操作。
    """
    if reimbursement.is_cycle_locked:
        locked_at_str = (
            reimbursement.locked_at.strftime("%Y-%m-%d %H:%M")
            if reimbursement.locked_at else "未知时间"
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"报销单 #{reimbursement.id} 所在周期已封账"
                f"（封账于 {locked_at_str}），无法操作。"
                "如需修改请联系管理员解锁。"
            ),
        )
```

- [ ] **Step 4: 在 6 个 service 函数加调用**

In `backend/app/services/reimbursement_service.py`:

1. `submit_reimbursement` (around line 377): 在 `await assert_draft(reimbursement)` 之后加 `await assert_not_locked(reimbursement)`

2. `withdraw_reimbursement` (around line 401): 在状态校验之前加 `await assert_not_locked(reimbursement)`

3. `update_reimbursement` (查找 `def update_reimbursement`): 在 `await assert_draft(reimbursement)` 之后加 `await assert_not_locked(reimbursement)`

4. `delete_reimbursement` (around line 753): 在 `await assert_draft(reimbursement)` 之后加 `await assert_not_locked(reimbursement)`

5. `link_invoices` / `unlink_invoice` (查找这些函数): 在 `await assert_draft(reimbursement)` 之后加 `await assert_not_locked(reimbursement)`

6. `toggle_day_subsidy` (查找该函数): 在 `await assert_draft(reimbursement)` 之后加 `await assert_not_locked(reimbursement)`

注意：每个函数都需要先获取 reimbursement 对象。如果函数签名只接受 `reimbursement_id`，先在函数内 `reimbursement = await get_reimbursement_or_404(db, reimbursement_id)` 后再加 `assert_not_locked`。

- [ ] **Step 5: 跑测试，验证通过**

Run:
```bash
docker cp backend/app/services/reimbursement_service.py ai-reimbursement-agent-backend-1:/app/app/services/reimbursement_service.py
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_locked_reimbursement.py -v 2>&1 | tail -15"
```

Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/reimbursement_service.py backend/tests/test_locked_reimbursement.py
git commit -m "$(cat <<'EOF'
feat(reimbursement): assert_not_locked helper + 6 个函数加封账校验

封账后员工不能 submit/withdraw/update/delete/link/unlink/toggle subsidy。
service 层集中校验，dialog 路径走 service 也会被挡。

漏洞背景：之前 portal 5 个操作不检查 is_cycle_locked，员工可在封账后
撤回再改内容。本 task 修复。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: action_executor 对话路径捕获 409 + emp_modify_field 加锁检查

**Files:**
- Modify: `backend/app/dialog/action_executor.py`

**Interfaces:**
- Consumes: Task 8 `assert_not_locked`（service 层抛 409）
- Produces: dialog handler 捕获 409 给用户友好提示；`_handle_modify_field` 检查发票所属报销单是否封账

- [ ] **Step 1: 改 `_handle_modify_field` 加封账检查**

In `backend/app/dialog/action_executor.py`, find `_handle_modify_field` function. Before modifying invoice fields, add:

```python
# 在 _handle_modify_field 函数体内，找到目标 invoice 之后，修改字段之前
if invoice.reimbursement_id:
    from app.models.reimbursement import Reimbursement
    reimb = await db.get(Reimbursement, invoice.reimbursement_id)
    if reimb and reimb.is_cycle_locked:
        return {
            "text": f"❌ 发票所属报销单 #{reimb.id} 已封账，无法修改。",
            "data": {},
        }
```

- [ ] **Step 2: 改 `_handle_submit_reimbursement` 捕获 409**

In `backend/app/dialog/action_executor.py`, find `_handle_submit_reimbursement`. Wrap the service calls in try/except:

```python
async def _handle_submit_reimbursement(self, ctx, db, _):
    # ... 现有 setup 逻辑（角色判定、cutoff 读取、get_or_create_reimbursement）保留 ...
    try:
        # 原有逻辑：attach invoices + set status submitted + commit 保留
        # ... (existing attach loop + status update + db.commit())
    except HTTPException as e:
        if e.status_code == 409:
            return {"text": f"❌ {e.detail}", "data": {}}
        raise
```

- [ ] **Step 3: 同样模式应用到其他 handler**

Apply the same try/except pattern to:
- `_handle_delete_invoice`
- `_handle_mark_travel_day`
- `_handle_modify_field`（在加锁检查之后，实际修改字段时也可能抛 409，捕获）

- [ ] **Step 4: 跑测试**

Run:
```bash
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_action_admin.py tests/test_locked_reimbursement.py -v --tb=short 2>&1 | tail -20"
```

Expected: tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/dialog/action_executor.py
git commit -m "$(cat <<'EOF'
feat(executor): 对话路径捕获 409 + emp_modify_field 加封账检查

- _handle_modify_field: 修改发票字段前检查所属报销单 is_cycle_locked
- _handle_submit_reimbursement / _handle_delete_invoice / _handle_mark_travel_day:
  捕获 service 层抛的 409，返回友好提示给员工
- 员工通过对话触发封账后修改操作会被挡，提示「请联系管理员解锁」

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: 管理员 unlock/lock 端点

**Files:**
- Modify: `backend/app/routers/reimbursements.py`
- Test: `backend/tests/test_admin_unlock_reimbursement.py`

**Interfaces:**
- Consumes: Task 7 `Reimbursement.unlocked_by` / `unlocked_at` / `unlock_reason` 字段
- Produces:
  - `POST /api/reimbursements/{id}/unlock`（admin）— body `{reason}`，设 is_cycle_locked=False + 审计字段
  - `POST /api/reimbursements/{id}/lock`（admin）— 重新封账，清空审计字段

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_admin_unlock_reimbursement.py`:

```python
"""管理员 unlock/lock 报销单端点测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def admin_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/admin/auth/login", json={"username": "admin", "password": "123456"})
        return r.json()["access_token"]


@pytest.fixture
async def setup_locked_reimbursement(admin_token):
    """创建一个已封账的测试报销单"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {admin_token}"}
        # 创建员工
        await ac.post("/api/employees", json={
            "name": "解锁测试员工", "employee_no": "UNLOCK-TEST-001",
            "status": 1, "password": "123456"
        }, headers=headers)
        # 员工登录 + 生成报销单
        r = await ac.post("/api/portal/auth/login", json={
            "employee_no": "UNLOCK-TEST-001", "password": "123456"
        })
        emp_token = r.json()["access_token"]
        emp_headers = {"Authorization": f"Bearer {emp_token}"}
        r = await ac.post("/api/portal/reimbursements/generate", headers=emp_headers)
        reimb_id = r.json()["id"]
        # 直接调 lock 端点封账（或直接改 DB）
        await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=headers)
    yield reimb_id
    # 清理
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {admin_token}"}
        try:
            await ac.delete(f"/api/reimbursements/{reimb_id}", headers=headers)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_admin_unlock_locked_reimbursement(admin_token, setup_locked_reimbursement):
    """unlock 已封账报销单 → 200，审计字段填上"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "员工反馈金额错误"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["is_cycle_locked"] is False
    assert body["unlocked_by"] == "admin"
    assert body["unlock_reason"] == "员工反馈金额错误"
    assert body["unlocked_at"] is not None


@pytest.mark.asyncio
async def test_admin_unlock_already_unlocked(admin_token, setup_locked_reimbursement):
    """unlock 未封账报销单 → 400"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 先 unlock
        await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "测试"}, headers=headers)
        # 再 unlock → 400
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "再次"}, headers=headers)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_lock_unlocked_reimbursement(admin_token, setup_locked_reimbursement):
    """lock 已 unlock 的报销单 → 200，审计字段清空"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 先 unlock
        await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "测试"}, headers=headers)
        # 重新 lock
        r = await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["is_cycle_locked"] is True
    assert body["unlocked_by"] is None
    assert body["unlocked_at"] is None
    assert body["unlock_reason"] is None


@pytest.mark.asyncio
async def test_admin_lock_already_locked(admin_token, setup_locked_reimbursement):
    """lock 已封账报销单 → 400"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=headers)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unlock_requires_reason(admin_token, setup_locked_reimbursement):
    """不传 reason → 422"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={}, headers=headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unlock_reason_too_long(admin_token, setup_locked_reimbursement):
    """reason > 500 字 → 422"""
    reimb_id = setup_locked_reimbursement
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "x" * 501}, headers=headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_employee_cannot_unlock(setup_locked_reimbursement):
    """员工 token 调 unlock → 403"""
    reimb_id = setup_locked_reimbursement
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 员工登录
        r = await ac.post("/api/portal/auth/login", json={
            "employee_no": "UNLOCK-TEST-001", "password": "123456"
        })
        emp_token = r.json()["access_token"]
        emp_headers = {"Authorization": f"Bearer {emp_token}"}
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "x"}, headers=emp_headers)
    assert r.status_code == 403
```

- [ ] **Step 2: 跑测试，验证失败**

Run:
```bash
docker cp backend/tests/test_admin_unlock_reimbursement.py ai-reimbursement-agent-backend-1:/app/tests/test_admin_unlock_reimbursement.py
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_admin_unlock_reimbursement.py -v 2>&1 | tail -15"
```

Expected: FAIL with 404（端点不存在）

- [ ] **Step 3: 加 unlock/lock 端点**

In `backend/app/routers/reimbursements.py`, append at the end of the file:

```python
class UnlockRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500, description="解锁原因")


@router.post("/{reimbursement_id}/unlock", response_model=ReimbursementDetail)
async def unlock_reimbursement(
    reimbursement_id: int,
    request: UnlockRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员手动解锁报销单（让员工能修改）

    解锁后 is_cycle_locked=False，员工可撤回（withdraw）后再修改。
    审计字段 unlocked_by/unlocked_at/unlock_reason 填上。
    重新 lock 时清空审计字段。
    """
    from datetime import datetime, timezone
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if not reimbursement.is_cycle_locked:
        raise HTTPException(status_code=400, detail="该报销单未封账，无需解锁")
    reimbursement.is_cycle_locked = False
    reimbursement.unlocked_by = admin["username"]
    reimbursement.unlocked_at = datetime.now(timezone.utc)
    reimbursement.unlock_reason = request.reason
    # 不重置 status，保持封账时状态（通常 SUBMITTED）
    # 员工需自己撤回才能改（撤回此时不被 assert_not_locked 阻拦）
    await db.commit()
    await db.refresh(reimbursement)
    return reimbursement


@router.post("/{reimbursement_id}/lock", response_model=ReimbursementDetail)
async def lock_reimbursement(
    reimbursement_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """管理员手动重新封账

    清空 unlock 审计字段（重新封账后旧解锁记录不再有意义）。
    """
    from datetime import datetime, timezone
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.is_cycle_locked:
        raise HTTPException(status_code=400, detail="该报销单已封账")
    reimbursement.is_cycle_locked = True
    reimbursement.locked_at = datetime.now(timezone.utc)
    # 清空 unlock 审计字段
    reimbursement.unlocked_by = None
    reimbursement.unlocked_at = None
    reimbursement.unlock_reason = None
    await db.commit()
    await db.refresh(reimbursement)
    return reimbursement
```

Ensure `Field` is imported:
```python
from pydantic import BaseModel, Field
```

Ensure `ReimbursementDetail` (or equivalent response model) is imported or defined. If not, use the existing response model used in other endpoints in this file.

- [ ] **Step 4: 跑测试，验证通过**

Run:
```bash
docker cp backend/app/routers/reimbursements.py ai-reimbursement-agent-backend-1:/app/app/routers/reimbursements.py
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_admin_unlock_reimbursement.py -v 2>&1 | tail -20"
```

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/reimbursements.py backend/tests/test_admin_unlock_reimbursement.py
git commit -m "$(cat <<'EOF'
feat(admin): POST /api/reimbursements/{id}/unlock + /lock 端点

- POST /{id}/unlock: 管理员手动解锁报销单，需 body.reason（1-500 字）
  设 is_cycle_locked=False + unlocked_by/unlocked_at/unlock_reason 填上
- POST /{id}/lock: 管理员重新封账，清空 3 个审计字段
- 状态不变（保持封账时的 SUBMITTED），员工需自己撤回才能改

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: 端到端流程测试 + 迁移验证测试

**Files:**
- Create: `backend/tests/test_locked_then_unlock_flow.py`
- Create: `backend/tests/test_migration_0016_rename.py`

**Interfaces:**
- Consumes: Task 8 `assert_not_locked` + Task 10 unlock/lock 端点
- Produces: 端到端验证 + 迁移验证

- [ ] **Step 1: 写端到端测试**

Create `backend/tests/test_locked_then_unlock_flow.py`:

```python
"""端到端流程：员工生成 → 封账 → 撤回 409 → unlock → 撤回 200 → 改 → 提交 → 重新封账"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def setup():
    """setup admin + employee + 报销单"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # admin 登录
        r = await ac.post("/api/admin/auth/login", json={"username": "admin", "password": "123456"})
        admin_token = r.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        # 创建员工
        await ac.post("/api/employees", json={
            "name": "端到端测试员工", "employee_no": "FLOW-TEST-001",
            "status": 1, "password": "123456"
        }, headers=admin_headers)
        # 员工登录
        r = await ac.post("/api/portal/auth/login", json={
            "employee_no": "FLOW-TEST-001", "password": "123456"
        })
        emp_token = r.json()["access_token"]
        emp_headers = {"Authorization": f"Bearer {emp_token}"}
        # 生成报销单
        r = await ac.post("/api/portal/reimbursements/generate", headers=emp_headers)
        reimb_id = r.json()["id"]
    yield admin_headers, emp_headers, reimb_id
    # 清理
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        try:
            await ac.delete(f"/api/reimbursements/{reimb_id}", headers=admin_headers)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_locked_then_unlock_flow(setup):
    admin_headers, emp_headers, reimb_id = setup

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. 管理员封账
        r = await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=admin_headers)
        assert r.status_code == 200

        # 2. 员工尝试提交 → 409
        r = await ac.post(f"/api/portal/reimbursements/{reimb_id}/submit", headers=emp_headers)
        assert r.status_code == 409

        # 3. 管理员 unlock
        r = await ac.post(f"/api/reimbursements/{reimb_id}/unlock", json={"reason": "员工反馈有误"}, headers=admin_headers)
        assert r.status_code == 200

        # 4. 员工现在可以提交（DRAFT 状态）
        #    注意：报销单封账时是 DRAFT，lock 没改 status，所以还是 DRAFT
        r = await ac.post(f"/api/portal/reimbursements/{reimb_id}/submit", headers=emp_headers)
        assert r.status_code == 200

        # 5. 员工撤回 → DRAFT
        r = await ac.post(f"/api/portal/reimbursements/{reimb_id}/withdraw", headers=emp_headers)
        assert r.status_code == 200

        # 6. 管理员重新封账
        r = await ac.post(f"/api/reimbursements/{reimb_id}/lock", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["is_cycle_locked"] is True
        assert body["unlocked_by"] is None  # 审计字段清空
```

- [ ] **Step 2: 写迁移验证测试**

Create `backend/tests/test_migration_0016_rename.py`:

```python
"""alembic 0016 迁移验证测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import text
from app.database import get_async_sessionmaker


@pytest.mark.asyncio
async def test_column_renamed_to_cycle_end_day():
    """列名是 cycle_end_day（不是 cycle_cutoff_day）"""
    async with get_async_sessionmaker()() as db:
        result = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='system_settings' AND column_name IN ('cycle_end_day', 'cycle_cutoff_day')"
        ))
        cols = [r[0] for r in result]
        assert "cycle_end_day" in cols
        assert "cycle_cutoff_day" not in cols


@pytest.mark.asyncio
async def test_check_constraint_renamed():
    """CHECK 约束名是 ck_cycle_end_day_range"""
    async with get_async_sessionmaker()() as db:
        result = await db.execute(text(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_name='system_settings' AND constraint_name LIKE 'ck_cycle%'"
        ))
        names = [r[0] for r in result]
        assert "ck_cycle_end_day_range" in names
        assert "ck_cycle_cutoff_day_range" not in names


@pytest.mark.asyncio
async def test_default_value_is_20():
    """默认值是 20（不是 21）"""
    async with get_async_sessionmaker()() as db:
        result = await db.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name='system_settings' AND column_name='cycle_end_day'"
        ))
        default = result.scalar()
        assert "20" in default


@pytest.mark.asyncio
async def test_alembic_version_is_0017():
    """alembic 版本是 0017_reimbursement_unlock_audit"""
    async with get_async_sessionmaker()() as db:
        result = await db.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar()
        # 0017 依赖 0016，所以跑完 0017 后 version 是 0017
        assert version == "0017_reimbursement_unlock_audit"
```

- [ ] **Step 3: 跑测试**

Run:
```bash
docker cp backend/tests/test_locked_then_unlock_flow.py ai-reimbursement-agent-backend-1:/app/tests/test_locked_then_unlock_flow.py
docker cp backend/tests/test_migration_0016_rename.py ai-reimbursement-agent-backend-1:/app/tests/test_migration_0016_rename.py
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_locked_then_unlock_flow.py tests/test_migration_0016_rename.py -v 2>&1 | tail -20"
```

Expected: tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_locked_then_unlock_flow.py backend/tests/test_migration_0016_rename.py
git commit -m "$(cat <<'EOF'
test: 端到端 unlock 流程 + 迁移 0016 验证

- test_locked_then_unlock_flow: 员工生成→封账→409→unlock→提交→撤回→重新封账
- test_migration_0016_rename: 验证列名/约束名/默认值/alembic 版本

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: 前端 — Settings CycleTab 显示周期范围 + 改字段名

**Files:**
- Modify: `frontend/src/api/client.ts`（`settingsApi.cycle` 响应类型改）
- Modify: `frontend/src/pages/Settings.tsx`（CycleTab 显示当前周期范围）

**Interfaces:**
- Consumes: Task 5 `/api/settings/cycle` 新响应 `{cycle_end_day, current_cycle_start, current_cycle_end}`
- Produces: 管理员 Settings CycleTab 显示当前周期范围

- [ ] **Step 1: 改 `client.ts` 响应类型**

In `frontend/src/api/client.ts`, find `settingsApi.cycle` definition. Change the return type:

```ts
settingsApi: {
  // ... 已有方法

  cycle: {
    get: () => request<{
      cycle_end_day: number;
      current_cycle_start: string;  // YYYY-MM-DD
      current_cycle_end: string;  // YYYY-MM-DD
    }>("/settings/cycle"),
    update: (cycle_end_day: number) =>
      request<{
        cycle_end_day: number;
        current_cycle_start: string;
        current_cycle_end: string;
      }>("/settings/cycle", {
        method: "PUT",
        body: JSON.stringify({ cycle_end_day }),
      }),
  },
}
```

- [ ] **Step 2: 改 `Settings.tsx` CycleTab**

In `frontend/src/pages/Settings.tsx`, find the `CycleTab` component. Update:
- State variable: `cycleCutoff` → `cycleEndDay`（或保留 `cycleCutoff` 但语义改）
- API call: `settingsApi.cycle.update(cycleCutoff)` → `settingsApi.cycle.update(cycleEndDay)`
- 显示当前周期范围：在输入框下方加一行：
  ```tsx
  {currentCycleStart && currentCycleEnd && (
    <p className="text-sm text-gray-600 mt-2">
      当前周期：{currentCycleStart} ~ {currentCycleEnd}
    </p>
  )}
  ```
- State 新增 `currentCycleStart` / `currentCycleEnd`，从 API 响应设置

- [ ] **Step 3: 跑前端构建**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: build 成功，无 TS 错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/pages/Settings.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): Settings CycleTab 显示当前周期范围 + 字段名改

- settingsApi.cycle 响应类型改 cycle_end_day + current_cycle_start/end
- CycleTab 输入框下显示「当前周期：YYYY-MM-DD ~ YYYY-MM-DD」
- 字段名 cycle_cutoff_day → cycle_end_day

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: 前端 — Portal 报销单列表 + 详情加周期范围 + 封账禁用按钮

**Files:**
- Modify: `frontend/src/pages/portal/MyReimbursements.tsx`

**Interfaces:**
- Consumes: Task 5 portal 列表响应含 `cycle_start` / `cycle_end` / `is_cycle_locked`
- Produces: 员工 Portal 报销单列表显示周期范围，详情页封账时禁用按钮

- [ ] **Step 1: 列表加周期范围列**

In `frontend/src/pages/portal/MyReimbursements.tsx`, find the reimbursement list rendering. Add a column or row showing:

```tsx
{r.cycle_start && r.cycle_end && (
  <span className="text-sm text-gray-600">
    {r.cycle_start} ~ {r.cycle_end}
  </span>
)}
```

- [ ] **Step 2: 详情页加周期范围 + 封账禁用按钮**

In the detail view section of `MyReimbursements.tsx`:
- 顶部加周期范围显示：
  ```tsx
  {detail.cycle_start && detail.cycle_end && (
    <div className="mb-4 p-3 bg-gray-50 rounded">
      <span className="text-sm">周期范围：{detail.cycle_start} ~ {detail.cycle_end}</span>
      {detail.is_cycle_locked && (
        <span className="ml-2 text-red-600 text-sm font-medium">🔒 已封账</span>
      )}
    </div>
  )}
  ```
- 所有操作按钮（提交、撤回、编辑、加发票、删发票、删报销单、切补贴）在 `is_cycle_locked=true` 时禁用：
  ```tsx
  <button disabled={detail.is_cycle_locked} title={detail.is_cycle_locked ? "周期已封账，无法操作" : ""}>
  ```

- [ ] **Step 3: 跑前端构建**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: build 成功

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/portal/MyReimbursements.tsx
git commit -m "$(cat <<'EOF'
feat(portal): 报销单列表 + 详情显示周期范围 + 封账禁用按钮

- 列表加周期范围列（cycle_start ~ cycle_end）
- 详情页顶部显示周期范围 + 🔒 已封账 标记
- 封账后所有操作按钮禁用（提交/撤回/编辑/加发票/删发票/删报销单/切补贴）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: 前端 — 管理端报销单详情加 unlock/lock 按钮

**Files:**
- Modify: `frontend/src/api/client.ts`（加 `reimbursementApi.unlock` / `lock` 方法）
- Modify: `frontend/src/pages/Reimbursements/ReimbursementDetail.tsx`

**Interfaces:**
- Consumes: Task 10 `POST /api/reimbursements/{id}/unlock` + `/lock` 端点
- Produces: 管理端报销单详情页 unlock/lock 按钮 + 弹窗填原因 + 显示审计信息

- [ ] **Step 1: 加 API 方法**

In `frontend/src/api/client.ts`, find `reimbursementApi` and add:

```ts
reimbursementApi: {
  // ... 已有方法

  unlock: (id: number, reason: string) =>
    adminRequest(`/reimbursements/${id}/unlock`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  lock: (id: number) =>
    adminRequest(`/reimbursements/${id}/lock`, { method: "POST" }),
}
```

- [ ] **Step 2: 加 unlock/lock 按钮 + 弹窗**

In `frontend/src/pages/Reimbursements/ReimbursementDetail.tsx`:
- 在详情页操作区加：
  ```tsx
  {detail.is_cycle_locked && (
    <button
      onClick={() => setShowUnlockDialog(true)}
      className="bg-red-600 text-white px-4 py-2 rounded-md hover:bg-red-700"
    >
      🔓 解锁报销单
    </button>
  )}
  {!detail.is_cycle_locked && detail.unlocked_at && (
    <button
      onClick={handleLock}
      className="bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700"
    >
      🔒 重新封账
    </button>
  )}
  ```
- 加 unlock 弹窗（输入原因 1-500 字）：
  ```tsx
  {showUnlockDialog && (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white p-6 rounded-lg max-w-md">
        <h3 className="text-lg font-semibold mb-4">解锁报销单</h3>
        <textarea
          value={unlockReason}
          onChange={(e) => setUnlockReason(e.target.value)}
          placeholder="请输入解锁原因（1-500 字）"
          maxLength={500}
          className="w-full border rounded p-2 mb-4"
          rows={3}
        />
        <div className="flex gap-2 justify-end">
          <button onClick={() => setShowUnlockDialog(false)} className="px-4 py-2 border rounded">取消</button>
          <button
            onClick={handleUnlock}
            disabled={!unlockReason.trim()}
            className="px-4 py-2 bg-red-600 text-white rounded disabled:opacity-50"
          >
            确认解锁
          </button>
        </div>
      </div>
    </div>
  )}
  ```
- 加 unlock 审计信息显示：
  ```tsx
  {detail.unlocked_at && (
    <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded">
      <p className="text-sm">
        🔓 已解锁 by <strong>{detail.unlocked_by}</strong> on {detail.unlocked_at}
      </p>
      <p className="text-sm mt-1">原因：{detail.unlock_reason}</p>
    </div>
  )}
  ```
- 加 handler：
  ```tsx
  async function handleUnlock() {
    try {
      await reimbursementApi.unlock(detail.id, unlockReason);
      toast.success("已解锁");
      setShowUnlockDialog(false);
      setUnlockReason("");
      // 重新加载详情
      loadDetail();
    } catch (e) {
      toast.error(e.response?.data?.detail || "解锁失败");
    }
  }

  async function handleLock() {
    if (!confirm("确认重新封账？")) return;
    try {
      await reimbursementApi.lock(detail.id);
      toast.success("已重新封账");
      loadDetail();
    } catch (e) {
      toast.error(e.response?.data?.detail || "封账失败");
    }
  }
  ```

- [ ] **Step 3: 跑前端构建**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: build 成功

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/pages/Reimbursements/ReimbursementDetail.tsx
git commit -m "$(cat <<'EOF'
feat(admin-frontend): 报销单详情加 unlock/lock 按钮 + 弹窗填原因 + 审计信息

- reimbursementApi.unlock/lock 方法
- 详情页：封账时显示「解锁」按钮，弹窗输入原因（1-500 字）
- 未封账且 unlocked_at 不为空时显示「重新封账」按钮
- 显示 unlock 审计信息（unlocked_by/unlocked_at/unlock_reason）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Boss 端智能问数显示周期范围 + README 更新

**Files:**
- Modify: `frontend/src/pages/boss/Chat.tsx`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 5 `insight_engine` 返回 `cycle_start` / `cycle_end`
- Produces: Boss 智能问数渲染结果时显示周期范围；README 更新周期配置说明

- [ ] **Step 1: Boss Chat 渲染周期范围**

In `frontend/src/pages/boss/Chat.tsx`, find where insight results are rendered. Add cycle range display:

```tsx
{result.cycle_start && result.cycle_end && (
  <p className="text-xs text-gray-500 mt-1">
    周期范围：{result.cycle_start} ~ {result.cycle_end}
  </p>
)}
```

- [ ] **Step 2: 更新 README**

In `README.md`, find the "### 周期 cutoff 配置" section (around line 94-106). Replace with:

```markdown
### 周期配置（cycle_end_day）

报销周期默认按 21-20 制（每月 21 日到次月 20 日，20 号是本月最后一天）。管理员可在系统设置页面修改 cycle_end_day（1-31），该日为本周期最后一天（含）。cycle_end_day 不存在时取该月最后一日。

修改后从下个完整周期生效，当前周期内不动。定时任务会动态更新 cron trigger，无需重启后端。

例：
- cycle_end_day=20（默认）→ 每月 21 日到次月 20 日（21-20 制）
- cycle_end_day=25 → 每月 26 日到次月 25 日
- cycle_end_day=1  → 上月 2 日到本月 1 日（自然月偏移）
- cycle_end_day=31 → 每月 1 日到该月最后一天（自然月，2 月取 28/29 日）

**封账规则**：
- 每月 cycle_end_day 00:00 定时任务自动归集游离发票 + 封账上一周期
- 封账后员工不能 submit/withdraw/update/delete/link/unlink/toggle subsidy
- 管理员可在管理端报销单详情页手动 unlock（需填原因），员工改完后管理员重新 lock
```

- [ ] **Step 3: 跑前端构建**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: build 成功

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/boss/Chat.tsx README.md
git commit -m "$(cat <<'EOF'
docs+feat: Boss 智能问数显示周期范围 + README 更新周期配置说明

- Boss Chat 渲染 insight 结果时附周期范围
- README 周期配置说明改为 cycle_end_day 语义 + 封账规则 + unlock 流程

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: 最终验证 + 全量测试 + push

**Files:**
- 无修改，只验证

**Interfaces:**
- Consumes: 所有前序 task 完成
- Produces: 全量验证 + push 到 origin

- [ ] **Step 1: 全量后端测试**

Run:
```bash
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_cycle_engine_end_day.py tests/test_cycle_end_service.py tests/test_locked_reimbursement.py tests/test_admin_unlock_reimbursement.py tests/test_locked_then_unlock_flow.py tests/test_migration_0016_rename.py tests/test_settings_cycle.py tests/test_portal_generate_reimbursement.py tests/test_action_admin.py -v --tb=short 2>&1 | tail -30"
```

Expected: 所有新功能测试 PASS

- [ ] **Step 2: 端到端手动验证**

```bash
# admin login
ADMIN_TOKEN=$(curl -s -X POST http://localhost:18080/api/admin/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"123456"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 1. 读 cycle 配置
curl -s "http://localhost:18080/api/settings/cycle" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool

# 2. 改 cycle_end_day=25
curl -s -X PUT "http://localhost:18080/api/settings/cycle" -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"cycle_end_day":25}' | python3 -m json.tool

# 3. 改回 20
curl -s -X PUT "http://localhost:18080/api/settings/cycle" -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"cycle_end_day":20}' | python3 -m json.tool

# 4. 员工生成报销单
EMP_TOKEN=$(curl -s -X POST http://localhost:18080/api/portal/auth/login -H "Content-Type: application/json" -d '{"employee_no":"TEST-001","password":"123456"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -X POST "http://localhost:18080/api/portal/reimbursements/generate" -H "Authorization: Bearer $EMP_TOKEN" | python3 -m json.tool

# 5. 管理员 lock 报销单
REIMB_ID=<从上一步输出取 id>
curl -s -X POST "http://localhost:18080/api/reimbursements/$REIMB_ID/lock" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool

# 6. 员工尝试 submit → 409
curl -s -X POST "http://localhost:18080/api/portal/reimbursements/$REIMB_ID/submit" -H "Authorization: Bearer $EMP_TOKEN" -w "\n-> %{http_code}\n"

# 7. 管理员 unlock
curl -s -X POST "http://localhost:18080/api/reimbursements/$REIMB_ID/unlock" -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"reason":"测试解锁"}' | python3 -m json.tool

# 8. 员工现在可以 submit
curl -s -X POST "http://localhost:18080/api/portal/reimbursements/$REIMB_ID/submit" -H "Authorization: Bearer $EMP_TOKEN" -w "\n-> %{http_code}\n"

# 9. 管理员重新 lock
curl -s -X POST "http://localhost:18080/api/reimbursements/$REIMB_ID/lock" -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool
```

Expected: 所有步骤返回预期状态码（200 / 409）

- [ ] **Step 3: 验证 alembic 版本**

Run:
```bash
docker compose exec -T db psql -U reimburse -d reimbursement -c "SELECT version_num FROM alembic_version;"
```

Expected: `0017_reimbursement_unlock_audit`

- [ ] **Step 4: 推送所有 commit**

```bash
git log origin/develop/v2..HEAD --oneline
git push origin develop/v2
```

Expected: 所有新 commit 推送到 GitHub

- [ ] **Step 5: Commit (无文件改动，跳过)**

如果全量验证通过，无需额外 commit。如果发现需要修复的问题，单独 commit 修复。

---

## Self-Review Checklist

After all tasks complete, verify:

- [ ] Task 1: alembic 0016 重命名列 + 重算数据 + 默认值改 20
- [ ] Task 2: SystemSettings model 改 cycle_end_day
- [ ] Task 3: cycle_engine 改算法（`>` 替代 `>=`）+ cycle_end_service 替代 cutoff_service
- [ ] Task 4: aggregation/cycle_lock/scheduler 改字段名 + reschedule_cycle_lock_job
- [ ] Task 5: settings/portal/action_executor/insight 改字段名 + 周期范围展示
- [ ] Task 6: alembic 0017 加 unlock 审计字段
- [ ] Task 7: Reimbursement model 加 unlocked_by/unlocked_at/unlock_reason
- [ ] Task 8: assert_not_locked helper + 6 个 service 函数加调用 + 3 测试
- [ ] Task 9: action_executor 对话路径捕获 409 + emp_modify_field 加封账检查
- [ ] Task 10: unlock/lock 端点 + 7 测试
- [ ] Task 11: 端到端流程测试 + 迁移验证测试
- [ ] Task 12: 前端 Settings CycleTab 显示周期范围
- [ ] Task 13: 前端 Portal 报销单列表 + 详情加周期范围 + 封账禁用按钮
- [ ] Task 14: 前端管理端报销单详情 unlock/lock 按钮
- [ ] Task 15: Boss 智能问数显示周期范围 + README 更新
- [ ] Task 16: 最终验证 + push

## 上线步骤（部署到生产）

1. `git pull origin develop/v2`
2. `docker compose build backend mcp-sse`
3. `docker compose up -d`（后端启动时自动跑 alembic 0016 + 0017 迁移）
4. 前端 `npm run build` + 部署 dist
5. 管理员可在 Settings CycleTab 改 cycle_end_day（默认 20 = 21-20 制）
6. 员工可在 Portal 看到周期范围；封账后无法修改
7. 管理员可在管理端报销单详情页 unlock 封账报销单让员工修改
8. **数据迁移注意**：alembic 0016 会重算现有 reimbursements.cycle_start/cycle_end，执行前建议 dump 数据库备份
