# 周期截止日重命名 + 封账后禁止操作 + 管理员手动解锁 设计

**日期**：2026-09-12
**分支**：develop/v2
**前置 commit**：0e8d7ba（final fix of 周期可配置 + 员工自生成报销单）

## 背景与目标

上一轮「周期可配置 + 员工自生成报销单」交付后，发现 3 个语义和安全性问题：

1. **字段命名混乱**：`cycle_cutoff_day` 语义不直观。客户期望「设置 25 表示 25 号是周期最后一天」。需要重命名为 `cycle_end_day` 并改语义。
2. **封账后仍可修改**：portal 端 5 个操作（submit / withdraw / update / delete / link/unlink）都不检查 `is_cycle_locked`，员工可在封账后撤回再改。
3. **封账后无法修复**：员工未及时生成报销单时，系统在 cutoff 日 0:00 自动归集 + 封账。若员工发现报销单有问题无法修改，需要管理员手动解锁能力。

## 需求边界（已确认）

### 需求 1：字段重命名 + 周期范围展示

- **字段重命名**：`cycle_cutoff_day` → `cycle_end_day`，语义改为「该日为周期最后一天（含）」。例：`cycle_end_day=25` → 周期 8/26 ~ 9/25。
- **默认值改为 20**（保持原「21-20 制」语义：21 号属下月，20 号属本月最后一天）。
- **现有数据重算**：alembic 迁移重命名列 + 重算现有 `reimbursements.cycle_start` / `cycle_end` 按新语义。现有数据均为测试数据，无保留顾虑。
- **4 处前端展示周期范围**：
  1. 管理员 Settings CycleTab：输入框下显示「当前周期：YYYY-MM-DD ~ YYYY-MM-DD」
  2. 员工 Portal 报销单列表：每行加周期范围列
  3. 员工 Portal 报销单详情：顶部加周期范围
  4. Boss 端智能问数查询结果：附周期范围
- **定时任务动态生效**：管理员保存后调 `scheduler.reschedule_job` 立即更新 cron，不需重启容器。

### 需求 2：封账后禁止 4 类操作

封账后（`is_cycle_locked=True`）员工端禁止：
- 禁止撤回（withdraw：SUBMITTED → DRAFT）— **核心漏洞修复**
- 禁止编辑 DRAFT 报销单（update reason/period）
- 禁止加/减发票（link/unlink invoices）
- 禁止删除报销单（delete）
- 禁止提交（submit，封账定时任务自动提交是另一条路径）

dialog 对话路径同样禁止（emp_modify_field / emp_submit_reimbursement 等）。

### 需求 3：管理员手动 unlock

- **粒度**：仅单报销单（不能整周期解锁）
- **审计**：3 个新字段 `unlocked_by` / `unlocked_at` / `unlock_reason`
- **unlock 后状态不变**：保持封账时的状态（通常 SUBMITTED），员工需自己撤回才能改
- **重新封账**：管理员手动 lock 端点，清空审计字段
- **闭环**：unlock → 员工改 → 员工重新提交 → 管理员重新封账

## 数据模型

### alembic 0016：重命名列 + 重算现有数据

```sql
-- 1. 重命名列
ALTER TABLE system_settings RENAME COLUMN cycle_cutoff_day TO cycle_end_day;
ALTER TABLE system_settings RENAME CONSTRAINT ck_cycle_cutoff_day_range TO ck_cycle_end_day_range;

-- 2. 修改默认值从 21 改为 20
ALTER TABLE system_settings ALTER COLUMN cycle_end_day SET DEFAULT 20;

-- 3. 重算现有 reimbursements.cycle_start / cycle_end 按新语义
UPDATE reimbursements r
SET 
    cycle_start = (r.cycle_key::text || '-01')::date 
                  - make_interval(months => 1)
                  + make_interval(days => s.cycle_end_day + 1),
    cycle_end = (r.cycle_key::text || '-01')::date 
                + make_interval(days => s.cycle_end_day - 1)
FROM system_settings s
WHERE s.id = 1;
```

### alembic 0017：unlock 审计字段

```sql
ALTER TABLE reimbursements ADD COLUMN unlocked_by VARCHAR(100);
ALTER TABLE reimbursements ADD COLUMN unlocked_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE reimbursements ADD COLUMN unlock_reason TEXT;
```

### `backend/app/models/settings.py` 改动

```python
cycle_end_day: Mapped[int] = mapped_column(
    Integer, default=20,
    comment="周期截止日（1-31）。该日为本周期最后一天（含）。例：cycle_end_day=25 → 8/26~9/25。"
            "cycle_end_day 不存在时取该月最后一日。默认 20 = 21-20制。"
)
```

