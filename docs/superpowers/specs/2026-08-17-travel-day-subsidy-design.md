# 报销单补贴计算规则调整 — 员工自主上报出差日

> 日期：2026-08-17
> 状态：已与用户确认 7 段设计 + 迁移策略 A
> 实施前等待用户审阅

## Context

现有补贴逻辑：发票有费用发生的天 → 自动计补贴（节假日 80 / 工作日 60）。员工不主动上报。

新规则：员工在「智能问数」对话框输入框左侧的日历按钮自主标记出差日，报销单按"已标记的出差日"核算补贴。带发票但未标记为出差的天**不再触发**补贴。

## 核心规则变化

| 项 | 旧 | 新 |
|---|---|---|
| 触发源 | `ReimbursementItem.item_date` 去重 | `ReimbursementTravelDay.travel_date` 去重 |
| 员工操作 | 无（自动） | 在对话框标记出差日 |
| 补贴标准 | 节假日 80 / 工作日 60 | 不变 |
| 手动取消补贴 | toggle included | 保留 |
| 周期范围 | 周期内发票 | 周期内出差日 |

## 数据模型

### 新增表 `reimbursement_travel_days`

```python
class ReimbursementTravelDay(Base, TimestampMixin):
    __tablename__ = "reimbursement_travel_days"
    __table_args__ = (
        UniqueConstraint("reimbursement_id", "travel_date", name="uq_travel_day_reimb_date"),
    )

    id: Mapped[int]                      # PK
    reimbursement_id: Mapped[int]        # FK reimbursements.id CASCADE
    travel_date: Mapped[date]            # 出差日期
    note: Mapped[str | None]             # 可选备注，如"北京出差"/"返程"
    weekday: Mapped[int | None]          # 0=周一…6=周日（冗余）
    day_type: Mapped[str | None]         # workday/weekend/holiday（冗余）
    base_rate: Mapped[float | None]      # 60 或 80（冗余）
    applicant_id: Mapped[str]            # 谁标的，用于鉴权
```

### 与 `day_subsidies` 的关系

- `day_subsidies` 表结构不变
- `subsidy_engine.recompute_subsidies` 改为读 `travel_days` 而非 `items.item_date` 去重
- 不在 travel_days 里的旧 day_subsidy 行删除
- `trigger_invoice_count` 字段保留作信息字段（员工可看到当天有几张发票），不再驱动逻辑

### 约束

- `travel_date` 必须落在所属报销单 `cycle_start ~ cycle_end` 内（后端 POST 时校验）
- `(reimbursement_id, travel_date)` 唯一，防同一天重复标记
- 一个报销单可有多条 travel_days，无上限

## 后端 API 与权限

新增路由文件 `backend/app/routers/travel_days.py`，挂在 `/api/portal/travel-days` 前缀。

| 端点 | 方法 | 鉴权 | 行为 |
|---|---|---|---|
| `/api/portal/travel-days` | GET | `get_current_employee` | 返回当前员工本周期报销单的所有 travel_days |
| `/api/portal/travel-days` | POST | `get_current_employee` | 标记一个出差日。body: `{travel_date, note?}` |
| `/api/portal/travel-days/{id}` | DELETE | `get_current_employee` | 删除一条 travel_day（仅本人） |
| `/api/portal/travel-days/by-date/{date}` | DELETE | `get_current_employee` | 按日期删除（日历点取消更直观） |
| `/api/admin/travel-days` | GET | `get_current_admin_or_boss` | 管理员/超级管理员按 reimbursement_id 查询 |

### 鉴权细节

- POST/DELETE 用 `get_current_employee`：员工只能改自己的报销单——后端从 token 拿 `emp_id`，再校验报销单的 `applicant_id` 匹配
- GET 员工端：只返回当前员工的报销单的 travel_days
- GET 管理端：支持 `?reimbursement_id=xxx` 查指定报销单，可穿透

### 周期归属规则

