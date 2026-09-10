# 周期可配置 + 员工自生成报销单 设计

**日期**：2026-09-10
**分支**：develop/v2
**当前 HEAD**：290ca13

## 背景与目标

客户提出两条修改要求：

1. **周期不固定**：当前报销周期硬编码为「21–20 制」（每月 21 日到次月 20 日），需要让管理员能自行设定周期。
2. **员工能自生成/提交报销单**：当前员工被显式拦截，只能等管理员或每月定时任务归集。客户希望员工能自己生成报销单。

## 当前现状（基于代码核查）

### 周期相关

- `backend/app/services/cycle_engine.py` 硬编码 21–20 制：`if d.day >= 21 → 属下月周期`
- 每月 21 日 00:00 定时任务（`scheduler_service._cycle_lock_job`）跑归集 + 封账 + 报表
- `system_settings` 表无 `cycle_cutoff_day` 字段
- 周期标识 `cycle_key`（YYYY-MM 格式）已存在 `reimbursements` 表，配合 `uq_reimb_applicant_cycle` 唯一约束

### 员工权限相关

- `backend/app/dialog/role_gate.py:25` 有 `EMPLOYEE_BLOCKED_INTENTS = {"emp_submit_reimbursement": "报销单由系统按报销周期自动生成与归集…"}`
- `backend/app/dialog/tools.py:91` `SubmitReimbursementTool.required_roles = [UserRole.ADMIN]`
- 权限矩阵 `_PERMISSION_MATRIX` 里 `emp_submit_` 员工本来是 True，被 `EMPLOYEE_BLOCKED_INTENTS` 二次拦截
- `backend/app/routers/portal.py` 无 `POST /reimbursements` 端点，员工无法创建报销单
- `_handle_submit_reimbursement` 逻辑已有「聚合已上传发票 + 创建报销单 + 提交」，但被权限拦截

## 需求边界（确认）

### 周期可配置

- **范围**：1–31 整数，cutoff 日不存在时取该月最后一日
- **粒度**：全公司统一一个 cutoff 日（不按部门区分）
- **生效**：从下个完整周期生效；当前周期按旧 cutoff 算完，不动
- **历史**：不记录变更历史，只配当前生效值
- **已存在数据**：迁移时默认 cutoff=21（与现状一致），现有报销单 `cycle_key` 不重算

### 员工自生成报销单

- **范围**：员工仅为自己生成（不能为他人生成）
- **触发**：① Portal 页面按钮 ② 聊天对话触发
- **生成内容**：自动带当前周期该员工所有游离发票
- **数量**：一员工一周期一份报销单（保留 `uq_reimb_applicant_cycle` 唯一约束）
- **状态**：生成后 DRAFT，可继续加减发票、可提交、可删除
- **管理员能力**：保留不变（仍可调 `/aggregate` 代员工归集）
- **定时任务**：保留每月 cutoff 日 0:00 自动归集，作未自生成员工的兜底

## 架构总览

### 改动范围

**周期可配置**：

- `backend/app/services/cycle_engine.py`（核心算法）
- `backend/app/models/settings.py`（加字段）
- `backend/app/services/cutoff_service.py`（新增，缓存层）
- `backend/app/routers/settings.py`（管理端配置接口）
- `backend/alembic/versions/0015_cycle_cutoff_day.py`（新增迁移）
- `frontend/src/pages/Settings.tsx`（配置 UI）

**员工自生成报销单**：

- `backend/app/routers/portal.py`（新端点）
- `backend/app/dialog/role_gate.py`（解禁）
- `backend/app/dialog/tools.py`（改 required_roles）
- `backend/app/dialog/action_executor.py`（handler 角色分支）
- `frontend/src/pages/portal/MyReimbursements.tsx`（加按钮）
- `frontend/src/api/client.ts`（加 API 方法）

### 核心设计原则

复用现有 `aggregation_service.get_or_create_reimbursement` + `attach_invoice_to_cycle`，不重写业务逻辑。

### 生效语义

- cutoff 改动 → 下个完整周期生效，当前周期内不动
- 员工生成 → 幂等（`uq_reimb_applicant_cycle` 唯一约束保证）
- 员工生成后 → 状态 DRAFT，可继续加减发票、可提交、可删除
- 定时任务 → 保留兜底，cutoff 日 0:00 自动归集未自生成员工的游离发票