### `backend/app/models/reimbursement.py` 加字段

```python
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

## 算法变更

### `cycle_engine.py` 关键语义变更

判定从 `>=` 改为 `>`。旧 `cutoff=21` 时 `day >= 21` 属下月；新 `cycle_end_day=20` 时 `day > 20` 属下月（即 20 号是本月最后一天）。

```python
import calendar
from datetime import date
from dateutil.relativedelta import relativedelta


def _actual_end_day(year: int, month: int, cycle_end_day: int) -> int:
    """该月实际 cycle_end_day（超过月末日时取月末日）"""
    last_day = calendar.monthrange(year, month)[1]
    return min(cycle_end_day, last_day)


def billing_cycle(cycle_key: str, cycle_end_day: int = 20) -> tuple[date, date]:
    """cycle_key(结束月YYYY-MM) → (周期起, 周期末)

    cycle_end_day 是本周期最后一天（含）。
    例：
      billing_cycle("2026-09", cycle_end_day=25) → (date(2026,8,26), date(2026,9,25))
      billing_cycle("2026-09", cycle_end_day=20) → (date(2026,7,21), date(2026,8,20))  # 默认 20
    """
    y, m = map(int, cycle_key.split("-"))
    end_actual = _actual_end_day(y, m, cycle_end_day)
    end = date(y, m, end_actual)
    start = end + relativedelta(days=1) - relativedelta(months=1)
    return (start, end)


def cycle_key_of(d: date, cycle_end_day: int = 20) -> str:
    """费用发生日 → 所属周期 cycle_key（结束月YYYY-MM）

    规则：d.day > actual_end_day → 属下月周期；d.day <= actual_end_day → 属当月周期

    例：
      cycle_key_of(date(2026,9,25), cycle_end_day=25) → "2026-09"（25 <= 25，属当月）
      cycle_key_of(date(2026,9,26), cycle_end_day=25) → "2026-10"（26 > 25，属下月）
      cycle_key_of(date(2026,9,20), cycle_end_day=20) → "2026-09"（20 <= 20，属当月）
      cycle_key_of(date(2026,9,21), cycle_end_day=20) → "2026-10"（21 > 20，属下月）
    """
    actual = _actual_end_day(d.year, d.month, cycle_end_day)
    if d.day > actual:
        return (d + relativedelta(months=1)).strftime("%Y-%m")
    return d.strftime("%Y-%m")


def current_cycle_key(today: date | None = None, cycle_end_day: int = 20) -> str:
    today = today or date.today()
    return cycle_key_of(today, cycle_end_day)


def just_ended_cycle_key(on_date: date | None = None, cycle_end_day: int = 20) -> str:
    """封账任务用：cycle_end_day 当天执行，刚结束的周期 = 本月 cycle_key

    cycle_end_day=25 时 9月25日执行 → 锁定 "2026-09"（8/26–9/25）
    """
    on_date = on_date or date.today()
    return on_date.strftime("%Y-%m")


def cycle_display(cycle_key: str, cycle_end_day: int = 20) -> str:
    """cycle_key → 显示名，如「2026年8月26日–9月25日」"""
    start, end = billing_cycle(cycle_key, cycle_end_day)
    if start.year == end.year:
        return f"{start.year}年{start.month}月{start.day}日–{end.month}月{end.day}日"
    return f"{start.year}年{start.month}月{start.day}日–{end.year}年{end.month}月{end.day}日"
```

### `cutoff_service.py` → `cycle_end_service.py`

文件重命名 + 函数重命名：

```python
"""cycle_end_day 配置的进程级缓存层

避免每次 cycle_engine 调用都查 system_settings 表。
管理员改完 cycle_end_day 后调 invalidate_cache() 让下次读时重新加载，
同时触发 scheduler.reschedule_job 动态更新 cron trigger。
"""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.settings import SystemSettings

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
        import logging
        logging.getLogger(__name__).error(
            f"Failed to reschedule cycle_lock_job: {e}. "
            f"Manual backend restart may be needed."
        )
```

### `scheduler_service.py` 加 reschedule 函数

```python
def reschedule_cycle_lock_job():
    """管理员改 cycle_end_day 后调，重新注册 cron trigger

    从 DB 同步读最新 cycle_end_day，reschedule_job 更新 cron。
    """
    global _scheduler
    if not _scheduler or not _scheduler.running:
        return  # scheduler 未启动（首次加载时），跳过

    # 同步读 DB 拿 cycle_end_day
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

