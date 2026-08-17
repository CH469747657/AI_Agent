# 老板专属登录端 — 设计文档

> 日期：2026-08-17
> 状态：已与用户确认 5 段设计
> 实施前等待用户审阅

## Context

公司需要一个「老板专属登录端」，让老板通过手机端登录、查看全公司发票与报销单明细、用智能问数方式查询数据。

探索发现：**后端 BOSS 角色、权限矩阵、意图注册、洞察引擎 100% 已就绪**——`backend/app/dialog/models.py:50-54` 已定义 `UserRole.BOSS`；`role_gate.py:42-67` 已配置 BOSS 数据范围 `read_only_all`；`intent_registry.py:526-666` 已注册 10 个 BOSS 可用洞察意图（含 3 个 BOSS 独有）；`insight_engine.py` 已实现全部洞察方法。**唯一缺口是认证层和前端入口**。

## 核心需求

1. 新增老板专属账号：用户名 `zhang` / 密码 `zhang`
2. 全公司最高数据查看权限，可穿透查看所有部门、所有员工的发票与报销单明细
3. 智能问数方式查询数据（对话式 + 表格返回）
4. 手机端登录查看（移动端优先）
5. 列表 UI（发票 + 报销单），传统列表筛选
6. 纯只读权限（不能批/删/改设置）
7. 对话返回的发票号/报销单号可点击下钻到详情页

## 架构与角色边界

### 后端

| 文件 | 改动 |
|---|---|
| `backend/app/config.py` | 新增 `boss_username` / `boss_password_hash` 字段（从 `.env` 读） |
| `backend/app/routers/admin_auth.py` | 新增 `boss_login` 端点 → `POST /api/boss/auth/login`，JWT `role=boss`；新增 `get_current_admin_or_boss` 依赖 |
| `backend/app/routers/invoices.py` | GET 端点 `Depends(get_current_admin)` → `Depends(get_current_admin_or_boss)` |
| `backend/app/routers/reimbursements.py` | GET 端点同上 |
| `backend/app/routers/reports.py` | GET 端点同上 |
| `backend/app/routers/employees.py` | GET 端点同上（BOSS 需要看员工列表，便于问数下钻） |
| `backend/app/routers/projects.py` | GET 端点同上（穿透查看项目归属） |
| `backend/app/routers/dialog.py` | `POST /api/dialog/message` 鉴权 `get_current_admin` → `get_current_admin_or_boss` |
| `backend/app/routers/holidays.py` | 不改（BOSS 无需看节假日） |
| `backend/app/routers/settings.py` | 不改（BOSS 不能改设置） |
| 写操作端点（POST/PUT/DELETE）| 保持 `Depends(get_current_admin)`，BOSS 403 |
| `backend/app/main.py` | 注册 boss_auth router 到 `/api/boss/auth` |

### 前端

```
/boss/login                              → BossLogin
/boss                                    → BossLayout（底部 Tab 容器）
  ├── /boss/chat            (默认首页)    → BossChat
  ├── /boss/invoices                     → BossInvoiceList
  ├── /boss/invoices/:id                 → BossInvoiceDetail
  ├── /boss/reimbursements               → BossReimbursementList
  └── /boss/reimbursements/:id           → BossReimbursementDetail
```

### 角色边界（纯只读）