- POST 时后端按 `travel_date` 找该员工该周期的报销单（复用现有 `aggregation_service` 周期匹配逻辑：周期键 = `YYYY-MM`，周期范围按 21 日切）
- 若该周期报销单不存在 → 自动创建草稿报销单（复用 `aggregation_service` 现有逻辑）
- 然后插入 travel_day 行 + 触发 `subsidy_engine.recompute_all`

### 副作用

所有写操作后调用 `recompute_all`，确保 `subsidy_total / total_amount` 即时刷新。

## 补贴引擎改造

### `subsidy_engine.py` 修改

**`recompute_subsidies` 改为读 travel_days**：

```python
# 旧：从 ReimbursementItem.item_date 去重得到日期集合
# 新：从 ReimbursementTravelDay.travel_date 去重得到日期集合
result = await db.execute(
    select(ReimbursementTravelDay.travel_date, ReimbursementTravelDay.note)
    .where(ReimbursementTravelDay.reimbursement_id == reimbursement.id)
)
dates_with_travel = {row.travel_date: row.note for row in result.all()}
```

- 去重日期集合来源从 items 改为 travel_days
- upsert 逻辑不变：travel_day 存在 → upsert 一行 day_subsidy；travel_day 不存在但 day_subsidy 行存在 → 删除
- `trigger_invoice_count` 仍按现有 `count_items_by_date` 计算（信息字段）

### 调用方影响

保留 `recompute_subsidies` 签名——只改内部数据源，调用方无需改动（report_generator / aggregation_service / reimbursement_service 等不变）。

### 手动取消补贴

- 现有 `toggle_day_subsidy`（员工在 MyReimbursements 详情页可点行切换 included）保留
- 员工标了出差日 → 触发补贴行；员工在详情页点"取消补贴" → included=False，subsidy_amount=0
- "先标出差日"再"是否计入补贴"两层开关，员工有最终决定权

## 前端日历组件

### 新组件 `frontend/src/components/TravelDayPicker.tsx`

月历弹层多选，结构：

```
┌─────────────────────────────┐
│  ‹  2026 年 8 月  ›         │  ← 月份切换
│  一 二 三 四 五 六 日        │
│  …  1  2  3  4  5  6        │
│  7  8  9 10 11 12 13        │  ← 周期内日期可点
│ 14 15 16 17 18 19 20        │     周期外日期灰显禁点
│ 21 22 23 24 25 26 27        │  ← 21 日起属于下个周期（自动切月）
│ 28 29 30 31 …               │
│                             │
│  ┌───────────────────────┐  │
│  │ 备注（可选）          │  │  ← 给当前批次选中的天加备注
│  └───────────────────────┘  │
│                             │
│  已选 3 天：8/15、8/16、8/17│  ← 当前批次选中的天
│                             │
│  [清空选择]      [完成]     │
└─────────────────────────────┘
```

### 关键交互

- 点对话框输入框左侧的 📅 按钮 → 弹出 picker
- 已标记为出差的日期显示为**实心蓝点**（来自后端 GET 本周期 travel_days）
- 本批次新选的日期显示为**浅蓝描边**，确认后才 POST 到后端
- 周期外的日期灰显禁点
- 备注是批量的：本次选中的所有天共用同一条备注
- 已标记的天再点一次 → 进入"取消选中"状态，"完成"时 DELETE

### 对话框集成 `ChatWidget.tsx:1133`

在"无凭证报销"按钮之后、文本输入之前插入日历按钮：

```tsx
<button onClick={() => setTravelPickerOpen(true)} title="标记出差日">
  <Calendar size={20} />
</button>
<TravelDayPicker
  open={travelPickerOpen}
  onClose={() => setTravelPickerOpen(false)}
  cycleStart={currentCycleStart}
  cycleEnd={currentCycleEnd}
  existingTravelDays={travelDays}
  onSubmit={handleTravelDaysSubmit}  // 批量增删
/>
```

### 完成后反馈

- "完成"成功后，picker 关闭，对话框内插入一条**助手消息**："已标记 8/15、8/16 为出差日。"
- 失败 → 弹错误 toast / 错误消息