`start_scheduler` 里 `add_job` 的 `day=21` 改为从 DB 读 cycle_end_day（默认 20）：

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
    # ... 其他 add_job
    _scheduler.start()
    return _scheduler
```

## 需求 2：封账后禁止 4 类操作

### `reimbursement_service.py` 加 `assert_not_locked` helper

```python
async def assert_not_locked(reimbursement: Reimbursement) -> None:
    """校验报销单未封账，否则抛 409"""
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

### 6 个 service 函数加调用

| 函数 | 加在哪 | 报错含义 |
|---|---|---|
| `submit_reimbursement` | `assert_draft` 之后 | 已封账不能再提交 |
| `withdraw_reimbursement` | 状态校验之前 | 已封账不能再撤回（核心漏洞修复） |
| `update_reimbursement`（service 层） | `assert_draft` 之后 | 已封账不能再编辑 |
| `delete_reimbursement` | `assert_draft` 之后 | 已封账不能再删除 |
| `link_invoices` / `unlink_invoice` | `assert_draft` 之后 | 已封账不能再加/减发票 |
| `toggle_day_subsidy` | `assert_draft` 之后 | 已封账不能再改补贴 |

router 层（`portal.py`）无需改，service 抛 409 会被 FastAPI 默认异常处理返回。

### dialog `action_executor.py` 对话路径

员工通过聊天触发修改操作也走 service 层，会自动抛 409。但 handler 需要捕获 409 给用户友好提示。统一在 handler 入口包装：

```python
async def _handle_submit_reimbursement(self, ctx, db, _):
    try:
        # ... 现有逻辑
        reimb.status = ReimbursementStatus.submitted
        await db.commit()
    except HTTPException as e:
        if e.status_code == 409:
            return {"text": f"❌ {e.detail}", "data": {}}
        raise
```

同样模式应用到 `_handle_modify_field`、`_handle_delete_invoice`、`_handle_mark_travel_day` 等 handler。

**特别注意 `_handle_modify_field`**：改的是 invoice 字段（金额/日期/销售方），不直接调 reimbursement service。但若 invoice 属于已封账报销单，应禁止。在 handler 入口加（这段是 handler 内部代码片段，非完整函数）：

```python
# 在 _handle_modify_field 函数体内，找到目标 invoice 之后，修改字段之前
if invoice.reimbursement_id:
    reimb = await db.get(Reimbursement, invoice.reimbursement_id)
    if reimb and reimb.is_cycle_locked:
        return {"text": f"❌ 发票所属报销单 #{reimb.id} 已封账，无法修改。", "data": {}}
```

### 前端展示

- 员工 Portal 详情页（`MyReimbursements.tsx` 详情视图）：`is_cycle_locked=True` 时禁用所有操作按钮（提交、撤回、编辑、加发票、删发票、删报销单、切补贴）
- 禁用按钮文案 tooltip：「周期已封账，无法操作」

## 需求 3：管理员手动 unlock + 重新封账

### 新增 2 个管理员端点

`backend/app/routers/reimbursements.py`：

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
    """管理员手动解锁报销单（让员工能修改）"""
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
    """管理员手动重新封账"""
    reimbursement = await svc.get_reimbursement_or_404(db, reimbursement_id)
    if reimbursement.is_cycle_locked:
        raise HTTPException(status_code=400, detail="该报销单已封账")
    reimbursement.is_cycle_locked = True
    reimbursement.locked_at = datetime.now(timezone.utc)
    # 清空 unlock 审计字段（重新封账后旧解锁记录不再有意义）
    reimbursement.unlocked_by = None
    reimbursement.unlocked_at = None
    reimbursement.unlock_reason = None
    await db.commit()
    await db.refresh(reimbursement)
    return reimbursement