## 数据模型

### alembic 迁移 `0015_cycle_cutoff_day`

```sql
ALTER TABLE system_settings
  ADD COLUMN IF NOT EXISTS cycle_cutoff_day INT NOT NULL DEFAULT 21
  CHECK (cycle_cutoff_day BETWEEN 1 AND 31);
```

### `backend/app/models/settings.py` 改动

```python
cycle_cutoff_day: Mapped[int] = mapped_column(
    Integer, default=21,
    comment="周期 cutoff 日（1-31）。cutoff 日不存在时取该月最后一日。周期=上月cutoff日到本月(cutoff-1)日，cutoff=21 → 21–20制"
)
```

### `backend/app/services/cycle_engine.py` 改动

现有 4 个函数加 `cutoff_day: int = 21` 可选参数：

```python
import calendar

def billing_cycle(cycle_key: str, cutoff_day: int = 21) -> tuple[date, date]:
    """cutoff_day=21 → 上月21日到本月20日

    cutoff 日不存在时取该月最后一日：
    - cutoff_day=31 在2月 → 上月最后一天到2月28/29日
    - cutoff_day=30 在2月 → 上月30日到2月28/29日
    """
    y, m = map(int, cycle_key.split("-"))
    # 本月 (cutoff-1) 日；cutoff=1 → 上月最后一天
    if cutoff_day == 1:
        end = date(y, m, 1) - relativedelta(days=1)
    else:
        end = date(y, m, cutoff_day - 1)
    # 上月 cutoff 日，cutoff 超过月末日时取月末日
    prev_y, prev_m = (y, m - 1) if m > 1 else (y - 1, 12)
    prev_month_last_day = calendar.monthrange(prev_y, prev_m)[1]
    actual_cutoff = min(cutoff_day, prev_month_last_day)
    start = date(prev_y, prev_m, actual_cutoff)
    return (start, end)


def cycle_key_of(d: date, cutoff_day: int = 21) -> str:
    """费用发生日 → 所属周期 cycle_key（结束月YYYY-MM）

    cutoff=1（自然月）：1日到月末，按当月算
    cutoff=21（21–20制）：day>=21属下月，day<21属当月
    cutoff=31：每月最后一天到下月倒数第二天
    """
    actual_cutoff = min(cutoff_day, calendar.monthrange(d.year, d.month)[1])
    if d.day >= actual_cutoff:
        return (d + relativedelta(months=1)).strftime("%Y-%m")
    return d.strftime("%Y-%m")


def current_cycle_key(today: date | None = None, cutoff_day: int = 21) -> str:
    today = today or date.today()
    # 用 cycle_key_of 算当前周期
    return cycle_key_of(today, cutoff_day)


def just_ended_cycle_key(on_date: date | None = None, cutoff_day: int = 21) -> str:
    """封账任务用：cutoff 日执行时，刚结束的周期 cycle_key

    cutoff=21 时 7月21日执行 → 锁定 cycle_key="2026-07"（6/21–7/20）
    cutoff=15 时 7月15日执行 → 锁定 cycle_key="2026-07"（6/15–7/14）
    """
    on_date = on_date or date.today()
    # cutoff 日执行，刚结束的周期 = 本月 cycle_key
    return on_date.strftime("%Y-%m")
```

### 调用方改动

所有调用 `cycle_engine` 的地方改成：

```python
from app.services.cutoff_service import get_cutoff_day

cutoff = await get_cutoff_day(db)  # 走缓存
cycle_key = cycle_key_of(expense_date, cutoff)
```

主要调用点（grep 确认）：

- `services/aggregation_service.py`（归集时算 cycle_key）
  - **特别说明**：`attach_invoice_to_cycle` 内部直接调 `cycle_key_of(edate)` 和 `current_cycle_key(today)` **不传 cutoff**，是必须修改的关键点。改法：函数签名加 `cutoff_day: int | None = None`，None 时从 `get_cutoff_day(db)` 读，传给内部 `cycle_key_of` / `current_cycle_key` 调用。