### 角色限制

只在员工端显示日历按钮：
- ChatWidget 的 `useRoleAndUserId` 已识别 role
- 日历按钮 `role === "employee"` 时渲染，admin/boss 不显示
- 老板端/管理员端不需要标记出差日（只读查看）

## 报销单回显与权限边界

### 报销单详情回显

员工端 `MyReimbursements.tsx` + 管理端 `Reimbursements.tsx` + 超级管理员端 `ReimbursementDetail.tsx`：新增"出差日" section（位于"日补贴" section 之上）。

```
┌─ 出差日 (3 天) ─────────────────┐
│  日期       备注        当日发票  │
│  08-15 周五  北京出差    3 张     │
│  08-16 周六  返程        2 张     │
│  08-17 周日  —           0 张     │
└────────────────────────────────┘
```

- 出差日按日期升序排列
- "当日发票"列显示该天有多少张 ReimbursementItem（信息字段，员工可对照）
- 备注为空显示 "—"
- **员工端**：每行右侧有删除按钮（×），点 → DELETE `/api/portal/travel-days/by-date/{date}` → 刷新
- **管理端 / 超级管理员端**：纯只读，无删除按钮

### "日补贴" section 保留

- 显示 `day_subsidies` 行（旧逻辑生成，但现在每行都对应一个 travel_day）
- 表格列保持不变：日期 / 类型 / 标准 / 实际补贴 / included 切换
- 员工端可点行切换 included（保留现有 toggle 功能）

### 后端序列化改造

- `reimbursement_service.serialize_reimbursement_detail` 现已返回 `items`、`day_subsidies`、`attachments`
- **新增 `travel_days` 字段**：每个 travel_day 序列化为 `{id, travel_date, note, weekday, day_type, base_rate}`
- 影响响应：员工端 `/api/portal/reimbursements/detail` + 管理端 `/api/reimbursements/{id}` + 超级管理员端共用 `/api/reimbursements/{id}`

### 权限矩阵

| 角色 | 标记出差日 | 查看出差日 | 取消补贴（toggle included） |
|---|---|---|---|
| employee | ✅ 本人报销单 | ✅ 本人 | ✅ |
| admin | ❌ | ✅ 任意员工 | ✅ |
| boss | ❌ | ✅ 任意员工 | ❌（纯只读） |

### 关键约束

- `POST/DELETE /api/portal/travel-days*` 只接受 employee role（router 级 `Depends(get_current_employee)`）
- admin/boss 通过 `/api/reimbursements/{id}` GET 时能看到 travel_days，但不能写
- boss 不能 toggle included（管理端 `toggle_subsidy` 端点保持 `get_current_admin`，boss 403）

## 数据迁移

**策略 A：按现有 day_subsidies 回填 travel_days**

- Alembic 建表脚本 `add_reimbursement_travel_days`
- 迁移数据：`INSERT INTO reimbursement_travel_days (reimbursement_id, travel_date, note, weekday, day_type, base_rate, applicant_id) SELECT rds.reimbursement_id, rds.subsidy_date, NULL, rds.weekday, rds.day_type, rds.base_rate, r.applicant_id FROM reimbursement_day_subsidies rds JOIN reimbursements r ON r.id = rds.reimbursement_id WHERE rds.included = true`
- 已 included=false 的补贴行不回填 travel_day（员工之前已主动取消）
- 迁移后 subsidy_total 不变（travel_days 与 day_subsidies 一一对应）
- 旧数据平滑过渡，员工打开旧报销单看到 travel_days 已有数据

## 测试

### 后端单元测试 `backend/tests/test_travel_days.py`（新建）