```

### 设计要点

1. **unlock 后状态不变**：报销单若为 SUBMITTED，unlock 后仍 SUBMITTED。员工需自己 `withdraw`（撤回到 DRAFT），此时 `assert_not_locked` 不再阻拦。改完再 `submit` 提交。
2. **重新封账清空审计字段**：保持审计字段语义干净 —— 只反映「当前未封账是怎么来的」。未来想要历史可加 `unlock_history` JSON 列，当前 YAGNI。
3. **解锁不依赖审批流程**：管理员可反复 unlock/lock，无「申请-审批」环节。

### 前端管理端报销单详情页

`frontend/src/pages/Reimbursements/ReimbursementDetail.tsx`：

- 加「解锁」按钮（仅当 `is_cycle_locked=True` 时显示，红色），点击 → 弹窗输入原因（1-500 字）→ 调 `POST /api/reimbursements/{id}/unlock`
- 加「重新封账」按钮（仅当 `is_cycle_locked=False` 且 `unlocked_at` 不为空时显示，绿色），点击 → 调 `POST /api/reimbursements/{id}/lock`
- 详情页显示 unlock 审计信息（若 `unlocked_at` 不为空）：
  ```
  🔓 已解锁 by {unlocked_by} on {unlocked_at}
  原因：{unlock_reason}
  ```

## 前端改动（需求 1 周期范围展示）

### 1. 管理员 Settings CycleTab

`frontend/src/pages/Settings.tsx` CycleTab：
- 输入框下加显示行：`当前周期：${current_cycle_start} ~ ${current_cycle_end}`
- API 响应字段：`cycle_end_day` + `current_cycle_start` + `current_cycle_end`（去掉 `next_effective_cycle`）

### 2. 员工 Portal 报销单列表

`frontend/src/pages/portal/MyReimbursements.tsx`：
- 列表加「周期范围」列：`${cycle_start} ~ ${cycle_end}`

### 3. 员工 Portal 报销单详情

详情视图顶部加一行：`周期范围：${cycle_start} ~ ${cycle_end}`

### 4. Boss 端智能问数查询结果

`backend/app/dialog/insight_engine.py`：`insight_*` 工具返回结果里加 `cycle_start` / `cycle_end`
`frontend/src/pages/boss/Chat.tsx`：渲染结果时显示周期范围

### `frontend/src/api/client.ts` 改动

`settingsApi.cycle.get/update` 返回类型改为：
```ts
{
  cycle_end_day: number;
  current_cycle_start: string;
  current_cycle_end: string;
}
```

## 错误处理

### 需求 1

1. **cycle_end_day 越界（< 1 或 > 31）**：pydantic `Field(ge=1, le=31)` → 422
2. **cycle_end_day 不存在（2/30、2/31）**：`_actual_end_day` 用 `calendar.monthrange` 自动截断到月末日
3. **重命名后旧代码引用 `cycle_cutoff_day`**：测试时跑全套新功能测试，旧引用运行时报 `AttributeError`，需全部改名
4. **reschedule_job 失败**：`invalidate_cache` try/except 吞异常，scheduler 保留旧 cron（保守降级），日志 ERROR

### 需求 2

5. **封账后员工 submit/withdraw/update/delete/link/unlink**：`assert_not_locked` 抛 409，router 透传，前端按钮禁用 + API 兜底
6. **dialog handler 收到 409**：handler 入口 try/except 捕获，返回 `{"text": "❌ ...", "data": {}}`
7. **封账后员工 emp_modify_field 改发票**：handler 入口查 invoice.reimbursement → 若 is_cycle_locked 拒绝

### 需求 3

8. **unlock 时 reason 为空**：pydantic `min_length=1` → 422
9. **unlock 不存在的报销单**：`get_reimbursement_or_404` 抛 404
10. **unlock 已 unlock 的报销单**：`if not is_cycle_locked: raise 400`
11. **员工 token 调 unlock**：`Depends(get_current_admin)` 鉴权层返回 403
12. **unlock 后员工改完未提交，管理员重新封账**：lock 端点不检查状态，直接设 `is_cycle_locked=True`，员工若再撤回会被挡（设计意图）

## 测试策略

### 后端测试

**新增 `backend/tests/test_cycle_engine_end_day.py`**（重命名原 `test_cycle_engine_cutoff.py`）：
- `test_billing_cycle_default_20`：默认 20 → 21-20 制（21 号属下月）
- `test_billing_cycle_end_day_25`：cycle_end_day=25 → 8/26 ~ 9/25
- `test_billing_cycle_end_day_1_natural_month`：cycle_end_day=1 → 上月 2 日到本月 1 日
- `test_billing_cycle_end_day_31_in_february`：2 月无 31 日 → 实际取 2/28
- `test_cycle_key_of_boundary_20`：day=20 属当月，day=21 属下月
- `test_cycle_key_of_boundary_25`：day=25 属当月，day=26 属下月
- `test_current_cycle_key`、`test_just_ended_cycle_key`

**新增 `backend/tests/test_cycle_end_service.py`**（重命名原 `test_cutoff_service.py`）：
- 4 个用例：默认值 20 fallback / 读 DB / 缓存命中 / invalidate_cache 后重新读 + reschedule_job 被调用

**新增 `backend/tests/test_locked_reimbursement.py`**（需求 2）：
- 12 个用例（6 service 函数 × 2 状态）：locked 时调 → 409，not locked 时调 → 正常
- 1 个对话路径用例：员工 `_handle_modify_field` 改属于已封账报销单的发票字段 → 409 友好提示
- 1 个 dialog `_handle_submit_reimbursement` 已封账 → 409 友好提示

**新增 `backend/tests/test_admin_unlock_reimbursement.py`**（需求 3）：
- `test_admin_unlock_locked_reimbursement` — unlock 封账报销单 → 200，审计字段填上
- `test_admin_unlock_already_unlocked` — unlock 未封账报销单 → 400
- `test_admin_lock_unlocked_reimbursement` — 重新封账 → 200，审计字段清空
- `test_admin_lock_already_locked` — lock 已封账报销单 → 400
- `test_unlock_requires_reason` — 不传 reason → 422
- `test_unlock_reason_too_long` — reason > 500 字 → 422
- `test_employee_cannot_unlock` — 员工 token 调 unlock → 403

**新增 `backend/tests/test_locked_then_unlock_flow.py`**（端到端）：
- 1 个完整流程：员工生成 → 模拟封账 → 员工撤回 409 → 管理员 unlock → 员工撤回 200 → 改 → 提交 → 管理员重新封账 200

**改造 `backend/tests/test_settings_cycle.py`**：
- 字段名 `cycle_cutoff_day` → `cycle_end_day`
- 测试响应里 `current_cycle_start` / `current_cycle_end` 字段
- 删除 `next_effective_cycle` 相关断言

**改造 `backend/tests/test_aggregate_reports.py`**：任何引用 `cutoff_day` 改为 `cycle_end_day`

**改造 `backend/tests/test_integration.py::TestCycleChangeTakesEffectNextPeriod`**：
- 字段名改 `cycle_end_day`
- 测试 `cycle_end_day=25` 时 9/25 属本月周期

**新增 `backend/tests/test_migration_0016_rename.py`**：
- 测试 alembic 0016 跑完后：列名 `cycle_end_day`、约束名 `ck_cycle_end_day_range`、默认值 20
- 现有 reimbursements 的 `cycle_start` / `cycle_end` 按新语义重算

### 前端测试

**改造 `frontend/e2e/p0/portal-generate-reimbursement.spec.ts`**：
- 周期显示文案从「下次生效周期」改为「当前周期：YYYY-MM-DD ~ YYYY-MM-DD」

**新增 `frontend/e2e/p0/admin-unlock-reimbursement.spec.ts`**：
- 管理员登录 → 选一份封账报销单 → 点「解锁」按钮 → 弹窗填原因 → 提交 → 详情页显示审计信息

### 现有测试

- `test_cycle_engine_cutoff.py` → 重命名为 `test_cycle_engine_end_day.py`，改测试预期（`>=` → `>`）
- `test_cutoff_service.py` → 重命名为 `test_cycle_end_service.py`
- 89 个历史失败测试不在本范围

### 测试运行

```bash
# 后端
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_cycle_engine_end_day.py tests/test_cycle_end_service.py tests/test_locked_reimbursement.py tests/test_admin_unlock_reimbursement.py tests/test_locked_then_unlock_flow.py tests/test_settings_cycle.py tests/test_migration_0016_rename.py -v"

# 前端 E2E
cd frontend && npx playwright test e2e/p0/admin-unlock-reimbursement.spec.ts
```

## 不做的事（边界）

- 不改 boss 端权限（仍只读，但能看到周期范围）
- 不重写 `aggregation_service` 业务逻辑
- 不加 unlock 申请-审批流程（管理员直接 unlock 即可）
- 不加 `unlock_history` JSON 列（YAGNI）
- 不修复 89 个历史失败测试
- 不改 alembic 0015 之前的迁移

## 上线步骤

1. `git pull origin develop/v2`
2. `docker compose build backend mcp-sse`
3. `docker compose up -d`（后端启动时自动跑 alembic 0016 + 0017 迁移）
4. 前端 `npm run build` + 部署 dist
5. 管理员可在 Settings CycleTab 改 cycle_end_day（默认 20 = 21-20 制）
6. 员工可在 Portal 看到周期范围；封账后无法修改
7. 管理员可在管理端报销单详情页 unlock 封账报销单让员工修改
8. **数据迁移注意**：alembic 0016 会重算现有 reimbursements.cycle_start/cycle_end，执行前建议 dump 数据库备份