- `services/expense_date_engine.py`
- `services/cycle_lock_service.py`（封账时算周期）
- `services/scheduler_service.py`（定时任务）
- `routers/reimbursements.py`、`routers/portal.py`（查询周期时算 cycle_key）

### `backend/app/services/cutoff_service.py` 进程级缓存

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.settings import SystemSettings

_cutoff_cache: int | None = None  # None = 未加载

async def get_cutoff_day(db: AsyncSession) -> int:
    global _cutoff_cache
    if _cutoff_cache is None:
        row = (await db.execute(
            select(SystemSettings).where(SystemSettings.id == 1)
        )).scalar_one_or_none()
        _cutoff_cache = row.cycle_cutoff_day if row else 21
    return _cutoff_cache

def invalidate_cache() -> None:
    global _cutoff_cache
    _cutoff_cache = None  # 下次读时重新加载
```

管理员保存 cutoff 后调 `invalidate_cache()`。

## 员工自生成报销单的后端改动

### 新增端点 `POST /api/portal/reimbursements/generate`

`backend/app/routers/portal.py`：

```python
@router.post("/reimbursements/generate", response_model=ReimbursementResponse)
async def generate_my_reimbursement(
    employee: Employee = Depends(get_current_employee_async),
    db: AsyncSession = Depends(get_db),
):
    """员工生成自己的报销单

    - 幂等：同一员工同一周期已有报销单时直接返回现有
    - 自动归集当前周期所有游离发票（通过 attach_invoice_to_cycle 自动按费用日归位）
    - 生成后状态 DRAFT，可继续加减发票、提交、删除
    """
    from app.services.cutoff_service import get_cutoff_day
    from app.services.cycle_engine import current_cycle_key
    from app.services.aggregation_service import (
        get_or_create_reimbursement,
        attach_invoice_to_cycle,
    )

    cutoff = await get_cutoff_day(db)
    ck = current_cycle_key(cutoff_day=cutoff)
    # 创建（或复用）当前周期报销单（DRAFT 状态）
    reimb = await get_or_create_reimbursement(
        db, applicant_id=employee.employee_no, cycle_key=ck,
        auto_generated=False,
    )
    # 把该员工所有游离发票跑一遍 attach_invoice_to_cycle
    # 该函数内部按发票费用日算目标周期：
    #   - 费用日在当前周期 → 归入这份报销单
    #   - 费用日在其他周期 → 归入对应周期的报销单（可能创建新单）
    #   - 目标周期已封账 → 归入当前周期并标记 late_charge
    # 因此这里不需要外部 cycle 判定，全部交给 attach_invoice_to_cycle
    free_invoices = await db.execute(
        select(Invoice).where(
            Invoice.applicant_id == employee.employee_no,
            Invoice.reimbursement_id.is_(None),
        )
    )
    for inv in free_invoices.scalars():
        await attach_invoice_to_cycle(db, inv)  # 内部自动按 cycle 归位

    await db.commit()
    await db.refresh(reimb)
    return reimb
```

### 幂等保证

- `get_or_create_reimbursement` 内部用 `SELECT ... WHERE applicant_id=? AND cycle_key=?`，已存在则返回现有
- 多次点「生成」始终返回同一份报销单
- 重复 attach 同一张发票会被 `attach_invoice_to_cycle` 内部判断跳过
- 并发请求由 `uq_reimb_applicant_cycle` 唯一约束保护，`IntegrityError` 被 `get_or_create_reimbursement` 捕获后重新 SELECT

### 鉴权

`get_current_employee_async` —— 只能是自己（基于 JWT 的 employee_no），端点签名不接受 `applicant_id` 参数，无法伪造。

### 改 `backend/app/dialog/role_gate.py`

```python
# 之前：
EMPLOYEE_BLOCKED_INTENTS = {
    "emp_submit_reimbursement": "报销单由系统按报销周期自动生成与归集，您无需手动提交。",
}