| 用例 | 期望 |
|---|---|
| `test_mark_travel_day_creates_subsidy_row` | 标一个出差日 → day_subsidies 多一行，subsidy_total 增 |
| `test_delete_travel_day_removes_subsidy_row` | 删出差日 → day_subsidies 少一行，subsidy_total 减 |
| `test_mark_outside_cycle_rejected` | travel_date 落在周期外 → 400 |
| `test_mark_duplicate_date_rejected` | 同一天重复标记 → 409 |
| `test_employee_cannot_mark_others_reimbursement` | applicant_id 不匹配 → 403 |
| `test_subsidy_only_counts_travel_days` | 报销单有发票但无 travel_days → subsidy_total=0 |
| `test_admin_can_list_any_travel_days` | admin token GET → 200 |
| `test_boss_can_list_but_not_write` | boss POST → 403, GET → 200 |

### 后端回归

迁移后立即跑全套测试。重点：
- `test_subsidy_engine.py`：若它依赖旧逻辑（items 触发补贴），需要更新断言
- `test_cycle_engine.py`、`test_expense_date_engine.py` 等可能受影响

### 迁移脚本测试

- 单元测试覆盖迁移函数：给定若干 day_subsidies 行 → 跑迁移后生成对应 travel_days 行
- 端到端验证：迁移前后的 subsidy_total 应一致

### 前端手动验证清单

1. 员工端 `/portal/home` 对话框点日历按钮 → 弹层 → 选 8/15、8/16 + 备注"北京出差" → 完成
2. 对话框显示"已标记 8/15、8/16 为出差日"
3. `/portal/reimbursements` 进详情页 → 出差日 section 显示这两行 → 补贴合计显示 120 元（工作日）或 160 元（周末）
4. 详情页出差日行点 × 删除 → 列表刷新 → 补贴合计 -60
5. 周期外日期灰显禁点
6. 管理端 `/reimbursements` 详情页能看到员工标的出差日，无 × 按钮
7. 超级管理员端 `/boss/reimbursements/:id` 同样能看到，纯只读
8. 旧报销单（迁移前的）打开后 travel_days 已有数据，补贴合计与迁移前一致

### 端到端验证脚本 `backend/scripts/e2e_travel_days_test.py`

- 登录员工 → 标出差日 → GET 详情验证 → 删除 → 验证 subsidy_total 变化
- 9 项左右，覆盖权限边界

## 修改文件清单

### 后端

| 文件 | 改动 |
|---|---|
| `backend/app/models/reimbursement.py` | 新增 `ReimbursementTravelDay` 模型 |
| `backend/alembic/versions/xxx_add_reimbursement_travel_days.py` | 建表 + 数据迁移 |
| `backend/app/routers/travel_days.py`（新建）| 5 个端点 + 鉴权 |
| `backend/app/main.py` | 注册 travel_days router |
| `backend/app/services/subsidy_engine.py` | `recompute_subsidies` 改读 travel_days |
| `backend/app/services/reimbursement_service.py` | `serialize_reimbursement_detail` 加 travel_days 字段 |
| `backend/app/schemas/__init__.py` | 加 `TravelDayCreateRequest` / `TravelDayResponse` |
| `backend/tests/test_travel_days.py`（新建）| 8 个单元测试用例 |
| `backend/tests/test_subsidy_engine.py` | 更新旧断言（items 不再触发补贴） |
| `backend/scripts/e2e_travel_days_test.py`（新建）| E2E 验证脚本 |

### 前端

| 文件 | 改动 |
|---|---|
| `frontend/src/components/TravelDayPicker.tsx`（新建）| 月历弹层多选组件 |
| `frontend/src/components/ChatWidget.tsx` | 输入区加日历按钮 + 集成 picker（仅 employee role） |
| `frontend/src/api/client.ts` | `portalApi` 加 travelDay API（list/create/deleteByDate） |
| `frontend/src/types/index.ts` | 加 `TravelDay` 类型 |
| `frontend/src/pages/portal/MyReimbursements.tsx` | 详情页加"出差日" section（员工端带删除按钮） |
| `frontend/src/pages/Reimbursements.tsx` | 详情页加"出差日" section（管理端只读） |
| `frontend/src/pages/boss/ReimbursementDetail.tsx` | 详情页加"出差日" section（超管只读） |