| 端点 | BOSS 可访问 | BOSS 可写 |
|---|---|---|
| GET /api/invoices* | ✅ | — |
| GET /api/reimbursements* | ✅ | — |
| GET /api/reports/* | ✅ | — |
| GET /api/employees* | ✅ | — |
| GET /api/projects* | ✅ | — |
| POST /api/dialog/message | ✅ | — |
| POST /api/reimbursements/{id}/approve | ❌ 403 | ❌ |
| DELETE /api/invoices/{id} | ❌ 403 | ❌ |
| PUT /api/settings/* | ❌ 403 | ❌ |

## 认证与凭证

### 凭证存储

老板账号 `zhang/zhang` 仿 admin 模式存 `.env`，不进 DB：

```
# .env 新增（紧跟 ADMIN_PASSWORD_HASH 之后）
BOSS_USERNAME=zhang
BOSS_PASSWORD_HASH=$2a$12$<bcrypt("zhang")>
```

密码哈希生成方式（复用 `app.services.auth_service.hash_password`）：
```bash
python -c "from app.services.auth_service import hash_password; print(hash_password('zhang'))"
```

### 后端认证流

`POST /api/boss/auth/login`：
1. 校验 `username == settings.boss_username`
2. `verify_password(password, settings.boss_password_hash)`
3. 颁发 JWT：`sub=username` / `role="boss"` / `exp=now+24h`（复用 `settings.jwt_expire_hours`）
4. 返回 `{access_token, token_type:"bearer", profile:{username, role:"boss"}}`

`get_current_admin_or_boss` 依赖：
```python
async def get_current_admin_or_boss(token: str = Depends(OAUTH2_SCHEME)) -> dict:
    payload = decode_jwt(token)
    role = payload.get("role")
    if role not in ("admin", "boss"):
        raise HTTPException(403, "需要管理员或老板权限")
    return {"sub": payload["sub"], "role": role}
```

### 前端 token 存储

`frontend/src/api/client.ts` 新增：
- `localStorage.boss_token` — 独立 key，避免与 `admin_token` / `portal_token` 串号
- `setBossToken()` / `clearBossToken()` / `getBossToken()`
- axios 请求拦截器：BOSS 路由请求自动注入 `Authorization: Bearer <boss_token>`

### 路由守卫

`frontend/src/components/BossProtected.tsx`：
- 检查 `localStorage.boss_token`
- 无 token → 重定向 `/boss/login`
- token 失效（401）→ 清 token + 重定向 `/boss/login`

### 登出

JWT 无服务端状态，登出仅清前端 token；后端不实现端点，前端 `clearBossToken()` 即可。

## 数据访问穿透能力

### 复用管理端路由 + 加 BOSS 鉴权

现有管理端路由默认「全公司可见」（无 user_id 过滤），BOSS 复用即可。

### 数据范围（穿透语义）

| 场景 | BOSS 可见 |
|---|---|
| 发票列表筛选 | 全公司所有部门、所有员工、所有状态 |
| 报销单列表筛选 | 全公司所有部门、所有员工、所有状态（含已报销/待审批/已拒绝） |
| 发票详情 | 全部字段（销售方/购买方/金额/税额/明细）+ 关联报销单 |
| 报销单详情 | 全部字段 + 关联发票列表 + 审批记录 |
| 员工列表 | 全部员工（含部门/工号）— 用于问数下钻 |
| 项目列表 | 全部项目 — 用于穿透项目归属 |
| 报表导出 | Excel/PDF 全公司报表 |

### 问数穿透（智能问数）

后端 BOSS 意图已注册（`intent_registry.py:526-666`），共 10 个：

| 意图 | 含义 |
|---|---|
| `insight_total` | 全公司发票总额 |
| `insight_by_category` | 按费用分类汇总 |
| `insight_category_amount` | 指定分类金额 |
| `insight_trend` | 月度趋势 |
| `insight_anomaly` | 异常告警（重复/高风险/验真失败） |
| `insight_top` | Top N（员工/部门/项目） |
| `insight_project` | 按项目汇总 |
| `insight_invoice_total` | 发票总数 |
| `insight_invoice_filter` | 按条件筛选发票 |
| **BOSS 独有 3 个** ||
| `insight_by_dept` | 按部门汇总 |
| `insight_person` | 个人维度对比 |
| `insight_compare` | 多维度对比 |

`role_gate.py:58-67` 已配置 BOSS 对 `insight_*` 数据范围 = `read_only_all`（全公司只读），引擎实现也已是全公司范围（无 user_id 过滤）。

**前端 BOSS 问数端点**：`POST /api/dialog/message`（与 admin 共用），body 传 `role: "boss"`，后端按 BOSS 角色路由意图。

### 列表筛选参数

后端现有 `/api/invoices?status=&user_id=&receipt_type=&page=&size=` 已支持筛选，BOSS 列表页前端可调：
- 状态筛选（全部/已确认/待复核/已报销）
- 部门/员工筛选（前端调 `/api/employees` 拉部门员工列表）
- 时间范围（开始日期/结束日期）
- 关键字搜索（销售方/invoice_number）

报销单列表筛选：
- 状态（全部/待审批/已批准/已拒绝/已报销）
- 部门/员工
- 时间范围

### 性能考量

BOSS 看全公司数据，列表查询需带分页（现有端点已支持 `page` / `size`，默认 size=20）。前端列表页默认拉 20 条，下拉加载更多（IntersectionObserver）。

## 前端移动端布局

### `BossLayout`（壳）

```
┌─────────────────────────┐
│                         │ ← 当前页面内容（充满）
│                         │
│                         │
│                         │
├─────────────────────────┤
│  💬      📄       🧾     │ ← 底部固定 Tab Bar (56px)
│  问数   发票    报销单    │   3 个 Tab，活跃态高亮
└─────────────────────────┘
```

- Tab Bar 仅在列表/对话/详情顶层显示
- 详情页（`/boss/invoices/:id` 等）隐藏 Tab Bar，返回靠左上角 ← 按钮
- 移动 viewport 适配 `width=device-width, initial-scale=1, maximum-scale=1`

### `BossLogin`

- 移动端单列布局
- 顶部 logo / 「老板端」标题
- 表单：用户名 / 密码 / 登录按钮
- 调 `POST /api/boss/auth/login` → 存 `localStorage.boss_token` → 跳 `/boss/chat`

### `BossChat`（首页）

- 全屏聊天界面
- 顶部：标题「老板智能问数」+ 右上角刷新按钮（重置对话）
- 中部：消息流（用户消息右气泡 / AI 消息左气泡）
  - **AI 消息渲染**：文本段 + 表格段（Markdown 表格，水平滚动）+ 可点击 chip（发票号/报销单号 → 跳详情）
  - 不要图表
- 底部：固定输入框 + 发送按钮 + 「清除对话」按钮
- 启动时显示欢迎语：「您好，请直接问我公司报销情况，例如：本月各部门发票总额？陈辉有几张待审报销单？」

### `BossInvoiceList`

- 顶部：固定筛选条（状态 / 部门 / 时间）+ 搜索框
- 中部：发票卡片列表（移动端卡片式而非表格）
  ```
  ┌──────────────────────────┐
  │ 销售方名称            ¥215.80 │
  │ 2025-12-17  已确认       发票号 │
  └──────────────────────────┘
  ```
- 下拉加载更多（IntersectionObserver）
- 点击卡片 → `/boss/invoices/:id`

### `BossInvoiceDetail`

- 左上角 ← 返回
- 顶部：发票号 + 状态徽章
- 中部：发票字段卡（销售方/购买方/金额/税额/开票日期/项目）
- 关联报销单卡（如果有，点击跳 `/boss/reimbursements/:id`）
- 底部：原始发票图片预览（可放大）
- **无操作按钮**（纯只读，不显示审批/删除/编辑按钮）

### `BossReimbursementList` / `BossReimbursementDetail`

结构同发票，列表筛选维度换为报销单状态，详情显示：报销单基本信息 + 关联发票列表（点击跳发票详情）+ 审批记录时间线。

### 组件复用

| 现有组件 | 老板端是否复用 | 备注 |
|---|---|---|
| `StatusBadge` | ✅ | 复用，状态显示 |
| `EmptyState` | ✅ | 复用，空列表占位 |
| `ConfirmModal` | ❌ | BOSS 纯只读，无确认弹窗 |
| `StatCard` | ❌ | 仪表盘才用，BOSS 首页是对话 |
| `ChatWidget`（现有悬浮组件）| ❌ | BOSS 用全屏对话，不复用悬浮组件 |
| `Sidebar`（admin 用）| ❌ | BOSS 用底部 Tab |
| `PortalLayout`（员工用）| ❌ | BOSS 用独立 BossLayout |

### 移动端样式策略

- 不引入新 UI 库，复用现有 Tailwind / CSS
- 新增 `frontend/src/index.css` 的 `.boss-mobile-*` 前缀类
- 响应式断点：`max-width: 768px`（老板手机端），桌面端访问 `/boss` 也能看（容器最大宽度 480px 居中）

## 错误处理

### 认证层

| 场景 | HTTP | 响应 | 前端行为 |
|---|---|---|---|
| 用户名/密码错 | 401 | `{detail: "用户名或密码错误"}` | 表单下方提示，不清 token |
| `boss_token` 缺失 | 401 | `{detail: "未登录或登录已过期"}` | 跳 `/boss/login` |
| `boss_token` 过期（>24h）| 401 | 同上 | 同上 |
| BOSS 访问写操作端点 | 403 | `{detail: "需要管理员权限"}` | 列表/详情页正常使用，写按钮隐藏——不会触发 |

### 数据访问层

| 场景 | HTTP | 前端行为 |
|---|---|---|
| 发票 ID 不存在 | 404 | 列表页展示「发票不存在」+ 返回按钮 |
| 报销单 ID 不存在 | 404 | 同上 |
| LLM 调用失败（问数） | 200 + body.error | 对话气泡显示「AI 服务暂时不可用，请稍后重试」+ 保留用户消息 |
| LLM 返回 JSON 解析失败 | 200 + body.error | 同上 |
| 列表分页超出范围 | 200 + `[]` | 显示 EmptyState + 提示「没有更多了」 |

### 边界场景

| 场景 | 处理 |
|---|---|
| `.env` 未配 BOSS 凭证 | `boss_login` 返回 500 + 「老板账号未配置」 |
| 同一浏览器登录 admin 和 boss | token key 独立（`admin_token` vs `boss_token`），互不影响 |
| 老板 token 调用 admin 写端点 | 后端 `get_current_admin` 拒绝（role=boss 不在白名单） |
| 老板用 admin 端口访问 | 路由 `/admin/*` 受 `<AdminProtected>` 守卫，boss_token 会被识别为有效但路由跳转可能出错——前端在 BossProtected 内强制只渲染 `/boss/*` 路由，admin 路由不让 boss token 进入 |

## 测试

### 后端单元测试

`backend/tests/test_boss_auth.py`（新建）：

```python
def test_boss_login_success(client, settings_with_boss_creds):
    # 配置 BOSS_USERNAME=zhang, BOSS_PASSWORD_HASH=hash("zhang")
    resp = client.post("/api/boss/auth/login", json={"username":"zhang","password":"zhang"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["profile"]["role"] == "boss"

def test_boss_login_wrong_password(client, settings_with_boss_creds):
    resp = client.post("/api/boss/auth/login", json={"username":"zhang","password":"wrong"})
    assert resp.status_code == 401

def test_boss_can_read_invoices(client, boss_token):
    resp = client.get("/api/invoices", headers={"Authorization": f"Bearer {boss_token}"})
    assert resp.status_code == 200

def test_boss_cannot_delete_invoice(client, boss_token):
    resp = client.delete("/api/invoices/1", headers={"Authorization": f"Bearer {boss_token}"})
    assert resp.status_code == 403

def test_boss_can_call_dialog(client, boss_token):
    resp = client.post("/api/dialog/message",
        json={"message":"本月发票总额","role":"boss"},
        headers={"Authorization": f"Bearer {boss_token}"})
    assert resp.status_code == 200
    assert "total" in resp.json()["text"].lower() or "总额" in resp.json()["text"]
```

### 后端权限矩阵测试

`backend/tests/test_role_matrix.py`（新建）：
- 遍历所有写操作端点，验证 BOSS token 返回 403
- 遍历所有读操作端点，验证 BOSS token 返回 200

### 端到端测试

`backend/scripts/e2e_boss_test.py`（新建）：
1. 登录 BOSS → 拿 token
2. POST `/api/dialog/message` 问「本月发票总额」→ 验证返回文本+表格
3. GET `/api/invoices` → 验证返回全公司发票列表
4. GET `/api/invoices/{id}` → 验证详情
5. DELETE `/api/invoices/{id}` → 验证 403

### 前端手动验证清单

1. iPhone Safari / Android Chrome 访问 `/boss/login` → 登录 → 跳 `/boss/chat`
2. 输入「本月各部门发票总额」→ 返回表格 → 点击发票号 chip 跳详情
3. 底部 Tab 切到「发票」→ 列表加载 → 筛选部门 → 下拉加载更多
4. 点发票卡片 → 详情页 → 点击关联报销单 → 跳报销单详情
5. 切到「报销单」Tab → 同上验证
6. 关闭浏览器重开 → token 仍在（24h 内）→ 直跳对话页
7. 24h 后访问 → 跳登录页

## 验证步骤（开发完到上线前）

1. **后端启动验证**：`docker compose up -d --force-recreate backend`，看日志确认无报错
2. **认证冒烟**：`curl POST /api/boss/auth/login` 用 zhang/zhang，拿 token
3. **路由穿透验证**：用 token 调 GET `/api/invoices`，验证返回全公司数据
4. **权限边界验证**：用 token 调 DELETE `/api/invoices/{id}`，验证 403
5. **问数验证**：用 token 调 POST `/api/dialog/message` body `{"message":"本月发票总额","role":"boss"}`，验证返回文本+表格
6. **前端启动验证**：`npm run dev`（frontend），访问 `http://localhost:5173/boss/login`
7. **手机端验证**：手机浏览器访问 `http://<局域网IP>:5173/boss/login`，验证移动端布局
8. **回归验证**：admin 端 `http://localhost:13000/` + 员工端 `/portal/login` 不受影响

## 修改文件清单

| 文件 | 改动 |
|---|---|
| `.env` | 加 `BOSS_USERNAME=zhang` / `BOSS_PASSWORD_HASH=...` |
| `backend/app/config.py` | 加 `boss_username` / `boss_password_hash` 字段 |
| `backend/app/routers/admin_auth.py` | 加 `boss_login` 端点 + `get_current_admin_or_boss` 依赖 |
| `backend/app/routers/invoices.py` | GET 端点改 `get_current_admin_or_boss` |
| `backend/app/routers/reimbursements.py` | GET 端点改 `get_current_admin_or_boss` |
| `backend/app/routers/reports.py` | GET 端点改 `get_current_admin_or_boss` |
| `backend/app/routers/employees.py` | GET 端点改 `get_current_admin_or_boss` |
| `backend/app/routers/projects.py` | GET 端点改 `get_current_admin_or_boss` |
| `backend/app/routers/dialog.py` | `POST /api/dialog/message` 鉴权改 `get_current_admin_or_boss` |
| `backend/app/main.py` | 注册 boss_auth router |
| `frontend/src/api/client.ts` | 加 `boss_token` 存取 + 拦截器 |
| `frontend/src/components/BossProtected.tsx`（新建）| 路由守卫 |
| `frontend/src/components/BossLayout.tsx`（新建）| 底部 Tab 容器 |
| `frontend/src/pages/boss/Login.tsx`（新建）| 移动端登录页 |
| `frontend/src/pages/boss/Chat.tsx`（新建）| 全屏问数对话 |
| `frontend/src/pages/boss/InvoiceList.tsx`（新建）| 发票列表（卡片式） |
| `frontend/src/pages/boss/InvoiceDetail.tsx`（新建）| 发票详情 |
| `frontend/src/pages/boss/ReimbursementList.tsx`（新建）| 报销单列表 |
| `frontend/src/pages/boss/ReimbursementDetail.tsx`（新建）| 报销单详情 |
| `frontend/src/App.tsx` | 加 `/boss/*` 路由分支 |
| `frontend/src/index.css` | 加 boss-mobile 样式前缀 |
| `backend/tests/test_boss_auth.py`（新建）| 认证单元测试 |
| `backend/tests/test_role_matrix.py`（新建）| 权限矩阵测试 |
| `backend/scripts/e2e_boss_test.py`（新建）| E2E 验证脚本 |