# 改为：删除 emp_submit_reimbursement 这一项
EMPLOYEE_BLOCKED_INTENTS = {}  # 或保留其他需要拦截的意图
```

权限矩阵 `_PERMISSION_MATRIX`（`role_gate.py:42`）里 `emp_submit_` 已经是 `{EMPLOYEE: True, ADMIN: True, BOSS: False}`，删 EMPLOYEE_BLOCKED_INTENTS 这一项后员工即可调。

### 改 `backend/app/dialog/tools.py`

```python
class SubmitReimbursementTool(_BridgeTool):
    name = "emp_submit_reimbursement"
    description = "提交报销单"
    Parameters = SubmitReimbursementParams
    required_roles = [UserRole.EMPLOYEE, UserRole.ADMIN]  # 之前是 [UserRole.ADMIN]
    handler_method = "_handle_submit_reimbursement"
```

### 改 `backend/app/dialog/action_executor.py`

`_handle_submit_reimbursement` 按角色分支：

```python
async def _handle_submit_reimbursement(
    self, ctx: DialogContext, db: AsyncSession, _: Optional[dict]
) -> dict:
    """提交报销单 — 聚合已上传发票 + 创建报销单 + 提交

    员工：为自己生成（applicant_id = ctx.user_id）
    管理员：为指定员工生成（用 ctx.slots 提取的 user_id）
    """
    # 角色判定（DialogContext.role 字段是 UserRole enum）
    if ctx.role == UserRole.EMPLOYEE:
        target_user_id = ctx.user_id
    else:  # ADMIN
        slot = ctx.slots.get("user_id")
        target_user_id = (slot.value if slot and slot.filled else None) or ctx.user_id
    # 复用 portal 端同样逻辑：get_or_create + attach + submit
    ...
```

## 前端改动

### 员工端 Portal — `frontend/src/pages/portal/MyReimbursements.tsx`

在「我的报销单」列表页顶部加 **「生成我的报销单」** 按钮：

```tsx
<div className="flex items-center justify-between mb-4">
  <h1 className="text-xl font-semibold">我的报销单</h1>
  <button
    onClick={handleGenerate}
    disabled={generating}
    className="bg-primary-600 text-white px-4 py-2 rounded-md hover:bg-primary-700 disabled:opacity-50"
  >
    {generating ? '生成中...' : '生成我的报销单'}
  </button>
</div>

async function handleGenerate() {
  setGenerating(true)
  try {
    const res = await reimbursementApi.generate()  // POST /portal/reimbursements/generate
    navigate(`/portal/reimbursements/${res.id}`)   // 跳详情页
  } catch (e) {
    toast.error(e.response?.data?.detail || '生成失败')
  } finally {
    setGenerating(false)
  }
}
```

按钮 tooltip：「按当前周期生成报销单，自动带本周期所有未关联发票。已有报销单会返回原单。」

### 管理端 `frontend/src/pages/Settings.tsx`

系统设置页加 `周期 cutoff 日` 输入框（紧挨其他系统配置下方）：

```tsx
<div className="mb-4">
  <label className="block text-sm font-medium mb-1">周期 cutoff 日</label>
  <input
    type="number" min={1} max={31}
    value={settings.cycle_cutoff_day}
    onChange={e => setSettings({...settings, cycle_cutoff_day: Number(e.target.value)})}
    className="w-24 border rounded-md px-2 py-1"
  />
  <p className="text-xs text-gray-500 mt-1">
    cutoff 日不存在时取该月最后一日。例：21 = 每月21日到次月20日。修改后下个完整周期生效。
  </p>
</div>
```

保存按钮已有的保存逻辑加一行 `cycle_cutoff_day: settings.cycle_cutoff_day`，后端 `PUT /api/settings` 接收后调 `cutoff_service.invalidate_cache()`。

### `frontend/src/api/client.ts`

```ts
reimbursementApi: {
  // 已有方法...

  generate: () => portalRequest<{ id: number; cycle_key: string; status: string; /* ... */ }>(
    "/reimbursements/generate",
    { method: "POST" }
  ),
}
```

### 不做的改动（边界）

- 不改 boss 端（仍只能查看）
- 不改 `dialog/ChatWidget` 组件的对话触发逻辑 —— 它本来就走 `emp_submit_reimbursement` 意图，后端解禁后对话自动能用
- 不改 Portal 详情页的「提交」按钮 —— 已有，员工生成 DRAFT 后点「提交」走 `/submit`

## 错误处理

### 周期可配置

1. **管理员保存 cutoff 越界（< 1 或 > 31，或非整数）**
   - 后端 `PUT /api/settings` 用 pydantic 校验：`cycle_cutoff_day: int = Field(ge=1, le=31)`
   - 不通过 → 422 返回前端
   - 前端 `min={1} max={31}` 预拦截

2. **管理员保存 cutoff 在当前周期已过半时**
   - 后端正常保存，不报错（按设计「下个周期生效」）
   - 响应附带 `next_effective_cycle` 字段提示「下次生效周期 = 2026-08（cutoff=15）」
   - 前端 toast：「保存成功，下个完整周期（YYYY-MM）生效」

3. **cutoff 日不存在（2 月无 30/31 日）**
   - `cycle_engine.billing_cycle` 用 `calendar.monthrange` 取月末日，`cutoff = min(cutoff_day, 月末日)`
   - 不报错，按「cutoff 取该月最后一天」规则计算
   - 日志 INFO：`billing_cycle: cutoff_day=31 capped to 28 in 2026-02`

4. **cutoff 切换后定时任务跑错周期**
   - `scheduler_service._cycle_lock_job` 启动时调 `get_cutoff_day(db)` 读最新配置
   - 用 `just_ended_cycle_key(cutoff_day=cutoff)` 算刚结束的周期
   - 不依赖硬编码的 21 日判定

### 员工自生成报销单

5. **员工当前周期已生成过报销单**
   - `get_or_create_reimbursement` 幂等：SELECT 现有 → 直接返回
   - 不报错，不创建新单
   - 前端 toast：「该周期报销单已存在，已为您打开」
   - 跳详情页

6. **员工当前周期无游离发票**
   - 正常创建空报销单（DRAFT 状态）
   - 不报错（员工可先创建再补传发票）
   - 响应里 `expense_total: 0`、`items: []`，前端详情页显示「该报销单暂无发票，点击上传」

7. **员工 attach 发票时费用日不在当前周期**
   - `attach_invoice_to_cycle` 内部判断发票 cycle_key ≠ 当前周期 → 跳过 attach
   - 该发票保持游离状态
   - 日志 INFO：`skipping invoice #N (cycle=2026-06) for current reimbursement (cycle=2026-07)`
   - 不报错给员工（避免暴露内部 cycle 判定细节）

8. **员工重复点「生成」并发请求**
   - `uq_reimb_applicant_cycle` 唯一约束保护：第二个 INSERT 被 DB 拒绝 → 抛 `IntegrityError`
   - `get_or_create_reimbursement` 捕获后重新 SELECT 返回现有
   - 前端按钮点击后立即 `disabled`，避免重复请求

9. **员工生成的报销单已被自动归集任务影响**
   - cutoff 日 0:00 定时归集跑时，员工已有报销单 → `aggregate_pending_invoices` 按现有单 attach
   - 不创建新单，不冲突
   - 日志 INFO：`employee X already has reimbursement for cycle Y, attaching 2 invoices`

10. **员工尝试为别人生成（伪造 applicant_id）**
    - 端点签名只用 `employee.employee_no`（从 JWT 解出），不接受请求体里的 `applicant_id`
    - 无法伪造
    - 即使绕过前端调 API，后端鉴权层 `get_current_employee_async` 只认 JWT

## 测试策略

### 后端测试

**新增 `backend/tests/test_cycle_engine_cutoff.py`**：

- `test_billing_cycle_default_21`：cutoff=21 时跟现状一致（21–20 制）
- `test_billing_cycle_natural_month`：cutoff=1 时 = 自然月（1–月末）
- `test_billing_cycle_cutoff_31_in_february`：cutoff=31 在 2 月 → 上月最后一天到 2/28 或 2/29（闰年）
- `test_billing_cycle_cutoff_30_in_february`：cutoff=30 在 2 月 → 上月 30 日到 2 月末日
- `test_cycle_key_of_boundary`：cutoff=21 时 day=20 属当月周期，day=21 属下月周期
- `test_cycle_key_of_cutoff_1`：cutoff=1 时 day=1 属当月周期，上月末日属上月周期
- `test_current_cycle_key_with_cutoff`：cutoff=15 时 5/14 属 2026-04 周期，5/15 属 2026-05 周期
- `test_just_ended_cycle_key`：cutoff=21 时 21 日执行 → 锁定本月周期

**新增 `backend/tests/test_portal_generate_reimbursement.py`**：

- `test_employee_generate_first_time`：员工首次生成 → 200，新报销单 DRAFT，含当前周期所有游离发票
- `test_employee_generate_idempotent`：第二次生成 → 返回同一份（id 相同）
- `test_employee_generate_no_free_invoices`：无游离发票 → 返回空报销单（DRAFT）
- `test_employee_generate_attaches_only_current_cycle_invoices`：跨周期游离发票 → 只带当前周期的
- `test_employee_generate_applicant_id_is_self`：返回的 applicant_id 必须等于自己 employee_no
- `test_unauthenticated_401`：未带 token → 401
- `test_employee_cannot_generate_for_others`：端点不接受 applicant_id 参数，伪造无效
- `test_concurrent_generate_returns_same`：模拟并发 → 都拿到同一份（幂等）

**改 `backend/tests/test_admin_aggregate.py`**：

- `test_admin_aggregate_still_works`：员工能自生成后，管理员 `/api/reimbursements/aggregate` 仍能归集未自生成员工的发票
- `test_admin_aggregate_skips_employees_with_existing_reimbursement`：员工已自生成 → 不创建新单，只补 attach

**改 `backend/tests/test_role_gate.py`**（如存在）：

- `test_employee_can_submit_reimbursement`：员工调用 `emp_submit_reimbursement` 通过（之前被拦截）

### 前端测试

**`frontend/e2e/portal-generate-reimbursement.spec.ts`**（Playwright E2E）：

- 员工登录 → 上传 2 张发票 → 点「生成我的报销单」 → 跳详情页 → 看到这 2 张发票
- 同一员工二次点「生成」 → 跳同一报销单（不新建）
- 管理员设置页改 cutoff 为 15 → 保存 → toast 显示「下次完整周期生效」

### 集成测试

**`backend/tests/test_integration.py` 加用例**：

- `test_cycle_change_takes_effect_next_period`：
  - cutoff=21，员工 5/22 上传一张发票（cycle=2026-06）
  - 管理员改 cutoff=15
  - 员工 5/22 上传的发票 cycle_key 仍是 2026-06（旧规则）—— 已有数据不动
  - 员工 5/16 上传新发票 → 用新规则算成 cycle=2026-06（5/16 ≥ 15 属下月周期）
  - 验证旧数据 + 新规则的边界

### 现有 89 个失败测试

不在本设计范围处理。本次新增功能相关的测试用例要全绿；89 个失败用例是历史遗留，单独处理。

### 测试运行命令

```bash
# 后端
docker compose exec -T backend bash -c "cd /app && python -m pytest tests/test_cycle_engine_cutoff.py tests/test_portal_generate_reimbursement.py -v"

# 前端 E2E
cd frontend && npx playwright test e2e/portal-generate-reimbursement.spec.ts
```

## 不做的事（明确边界）

- 不改 boss 端权限（仍只读）
- 不重写 `aggregation_service` 业务逻辑（只调参数）
- 不重算现有报销单的 `cycle_key`（避免破坏 `uq_reimb_applicant_cycle`）
- 不记录 cutoff 变更历史（按需求只配当前生效值）
- 不改 alembic 0011/0012 等已有迁移（仅新增 0015）
- 不在本次修复 89 个历史失败测试用例

## 上线步骤

1. 部署 alembic 迁移 0015_cycle_cutoff_day（启动时自动跑）
2. 后端重启加载新代码（cycle_engine + cutoff_service + portal 新端点 + role_gate 解禁）
3. 前端构建部署（Settings 加 cutoff 输入框 + MyReimbursements 加生成按钮）
4. 管理员可在设置页改 cutoff（默认 21，跟现状一致）
5. 员工立即可在 Portal 点「生成我的报销单」
6. 现有 2 份报销单 + 5 张发票数据不变（cutoff 默认 21 跟现状一致）
