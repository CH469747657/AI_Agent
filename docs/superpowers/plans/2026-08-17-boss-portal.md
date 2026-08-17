# 老板专属登录端 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「老板端」入口 — 老板账号 `zhang/zhang` 通过手机端登录，可穿透查看全公司发票/报销单明细 + 智能问数。

**Architecture:** 后端复用现有 BOSS 角色（`UserRole.BOSS` 已定义、`role_gate.py` 权限矩阵已就绪、`intent_registry.py` BOSS 意图已注册、`insight_engine.py` BOSS 洞察方法已实现），仅新增 BOSS 认证端点 + 在 GET 路由放宽鉴权为 `get_current_admin_or_boss`。前端新增 `/boss/*` 移动端路由，3 个底部 Tab（问数/发票/报销单）+ 详情页可下钻。

**Tech Stack:** FastAPI + JWT (后端) / React + React Router + Vite + Tailwind (前端) / pytest (测试)

## Global Constraints

- BOSS 账号：`zhang/zhang`，凭证存 `.env`，**不进 DB**（仿 admin 模式）
- 后端 JWT 必须含 `role=boss`，与 admin token 在 localStorage 用不同 key（`boss_token` vs `admin_token`）
- 写操作端点保持 `Depends(get_current_admin)`，BOSS token 调用返回 403
- 老板端纯只读：不显示审批/删除/编辑按钮
- 移动端优先：`viewport-fit=cover, width=device-width, initial-scale=1`，桌面访问容器最大宽度 480px 居中
- 问数返回：文本 + 表格（Markdown 表格水平滚动），**不要图表**
- 对话返回的发票号 / 报销单号渲染为可点击 chip，跳详情页
- 文件路径精确，代码片段完整可粘贴，不写占位符

---

## 文件结构

### 后端

| 文件 | 责任 |
|---|---|
| `backend/app/config.py` (修改) | 加 `boss_username` / `boss_password_hash` 字段 |
| `backend/app/routers/admin_auth.py` (修改) | 加 `boss_login` 端点 + `get_current_admin_or_boss` 依赖 |
| `backend/app/routers/invoices.py` (修改) | router-level 依赖改为 admin_or_boss；写端点显式覆盖回 `get_current_admin` |
| `backend/app/routers/reimbursements.py` (修改) | 同上 |
| `backend/app/routers/reports.py` (修改) | 同上（仅 GET，写端点保持 admin） |
| `backend/app/routers/employees.py` (修改) | router-level 改 admin_or_boss；POST/PUT/DELETE 端点显式覆盖回 `get_current_admin` |
| `backend/app/routers/projects.py` (修改) | 同上 |
| `backend/app/routers/dialog.py` (修改) | router-level 改 admin_or_boss |
| `backend/app/main.py` (修改) | 注册 `admin_auth.router` 已存在；boss_login 端点已挂在 admin_auth.router 上，复用 `/api/admin/auth/login` 路径不行——需新建子 router |
| `backend/tests/test_boss_auth.py` (新建) | BOSS 登录/读/写权限单元测试 |
| `backend/scripts/e2e_boss_test.py` (新建) | 端到端验证脚本 |

### 前端

| 文件 | 责任 |
|---|---|
| `frontend/src/api/client.ts` (修改) | 加 `bossApi`（login/getToken/logout）+ `bossRequest`（自动注入 boss_token） |
| `frontend/src/components/BossProtected.tsx` (新建) | 路由守卫 |
| `frontend/src/components/BossLayout.tsx` (新建) | 底部 Tab 容器 |
| `frontend/src/pages/boss/Login.tsx` (新建) | 移动端登录页 |
| `frontend/src/pages/boss/Chat.tsx` (新建) | 全屏问数对话 |
| `frontend/src/pages/boss/InvoiceList.tsx` (新建) | 发票列表（卡片式） |
| `frontend/src/pages/boss/InvoiceDetail.tsx` (新建) | 发票详情 |
| `frontend/src/pages/boss/ReimbursementList.tsx` (新建) | 报销单列表 |
| `frontend/src/pages/boss/ReimbursementDetail.tsx` (新建) | 报销单详情 |
| `frontend/src/App.tsx` (修改) | 加 `/boss/*` 路由分支 |
| `frontend/src/index.css` (修改) | 加 `.boss-*` 移动端样式 |

---

## Task 1：后端 BOSS 配置 + 认证端点

**Files:**
- Modify: `backend/app/config.py:55`（在 `admin_password_hash` 后加 `boss_username` / `boss_password_hash`）
- Modify: `backend/app/routers/admin_auth.py`（新增 `boss_login` + `get_current_admin_or_boss`）
- Modify: `backend/app/main.py:174`（注册 boss 路由）
- Create: `backend/tests/test_boss_auth.py`

**Interfaces:**
- Produces: `POST /api/boss/auth/login` 端点（请求 `{username, password}`，返回 `{access_token, token_type, profile:{username, role:"boss"}}`）
- Produces: `get_current_admin_or_boss(authorization: str = Header(None)) -> dict` 鉴权依赖（返回 `{"sub","role"}`），admin/boss JWT 都通过
- Produces: `settings.boss_username` / `settings.boss_password_hash` 字段

- [ ] **Step 1: 生成 zhang 密码的 bcrypt 哈希**

Run:
```bash
docker exec ai-reimbursement-agent-backend-1 python3 -c "from app.services.auth_service import hash_password; print(hash_password('zhang'))"
```
Expected: 输出 `$2b$12$...` 开头的哈希字符串（60 字符）。**复制此值用于 Step 2。**

- [ ] **Step 2: 更新 `.env` 加 BOSS 凭证**

在 `.env:52`（`ADMIN_PASSWORD_HASH=...` 之后）插入：

```
# 老板端账号（zhang / zhang，仅查看全公司数据）
BOSS_USERNAME=zhang
BOSS_PASSWORD_HASH=<粘贴 Step 1 输出的哈希>
```

- [ ] **Step 3: 在 `backend/app/config.py:55` 后加 BOSS 配置字段**

`backend/app/config.py` 第 55 行 `admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")` 之后追加：

```python
    admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")

    # 老板端账号 — 单一老板账户，账户名/密码哈希从 .env 读取
    # 与员工端 employees 表、管理端 admin 账户完全分离
    boss_username: str = os.getenv("BOSS_USERNAME", "")
    boss_password_hash: str = os.getenv("BOSS_PASSWORD_HASH", "")
```

- [ ] **Step 4: 在 `backend/app/routers/admin_auth.py` 末尾加 `boss_login` 端点**

在文件末尾追加：

```python


# ============================================================
# 老板端认证（BOSS）— 复用 admin_auth 的 JWT 机制，独立路由前缀
# ============================================================

boss_router = APIRouter()


class BossLoginRequest(BaseModel):
    """老板端登录请求"""
    username: str
    password: str


@boss_router.post("/login")
async def boss_login(request: BossLoginRequest):
    """老板端登录 — 用户名+密码，返回 JWT (role=boss)

    凭证从 .env 读取（BOSS_USERNAME / BOSS_PASSWORD_HASH）。
    """
    username = settings.boss_username
    if not username:
        logger.error("BOSS_USERNAME 未配置")
        raise HTTPException(status_code=500, detail="老板账号未配置")

    password_hash = settings.boss_password_hash
    if not password_hash:
        logger.error("BOSS_PASSWORD_HASH 未配置")
        raise HTTPException(status_code=500, detail="老板账号未配置")

    if request.username != username:
        logger.warning(f"Boss login failed: wrong username={request.username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(request.password, password_hash):
        logger.warning(f"Boss login failed: wrong password for username={request.username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    import jwt
    from app.services.auth_service import JWT_SECRET, JWT_ALGORITHM
    from datetime import timedelta
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": username,
        "emp_id": 0,
        "name": "老板",
        "role": "boss",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    logger.info(f"Boss {username} logged in")

    return {
        "access_token": token,
        "token_type": "bearer",
        "profile": {
            "username": username,
            "name": "老板",
            "role": "boss",
        },
    }


async def get_current_admin_or_boss(authorization: str = Header(None)) -> dict[str, Any]:
    """管理端/老板端通用鉴权依赖

    允许 admin 或 boss JWT 通过，返回 {"sub","name","role"}。
    用于在 GET 路由上放宽权限让 BOSS 也能读，写路由仍用 get_current_admin。
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    token = authorization[7:]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    role = payload.get("role")
    if role not in ("admin", "boss"):
        raise HTTPException(status_code=403, detail="需要管理员或老板权限")

    return {
        "username": payload.get("sub"),
        "name": payload.get("name", ""),
        "role": role,
    }
```

- [ ] **Step 5: 在 `backend/app/main.py:174` 后注册 boss_router**

在 `main.py:174`（`app.include_router(admin_auth_router, prefix="/api/admin/auth", ...)` 之后）插入：

```python
app.include_router(admin_auth_router, prefix="/api/admin/auth", tags=["管理端-认证"])

# 老板端认证路由（boss 账户，与管理端 admin 账户独立）
from app.routers.admin_auth import boss_router as boss_auth_router
app.include_router(boss_auth_router, prefix="/api/boss/auth", tags=["老板端-认证"])
```

- [ ] **Step 6: 写测试 `backend/tests/test_boss_auth.py`**

完整文件内容：

```python
"""BOSS 端认证 + 权限边界测试"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.config import settings
from app.services.auth_service import hash_password


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def setup_boss_creds(monkeypatch):
    """注入 BOSS 凭证到 settings（避免依赖 .env）"""
    monkeypatch.setattr(settings, "boss_username", "zhang")
    monkeypatch.setattr(settings, "boss_password_hash", hash_password("zhang"))


def test_boss_login_success(client):
    resp = client.post("/api/boss/auth/login", json={"username": "zhang", "password": "zhang"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["profile"]["role"] == "boss"
    assert body["profile"]["username"] == "zhang"
    assert body["access_token"]


def test_boss_login_wrong_password(client):
    resp = client.post("/api/boss/auth/login", json={"username": "zhang", "password": "wrong"})
    assert resp.status_code == 401


def test_boss_login_wrong_username(client):
    resp = client.post("/api/boss/auth/login", json={"username": "other", "password": "zhang"})
    assert resp.status_code == 401


def test_boss_login_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "boss_username", "")
    resp = client.post("/api/boss/auth/login", json={"username": "zhang", "password": "zhang"})
    assert resp.status_code == 500


def _boss_token(client) -> str:
    resp = client.post("/api/boss/auth/login", json={"username": "zhang", "password": "zhang"})
    return resp.json()["access_token"]


def test_boss_can_read_invoices(client):
    token = _boss_token(client)
    resp = client.get("/api/invoices", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_boss_can_read_reimbursements(client):
    token = _boss_token(client)
    resp = client.get("/api/reimbursements", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_boss_can_read_employees(client):
    token = _boss_token(client)
    resp = client.get("/api/employees", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_boss_can_read_projects(client):
    token = _boss_token(client)
    resp = client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_boss_cannot_delete_invoice(client):
    """BOSS token 调 DELETE 端点应返回 403（写端点保持 get_current_admin）"""
    token = _boss_token(client)
    resp = client.delete("/api/invoices/9999", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_boss_cannot_approve_reimbursement(client):
    token = _boss_token(client)
    resp = client.put("/api/reimbursements/9999/approve", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_boss_cannot_create_employee(client):
    token = _boss_token(client)
    resp = client.post("/api/employees", json={"employee_no": "X", "name": "X"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_boss_cannot_delete_reimbursement(client):
    token = _boss_token(client)
    resp = client.delete("/api/reimbursements/9999", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_boss_token_no_admin_access(client):
    """BOSS token 调 admin 写端点（如改密）应 403"""
    token = _boss_token(client)
    resp = client.post(
        "/api/admin/auth/change-password",
        json={"old_password": "zhang", "new_password": "newpass123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 7: 运行测试验证失败**

Run:
```bash
docker cp backend/tests/test_boss_auth.py ai-reimbursement-agent-backend-1:/app/tests/test_boss_auth.py
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_boss_auth.py -v
```
Expected: 多数测试 FAIL（路由未注册、`boss_username` 字段不存在、写端点未保持 admin），证明测试能捕捉到改造前的状态。

- [ ] **Step 8: 同步代码到容器**

Run:
```bash
docker cp backend/app/config.py ai-reimbursement-agent-backend-1:/app/app/config.py
docker cp backend/app/routers/admin_auth.py ai-reimbursement-agent-backend-1:/app/app/routers/admin_auth.py
docker cp backend/app/main.py ai-reimbursement-agent-backend-1:/app/app/main.py
```

- [ ] **Step 9: 重启 backend 让新代码生效**

Run:
```bash
docker compose restart backend
sleep 5
```
Expected: backend 启动无报错。

- [ ] **Step 10: 运行测试验证通过**

Run:
```bash
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_boss_auth.py -v
```
Expected: 所有 12 个测试 PASS（写端点 403 的测试此时还失败——因为 Task 2 才改 router-level 鉴权，但读端点测试此时应 PASS）。

> **注意：** Task 1 阶段写端点测试（`test_boss_cannot_*`）仍会 FAIL，因为路由级 `Depends(get_current_admin)` 在 Task 2 才改成 `get_current_admin_or_boss`。Task 1 完成后，只验证读端点测试 PASS、登录测试 PASS。写端点测试在 Task 2 完成后才会 PASS（因为要 router-level 改为 admin_or_boss + 写端点显式覆盖回 admin）。

- [ ] **Step 11: Commit**

```bash
git add .env backend/app/config.py backend/app/routers/admin_auth.py backend/app/main.py backend/tests/test_boss_auth.py
git commit -m "feat(boss): 新增老板端认证端点 + BOSS_USERNAME/BOSS_PASSWORD_HASH 配置"
```

---

## Task 2：放宽 GET 路由鉴权为 admin_or_boss

**Files:**
- Modify: `backend/app/routers/invoices.py:16`、`invoices.py:22`、`invoices.py:58`、`invoices.py:77`、`invoices.py:147`、`invoices.py:302`、`invoices.py:309`
- Modify: `backend/app/routers/reimbursements.py:27`、各 GET 端点显式覆盖
- Modify: `backend/app/routers/reports.py:15`、`reports.py:33`
- Modify: `backend/app/routers/employees.py:25`、各 POST/PUT/DELETE 端点显式覆盖
- Modify: `backend/app/routers/projects.py:12`、`projects.py:51`
- Modify: `backend/app/routers/dialog.py:24`

**Interfaces:**
- Consumes: `get_current_admin_or_boss` from Task 1
- Produces: BOSS JWT 可调 GET `/api/invoices` / `/api/reimbursements` / `/api/employees` / `/api/projects` / `/api/reports/download/*` / `/api/dialog/message`，写端点仍返回 403

**关键策略**：每个 router 默认 `dependencies=[Depends(get_current_admin_or_boss)]`，写端点（POST/PUT/DELETE）在装饰器显式 `dependencies=[Depends(get_current_admin)]` 覆盖——保证 BOSS 调写端点 403。

- [ ] **Step 1: 修改 `backend/app/routers/invoices.py`**

第 8 行 import 改为：
```python
from app.routers.admin_auth import get_current_admin, get_current_admin_or_boss
```

第 16 行改为：
```python
router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])
```

写端点（`/upload`、`/wecom-process`、`/no-receipt`，以及文件内的 POST/PUT/DELETE 端点）装饰器加 `dependencies=[Depends(get_current_admin)]`，例：

`invoices.py:22` 改为：
```python
@router.post("/upload", response_model=InvoiceResponse, dependencies=[Depends(get_current_admin)])
```

`invoices.py:58` 改为：
```python
@router.post("/wecom-process", response_model=InvoiceResponse, dependencies=[Depends(get_current_admin)])
```

`invoices.py:77` 改为：
```python
@router.post("/no-receipt", response_model=InvoiceResponse, dependencies=[Depends(get_current_admin)])
```

GET 端点（`/`、`/export`、`/statistics`、`/nonstandard-stats`）保持原签名即可（router-level 已放宽）。

> 用 `grep -nE "@router\.(post|put|delete)" backend/app/routers/invoices.py` 找全所有写端点，逐一加 `dependencies=[Depends(get_current_admin)]`。

- [ ] **Step 2: 修改 `backend/app/routers/reimbursements.py`**

第 17 行 import 改为：
```python
from app.routers.admin_auth import get_current_admin, get_current_admin_or_boss
```

第 27 行改为：
```python
router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])
```

所有写端点（POST/PUT/DELETE：`POST /`、`PUT /{id}/invoices`、`PUT /{id}/unlink/{invoice_id}`、`PUT /{id}/submit`、`PUT /{id}/withdraw`、`PUT /{id}/approve`、`PUT /{id}/reject`、`PUT /{id}/reimburse`、`PUT /{id}/subsidy/toggle`、`POST /cycle/lock/{cycle_key}`、`POST /aggregate`、`DELETE /{id}`、`POST /{id}/attachments`、`DELETE /{id}/attachments/{attachment_id}`）装饰器加 `dependencies=[Depends(get_current_admin)]`。

GET 端点（`/`、`/{id}`、`/cycle/status/{cycle_key}`、`/{id}/attachments/{attachment_id}/download`）保持不变。

- [ ] **Step 3: 修改 `backend/app/routers/reports.py`**

第 12 行 import 改为：
```python
from app.routers.admin_auth import get_current_admin, get_current_admin_or_boss
```

第 15 行改为：
```python
router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])
```

`reports.py:18` 的 `POST /generate/{reimbursement_id}` 加 `dependencies=[Depends(get_current_admin)]`。

GET `/download/{reimbursement_id}/{file_type}` 保持不变（BOSS 可下载报表）。

- [ ] **Step 4: 修改 `backend/app/routers/employees.py`**

第 15 行 import 改为：
```python
from app.routers.admin_auth import get_current_admin, get_current_admin_or_boss
```

第 25 行改为：
```python
router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])
```

写端点（`POST /sync`、`POST /`、`POST /batch/upload`、`PUT /{id}`、`DELETE /{id}`）装饰器加 `dependencies=[Depends(get_current_admin)]`。

GET 端点（`/`、`/{id}`、`/batch/template`）保持不变。

- [ ] **Step 5: 修改 `backend/app/routers/projects.py`**

第 9 行 import 改为：
```python
from app.routers.admin_auth import get_current_admin, get_current_admin_or_boss
```

第 12 行改为：
```python
router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])
```

`projects.py:15` 的 `POST /` 和 `projects.py:51` 的 `PUT /{project_id}/members` 加 `dependencies=[Depends(get_current_admin)]`。

GET 端点（`/`、`/{id}`）保持不变。

- [ ] **Step 6: 修改 `backend/app/routers/dialog.py`**

第 19 行 import 改为：
```python
from app.routers.admin_auth import get_current_admin_or_boss
```

第 24 行改为：
```python
router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])
```

- [ ] **Step 7: 运行测试（验证写端点测试 PASS）**

Run:
```bash
docker cp backend/app/routers/invoices.py ai-reimbursement-agent-backend-1:/app/app/routers/invoices.py
docker cp backend/app/routers/reimbursements.py ai-reimbursement-agent-backend-1:/app/app/routers/reimbursements.py
docker cp backend/app/routers/reports.py ai-reimbursement-agent-backend-1:/app/app/routers/reports.py
docker cp backend/app/routers/employees.py ai-reimbursement-agent-backend-1:/app/app/routers/employees.py
docker cp backend/app/routers/projects.py ai-reimbursement-agent-backend-1:/app/app/routers/projects.py
docker cp backend/app/routers/dialog.py ai-reimbursement-agent-backend-1:/app/app/routers/dialog.py
docker compose restart backend
sleep 5
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_boss_auth.py -v
```
Expected: 12 个测试全部 PASS。

- [ ] **Step 8: 手动冒烟验证 BOSS 端到端**

Run:
```bash
# 1. 登录拿 token
TOKEN=$(curl -s -X POST http://localhost:18080/api/boss/auth/login -H "Content-Type: application/json" -d '{"username":"zhang","password":"zhang"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
echo "TOKEN_LEN=${#TOKEN}"

# 2. 读发票列表（应 200）
curl -s -o /dev/null -w "GET /api/invoices: %{http_code}\n" http://localhost:18080/api/invoices -H "Authorization: Bearer $TOKEN"

# 3. 读报销单列表（应 200）
curl -s -o /dev/null -w "GET /api/reimbursements: %{http_code}\n" http://localhost:18080/api/reimbursements -H "Authorization: Bearer $TOKEN"

# 4. 删发票（应 403）
curl -s -o /dev/null -w "DELETE /api/invoices/9999: %{http_code}\n" -X DELETE http://localhost:18080/api/invoices/9999 -H "Authorization: Bearer $TOKEN"

# 5. 调对话（应 200）
curl -s -X POST http://localhost:18080/api/dialog/message -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{"user_id":"zhang","text":"本月发票总额","role":"boss"}' | head -c 300
```
Expected: GET 端点 200，DELETE 403，dialog 返回 JSON 含 `text` 字段。

- [ ] **Step 9: Commit**

```bash
git add backend/app/routers/
git commit -m "feat(boss): GET 路由放宽为 admin_or_boss 鉴权，写端点保持 admin 403"
```

---

## Task 3：前端 API 客户端扩展 BOSS token

**Files:**
- Modify: `frontend/src/api/client.ts`（在 `adminApi` 后追加 `bossApi` + `bossRequest`）

**Interfaces:**
- Produces: `bossApi.login(username, password)` → `BossLoginResponse`
- Produces: `bossApi.getToken()` / `bossApi.logout()` / `bossApi.getStoredBoss()`
- Produces: `bossRequest<T>(url, options)` 自动注入 `boss_token`
- Produces: `bossApi.listInvoices()` / `bossApi.invoiceDetail(id)` / `bossApi.listReimbursements()` / `bossApi.reimbursementDetail(id)` / `bossApi.sendMessage(params)`

- [ ] **Step 1: 在 `frontend/src/api/client.ts` 末尾追加 BOSS API 块**

在文件末尾追加：

```typescript

// ===== 老板端 Boss API =====

export interface BossLoginResponse {
  access_token: string;
  token_type: string;
  profile: {
    username: string;
    name: string;
    role: "boss";
  };
}

const BOSS_BASE = "/api";

/** 获取 boss token */
function getBossToken(): string | null {
  return localStorage.getItem("boss_token");
}

/** 保存 boss token */
function setBossToken(token: string) {
  localStorage.setItem("boss_token", token);
}

/** 清除 boss token */
function clearBossToken() {
  localStorage.removeItem("boss_token");
  localStorage.removeItem("boss_profile");
}

/** boss 请求封装（自动携带 Authorization） */
async function bossRequest<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const token = getBossToken();
  const headers: Record<string, string> = {
    ...(options?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${BOSS_BASE}${url}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    if (res.status === 401) {
      clearBossToken();
      if (!window.location.pathname.startsWith("/boss/login")) {
        window.location.href = "/boss/login";
      }
      throw new Error("登录已过期，请重新登录");
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `请求失败 (${res.status})`);
  }
  return res.json();
}

export const bossApi = {
  // 认证
  login: async (username: string, password: string): Promise<BossLoginResponse> => {
    const res = await fetch(`/api/boss/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "登录失败");
    }
    const data: BossLoginResponse = await res.json();
    setBossToken(data.access_token);
    localStorage.setItem("boss_profile", JSON.stringify(data.profile));
    return data;
  },

  logout: () => {
    clearBossToken();
  },

  getToken: getBossToken,

  getStoredBoss: (): BossLoginResponse["profile"] | null => {
    const raw = localStorage.getItem("boss_profile");
    return raw ? JSON.parse(raw) : null;
  },

  // 发票（复用管理端路由，BOSS JWT 鉴权）
  listInvoices: (params?: { status?: string; user_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.user_id) qs.set("user_id", params.user_id);
    const q = qs.toString();
    return bossRequest<Invoice[]>(`/invoices${q ? "?" + q : ""}`);
  },

  invoiceDetail: (id: number) => bossRequest<InvoiceDetail>(`/invoices/${id}`),

  invoiceFileUrl: (id: number) => `${BOSS_BASE}/invoices/${id}/file`,

  // 报销单（复用管理端路由）
  listReimbursements: (params?: { applicant_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.applicant_id) qs.set("applicant_id", params.applicant_id);
    const q = qs.toString();
    return bossRequest<Reimbursement[]>(`/reimbursements${q ? "?" + q : ""}`);
  },

  reimbursementDetail: (id: number) => bossRequest<Reimbursement>(`/reimbursements/${id}`),

  // 员工列表（用于筛选）
  listEmployees: () => bossRequest<Employee[]>(`/employees`),

  // 对话（复用管理端 /api/dialog/message，role=boss）
  sendMessage: (params: { text: string }) => {
    const body = {
      user_id: "zhang",
      text: params.text,
      role: "boss",
      has_attachment: false,
      attachment_base64: null,
      attachment_file_type: null,
      receipt_type: null,
      user_description: null,
      no_receipt_amount: null,
    };
    return bossRequest<DialogAPIResponse>(`/dialog/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  resetDialog: () =>
    bossRequest<{ status: string; message: string }>(
      `/dialog/reset/zhang`,
      { method: "POST" }
    ),

  // 报表下载
  downloadReportUrl: (reimbursementId: number, fileType: string) =>
    `${BOSS_BASE}/reports/download/${reimbursementId}/${fileType}`,

  downloadReport: async (reimbursementId: number, fileType: string): Promise<void> => {
    const token = getBossToken();
    const res = await fetch(
      `${BOSS_BASE}/reports/download/${reimbursementId}/${fileType}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} }
    );
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || "下载失败");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `reimbursement_${reimbursementId}.${fileType}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};
```

- [ ] **Step 2: 验证 TypeScript 编译通过**

Run:
```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```
Expected: 无报错。如果有 `Invoice` / `InvoiceDetail` / `Reimbursement` / `Employee` / `DialogAPIResponse` 类型未导入的错误，检查 `frontend/src/api/client.ts` 顶部的 import 是否包含这些类型（应该已包含，因为 admin/portal API 也在用）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(boss): 前端 API 客户端加 bossApi + bossRequest（独立 token 隔离）"
```

---

## Task 4：前端路由守卫 + 移动端布局组件

**Files:**
- Create: `frontend/src/components/BossProtected.tsx`
- Create: `frontend/src/components/BossLayout.tsx`
- Modify: `frontend/src/App.tsx`（加 `/boss/*` 路由分支）
- Modify: `frontend/src/index.css`（加 `.boss-*` 移动端样式）

**Interfaces:**
- Produces: `<BossProtected>` 路由守卫组件（无 token 跳 `/boss/login`）
- Produces: `<BossLayout>` 底部 Tab 容器（3 Tab：问数/发票/报销单，详情页隐藏 Tab）
- Produces: `/boss/login` / `/boss/chat` / `/boss/invoices` / `/boss/invoices/:id` / `/boss/reimbursements` / `/boss/reimbursements/:id` 路由

- [ ] **Step 1: 创建 `frontend/src/components/BossProtected.tsx`**

```tsx
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { bossApi } from "../api/client";

/**
 * 老板端路由守卫
 * - 无 token → 重定向 /boss/login
 * - 有 token → 渲染子路由
 */
export function BossProtected() {
  const location = useLocation();
  const token = bossApi.getToken();
  if (!token) {
    return <Navigate to="/boss/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}
```

- [ ] **Step 2: 创建 `frontend/src/components/BossLayout.tsx`**

```tsx
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect } from "react";

/**
 * 老板端移动布局容器
 * - 列表/对话页显示底部 Tab
 * - 详情页（/boss/invoices/:id 等）隐藏 Tab，让详情充满屏幕
 */
export function BossLayout() {
  const location = useLocation();
  const navigate = useNavigate();

  // 详情页模式：路径含 :id（如 /boss/invoices/123）
  const isDetailPage = /\/boss\/(invoices|reimbursements)\/\d+/.test(location.pathname);

  // 移动端 viewport meta（确保手机端正确缩放）
  useEffect(() => {
    let meta = document.querySelector('meta[name="viewport"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "viewport");
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", "width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover");
  }, []);

  return (
    <div className="boss-shell">
      <main className={`boss-main ${isDetailPage ? "boss-main--full" : ""}`}>
        <Outlet />
      </main>
      {!isDetailPage && (
        <nav className="boss-tabbar">
          <button
            className={`boss-tab ${location.pathname === "/boss/chat" || location.pathname === "/boss" ? "boss-tab--active" : ""}`}
            onClick={() => navigate("/boss/chat")}
          >
            <span className="boss-tab__icon">💬</span>
            <span className="boss-tab__label">问数</span>
          </button>
          <button
            className={`boss-tab ${location.pathname.startsWith("/boss/invoices") ? "boss-tab--active" : ""}`}
            onClick={() => navigate("/boss/invoices")}
          >
            <span className="boss-tab__icon">📄</span>
            <span className="boss-tab__label">发票</span>
          </button>
          <button
            className={`boss-tab ${location.pathname.startsWith("/boss/reimbursements") ? "boss-tab--active" : ""}`}
            onClick={() => navigate("/boss/reimbursements")}
          >
            <span className="boss-tab__icon">🧾</span>
            <span className="boss-tab__label">报销单</span>
          </button>
        </nav>
      )}
    </div>
  );
}
```

- [ ] **Step 3: 在 `frontend/src/index.css` 末尾追加 boss 移动端样式**

```css
/* ===== 老板端移动端样式 ===== */

.boss-shell {
  min-height: 100dvh;
  background: #f5f5f7;
  display: flex;
  flex-direction: column;
  /* 桌面访问时容器居中，模拟手机 */
  max-width: 480px;
  margin: 0 auto;
  box-shadow: 0 0 24px rgba(0, 0, 0, 0.06);
  position: relative;
}

.boss-main {
  flex: 1;
  overflow-y: auto;
  /* 留出底部 Tab Bar 空间 */
  padding-bottom: 56px;
  -webkit-overflow-scrolling: touch;
}

.boss-main--full {
  padding-bottom: 0;
}

.boss-tabbar {
  position: fixed;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100%;
  max-width: 480px;
  height: 56px;
  background: #fff;
  border-top: 1px solid #e5e5ea;
  display: flex;
  z-index: 100;
  /* 适配 iPhone 底部安全区 */
  padding-bottom: env(safe-area-inset-bottom);
}

.boss-tab {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  color: #8e8e93;
  font-size: 11px;
  gap: 2px;
  cursor: pointer;
  transition: color 0.15s;
}

.boss-tab__icon {
  font-size: 20px;
  line-height: 1;
}

.boss-tab__label {
  font-size: 11px;
}

.boss-tab--active {
  color: #007aff;
}

/* 通用 boss 端卡片样式 */
.boss-card {
  background: #fff;
  border-radius: 12px;
  padding: 14px;
  margin: 8px 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.boss-card--clickable {
  cursor: pointer;
  transition: background 0.15s;
}

.boss-card--clickable:active {
  background: #f5f5f7;
}

.boss-page-title {
  font-size: 17px;
  font-weight: 600;
  padding: 14px 16px 8px;
  margin: 0;
  background: #fff;
  position: sticky;
  top: 0;
  z-index: 10;
  border-bottom: 1px solid #e5e5ea;
}

.boss-back-btn {
  background: none;
  border: none;
  font-size: 24px;
  color: #007aff;
  padding: 8px 12px;
  cursor: pointer;
}

.boss-empty {
  text-align: center;
  padding: 60px 20px;
  color: #8e8e93;
  font-size: 14px;
}

.boss-loading {
  text-align: center;
  padding: 40px;
  color: #8e8e93;
  font-size: 14px;
}

.boss-error {
  background: #fff3f3;
  color: #c00;
  padding: 10px 14px;
  border-radius: 8px;
  margin: 8px 12px;
  font-size: 13px;
}

/* 对话气泡 */
.boss-chat-bubble-user {
  align-self: flex-end;
  background: #007aff;
  color: #fff;
  padding: 10px 14px;
  border-radius: 16px 16px 4px 16px;
  max-width: 78%;
  word-break: break-word;
  font-size: 14px;
  line-height: 1.5;
  margin: 4px 12px 4px auto;
}

.boss-chat-bubble-ai {
  align-self: flex-start;
  background: #fff;
  color: #000;
  padding: 10px 14px;
  border-radius: 16px 16px 16px 4px;
  max-width: 88%;
  word-break: break-word;
  font-size: 14px;
  line-height: 1.5;
  margin: 4px auto 4px 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

/* 对话内表格水平滚动 */
.boss-chat-bubble-ai table {
  display: block;
  overflow-x: auto;
  white-space: nowrap;
  margin: 8px 0;
  border-collapse: collapse;
}

.boss-chat-bubble-ai th,
.boss-chat-bubble-ai td {
  border: 1px solid #e5e5ea;
  padding: 6px 10px;
  font-size: 13px;
  text-align: left;
}

/* 对话内可点击 chip（发票号/报销单号） */
.boss-chip {
  display: inline-block;
  padding: 2px 8px;
  margin: 0 2px;
  background: #e8f2ff;
  color: #007aff;
  border-radius: 10px;
  font-size: 13px;
  cursor: pointer;
  text-decoration: none;
}

.boss-chip:active {
  background: #cce3ff;
}

/* 详情页字段卡 */
.boss-field-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f4;
  font-size: 14px;
}

.boss-field-row:last-child {
  border-bottom: none;
}

.boss-field-row__label {
  color: #8e8e93;
  flex-shrink: 0;
  margin-right: 12px;
}

.boss-field-row__value {
  color: #000;
  text-align: right;
  word-break: break-word;
  flex: 1;
}

/* 状态徽章（复用 StatusBadge 也可，这里给个兜底） */
.boss-status {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
}

.boss-status--confirmed { background: #e8f7ec; color: #2c8a3e; }
.boss-status--reviewing { background: #fff4d6; color: #b8860b; }
.boss-status--invalid   { background: #ffe1e1; color: #c00; }
.boss-status--reimbursed { background: #e8f2ff; color: #007aff; }

/* 输入框 + 发送按钮 */
.boss-chat-input-bar {
  position: sticky;
  bottom: 56px; /* Tab Bar 高度 */
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  background: #fff;
  border-top: 1px solid #e5e5ea;
}

.boss-chat-input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid #e5e5ea;
  border-radius: 20px;
  font-size: 14px;
  outline: none;
}

.boss-chat-input:focus {
  border-color: #007aff;
}

.boss-send-btn {
  background: #007aff;
  color: #fff;
  border: none;
  border-radius: 20px;
  padding: 0 18px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.boss-send-btn:disabled {
  background: #b8d4ff;
  cursor: not-allowed;
}

/* 筛选条 */
.boss-filter-bar {
  display: flex;
  gap: 6px;
  padding: 8px 12px;
  background: #fff;
  border-bottom: 1px solid #e5e5ea;
  overflow-x: auto;
  white-space: nowrap;
}

.boss-filter-chip {
  padding: 4px 12px;
  border-radius: 14px;
  background: #f5f5f7;
  color: #8e8e93;
  font-size: 13px;
  border: none;
  cursor: pointer;
}

.boss-filter-chip--active {
  background: #007aff;
  color: #fff;
}
```

- [ ] **Step 4: 修改 `frontend/src/App.tsx` 加 `/boss/*` 路由**

第 20 行后追加 import（在 portal imports 之后）：

```tsx
import { PortalProfile } from "./pages/portal/Profile";
import { BossProtected } from "./components/BossProtected";
import { BossLayout } from "./components/BossLayout";
import { BossLogin } from "./pages/boss/Login";
import { BossChat } from "./pages/boss/Chat";
import { BossInvoiceList } from "./pages/boss/InvoiceList";
import { BossInvoiceDetail } from "./pages/boss/InvoiceDetail";
import { BossReimbursementList } from "./pages/boss/ReimbursementList";
import { BossReimbursementDetail } from "./pages/boss/ReimbursementDetail";
```

`App()` 函数内，第 39 行 `const isPortal = location.pathname.startsWith("/portal");` 后追加：

```tsx
  const isPortal = location.pathname.startsWith("/portal");
  const isBoss = location.pathname.startsWith("/boss");
```

return 部分，在 `isPortal ? (...)` 三元后追加 boss 分支（结构上：

```tsx
  return (
    <>
      {isPortal ? (
        <AnimatePresence mode="wait">
          {/* ... 现有 portal 内容 ... */}
        </AnimatePresence>
      ) : isBoss ? (
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ type: "spring", stiffness: 200, damping: 25 }}
          >
            <Routes location={location}>
              <Route path="/boss/login" element={<BossLogin />} />
              <Route element={<BossProtected />}>
                <Route element={<BossLayout />}>
                  <Route path="/boss" element={<BossChat />} />
                  <Route path="/boss/chat" element={<BossChat />} />
                  <Route path="/boss/invoices" element={<BossInvoiceList />} />
                  <Route path="/boss/invoices/:id" element={<BossInvoiceDetail />} />
                  <Route path="/boss/reimbursements" element={<BossReimbursementList />} />
                  <Route path="/boss/reimbursements/:id" element={<BossReimbursementDetail />} />
                </Route>
              </Route>
            </Routes>
          </motion.div>
        </AnimatePresence>
      ) : (
        /* ... 现有 admin 内容 ... */
      )}
    </>
  );
```

完整改法是把现有 `return (<> {isPortal ? (...) : (...)} </>)` 改成三元嵌套：`isPortal ? (...) : isBoss ? (...) : (...)`。

- [ ] **Step 5: 创建 5 个 boss 页面占位（确保编译通过）**

为防止 Task 4 编译失败，先创建 5 个最简页面（Task 5 再填充内容）：

`frontend/src/pages/boss/Login.tsx`:
```tsx
export function BossLogin() {
  return <div className="boss-empty">Boss Login - 占位</div>;
}
```

`frontend/src/pages/boss/Chat.tsx`:
```tsx
export function BossChat() {
  return <div className="boss-empty">Boss Chat - 占位</div>;
}
```

`frontend/src/pages/boss/InvoiceList.tsx`:
```tsx
export function BossInvoiceList() {
  return <div className="boss-empty">Boss Invoice List - 占位</div>;
}
```

`frontend/src/pages/boss/InvoiceDetail.tsx`:
```tsx
export function BossInvoiceDetail() {
  return <div className="boss-empty">Boss Invoice Detail - 占位</div>;
}
```

`frontend/src/pages/boss/ReimbursementList.tsx`:
```tsx
export function BossReimbursementList() {
  return <div className="boss-empty">Boss Reimbursement List - 占位</div>;
}
```

`frontend/src/pages/boss/ReimbursementDetail.tsx`:
```tsx
export function BossReimbursementDetail() {
  return <div className="boss-empty">Boss Reimbursement Detail - 占位</div>;
}
```

- [ ] **Step 6: 验证 TypeScript 编译 + dev server 启动**

Run:
```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```
Expected: 无报错。

Run:
```bash
cd frontend && npm run dev &
sleep 4
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/boss/login
kill %1 2>/dev/null
```
Expected: 200。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/BossProtected.tsx frontend/src/components/BossLayout.tsx frontend/src/App.tsx frontend/src/index.css frontend/src/pages/boss/
git commit -m "feat(boss): 路由守卫 + 移动端 Tab 布局 + 占位页面"
```

---

## Task 5：填充 5 个 Boss 页面

**Files:**
- Modify: `frontend/src/pages/boss/Login.tsx`
- Modify: `frontend/src/pages/boss/Chat.tsx`
- Modify: `frontend/src/pages/boss/InvoiceList.tsx`
- Modify: `frontend/src/pages/boss/InvoiceDetail.tsx`
- Modify: `frontend/src/pages/boss/ReimbursementList.tsx`
- Modify: `frontend/src/pages/boss/ReimbursementDetail.tsx`

**Interfaces:**
- Consumes: `bossApi` from Task 3
- Consumes: `<BossLayout>` from Task 4（页面渲染在 BossLayout 的 `<Outlet />` 内）

- [ ] **Step 1: 实现 `Login.tsx`**

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";

export function BossLogin() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await bossApi.login(username, password);
      navigate("/boss/chat", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="boss-shell" style={{ justifyContent: "center", padding: "24px" }}>
      <div style={{ textAlign: "center", marginBottom: 32 }}>
        <div style={{ fontSize: 48 }}>👔</div>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: "12px 0 4px" }}>老板端</h1>
        <p style={{ fontSize: 13, color: "#8e8e93", margin: 0 }}>全公司数据 · 智能问数</p>
      </div>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input
          className="boss-chat-input"
          style={{ borderRadius: 12, padding: "14px" }}
          type="text"
          placeholder="账号"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
        <input
          className="boss-chat-input"
          style={{ borderRadius: 12, padding: "14px" }}
          type="password"
          placeholder="密码"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
        {error && <div className="boss-error">{error}</div>}
        <button
          type="submit"
          className="boss-send-btn"
          style={{ borderRadius: 12, padding: "14px", fontSize: 16 }}
          disabled={loading || !username || !password}
        >
          {loading ? "登录中…" : "登录"}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: 实现 `Chat.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { DialogAPIResponse } from "../../types";

interface Message {
  role: "user" | "ai";
  text: string;
  html?: string;
}

/**
 * 把对话返回文本中的「#477」「报销单#12」等模式渲染为可点击 chip
 * 后端 insight 引擎返回格式参考：「发票 #477 已确认」「报销单 #12 待审批」
 */
function renderTextWithChips(text: string, navigate: (path: string) => void): string {
  // 发票 #123 或 发票#123 或 #INV123
  const html = text
    .replace(/发票\s*#?(\d+)/g, (_, id) => `<a class="boss-chip" data-invoice-id="${id}">发票 #${id}</a>`)
    .replace(/报销单\s*#?(\d+)/g, (_, id) => `<a class="boss-chip" data-reimbursement-id="${id}">报销单 #${id}</a>`);
  return html;
}

export function BossChat() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 欢迎语
  useEffect(() => {
    setMessages([
      {
        role: "ai",
        text: "您好，请直接问我公司报销情况。\n\n例如：\n• 本月各部门发票总额？\n• 陈辉有几张待审报销单？\n• 本季度哪些发票异常？",
      },
    ]);
  }, []);

  // 自动滚到底
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // 处理 chip 点击（事件委托）
  const handleClickChip = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.classList.contains("boss-chip")) {
      const invId = target.getAttribute("data-invoice-id");
      const reimbId = target.getAttribute("data-reimbursement-id");
      if (invId) navigate(`/boss/invoices/${invId}`);
      if (reimbId) navigate(`/boss/reimbursements/${reimbId}`);
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setLoading(true);
    setMessages((prev) => [...prev, { role: "user", text }]);
    try {
      const resp: DialogAPIResponse = await bossApi.sendMessage({ text });
      const aiText = resp.error ? `⚠️ ${resp.error}` : resp.text;
      setMessages((prev) => [...prev, { role: "ai", text: aiText, html: renderTextWithChips(aiText, navigate) }]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "ai", text: `⚠️ ${err instanceof Error ? err.message : "AI 服务暂时不可用，请稍后重试"}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    try {
      await bossApi.resetDialog();
      setMessages([{ role: "ai", text: "对话已重置，请继续提问。" }]);
    } catch (err) {
      // 静默失败
    }
  };

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", background: "#fff", borderBottom: "1px solid #e5e5ea" }}>
        <h1 style={{ fontSize: 17, fontWeight: 600, margin: 0 }}>老板智能问数</h1>
        <button onClick={handleReset} className="boss-back-btn" style={{ fontSize: 13, padding: "4px 8px" }} title="重置对话">
          🔄
        </button>
      </div>
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "8px 0" }} onClick={handleClickChip}>
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="boss-chat-bubble-user">{m.text}</div>
          ) : (
            <div
              key={i}
              className="boss-chat-bubble-ai"
              dangerouslySetInnerHTML={{ __html: m.html || m.text.replace(/\n/g, "<br>") }}
            />
          )
        )}
        {loading && <div className="boss-chat-bubble-ai" style={{ color: "#8e8e93" }}>思考中…</div>}
      </div>
      <div className="boss-chat-input-bar">
        <input
          className="boss-chat-input"
          type="text"
          placeholder="问点什么…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          disabled={loading}
        />
        <button className="boss-send-btn" onClick={handleSend} disabled={loading || !input.trim()}>
          发送
        </button>
      </div>
    </>
  );
}
```

- [ ] **Step 3: 实现 `InvoiceList.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { Invoice } from "../../types";

const STATUS_FILTERS = [
  { label: "全部", value: "" },
  { label: "已确认", value: "confirmed" },
  { label: "待复核", value: "reviewing" },
  { label: "已报销", value: "reimbursed" },
];

export function BossInvoiceList() {
  const navigate = useNavigate();
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    (async () => {
      setError("");
      try {
        const data = await bossApi.listInvoices(status ? { status } : undefined);
        setInvoices(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载失败");
        setInvoices([]);
      }
    })();
  }, [status]);

  return (
    <>
      <h1 className="boss-page-title">发票（全公司）</h1>
      <div className="boss-filter-bar">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            className={`boss-filter-chip ${status === f.value ? "boss-filter-chip--active" : ""}`}
            onClick={() => setStatus(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>
      {error && <div className="boss-error">{error}</div>}
      {invoices === null ? (
        <div className="boss-loading">加载中…</div>
      ) : invoices.length === 0 ? (
        <div className="boss-empty">暂无发票</div>
      ) : (
        invoices.map((inv) => (
          <div
            key={inv.id}
            className="boss-card boss-card--clickable"
            onClick={() => navigate(`/boss/invoices/${inv.id}`)}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 500, color: "#000", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {inv.seller_name || "(无销售方)"}
                </div>
                <div style={{ fontSize: 12, color: "#8e8e93", marginTop: 4 }}>
                  {inv.issue_date || "—"} · #{inv.invoice_number?.slice(-8) || inv.id}
                </div>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <div style={{ fontSize: 16, fontWeight: 600, color: "#000" }}>¥{inv.total_with_tax || "0"}</div>
                <div style={{ fontSize: 11, color: "#8e8e93", marginTop: 2 }}>{inv.status}</div>
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}
```

- [ ] **Step 4: 实现 `InvoiceDetail.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { InvoiceDetail } from "../../types";

export function BossInvoiceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    (async () => {
      setError("");
      try {
        const data = await bossApi.invoiceDetail(Number(id));
        setInv(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载失败");
      }
    })();
  }, [id]);

  if (error) return (
    <>
      <button className="boss-back-btn" onClick={() => navigate(-1)}>←</button>
      <div className="boss-error">{error}</div>
    </>
  );
  if (!inv) return <div className="boss-loading">加载中…</div>;

  const fields: [string, any][] = [
    ["发票号码", inv.invoice_number],
    ["开票日期", inv.issue_date],
    ["销售方", inv.seller_name],
    ["销售方税号", inv.seller_tax_id],
    ["购买方", inv.buyer_name],
    ["购买方税号", inv.buyer_tax_id],
    ["价税合计", inv.total_with_tax ? `¥${inv.total_with_tax}` : null],
    ["不含税金额", inv.amount],
    ["税额", inv.tax_amount],
    ["税率", inv.tax_rate],
    ["项目名称", inv.item_name],
    ["用户描述", inv.user_description],
  ];

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", background: "#fff", borderBottom: "1px solid #e5e5ea" }}>
        <button className="boss-back-btn" onClick={() => navigate(-1)}>←</button>
        <h1 style={{ fontSize: 17, fontWeight: 600, margin: 0, padding: "14px 0" }}>发票详情</h1>
      </div>
      <div className="boss-card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <span style={{ fontSize: 13, color: "#8e8e93" }}>#{inv.id}</span>
          <span className={`boss-status boss-status--${inv.status}`}>{inv.status}</span>
        </div>
        {fields.map(([label, value]) => (
          <div key={label} className="boss-field-row">
            <span className="boss-field-row__label">{label}</span>
            <span className="boss-field-row__value">{value || "—"}</span>
          </div>
        ))}
      </div>

      {inv.reimbursement_id && (
        <div
          className="boss-card boss-card--clickable"
          onClick={() => navigate(`/boss/reimbursements/${inv.reimbursement_id}`)}
        >
          <div style={{ fontSize: 13, color: "#8e8e93" }}>所属报销单</div>
          <div style={{ fontSize: 15, color: "#007aff", marginTop: 4 }}>报销单 #{inv.reimbursement_id} →</div>
        </div>
      )}

      <div className="boss-card">
        <div style={{ fontSize: 13, color: "#8e8e93", marginBottom: 8 }}>原始发票</div>
        <a
          href={bossApi.invoiceFileUrl(inv.id)}
          target="_blank"
          rel="noreferrer"
          className="boss-chip"
          style={{ display: "inline-block", padding: "8px 14px" }}
        >
          📎 查看原始文件
        </a>
      </div>
    </>
  );
}
```

- [ ] **Step 5: 实现 `ReimbursementList.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { Reimbursement } from "../../types";

const STATUS_FILTERS = [
  { label: "全部", value: "" },
  { label: "待审批", value: "pending" },
  { label: "已批准", value: "approved" },
  { label: "已拒绝", value: "rejected" },
  { label: "已报销", value: "reimbursed" },
];

export function BossReimbursementList() {
  const navigate = useNavigate();
  const [items, setItems] = useState<Reimbursement[] | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    (async () => {
      setError("");
      try {
        const data = await bossApi.listReimbursements();
        // 前端按状态过滤（后端 list 不接受 status 参数时）
        const filtered = status ? data.filter((r) => r.status === status) : data;
        setItems(filtered);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载失败");
        setItems([]);
      }
    })();
  }, [status]);

  return (
    <>
      <h1 className="boss-page-title">报销单（全公司）</h1>
      <div className="boss-filter-bar">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            className={`boss-filter-chip ${status === f.value ? "boss-filter-chip--active" : ""}`}
            onClick={() => setStatus(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>
      {error && <div className="boss-error">{error}</div>}
      {items === null ? (
        <div className="boss-loading">加载中…</div>
      ) : items.length === 0 ? (
        <div className="boss-empty">暂无报销单</div>
      ) : (
        items.map((r) => (
          <div
            key={r.id}
            className="boss-card boss-card--clickable"
            onClick={() => navigate(`/boss/reimbursements/${r.id}`)}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 500 }}>
                  报销单 #{r.id}
                </div>
                <div style={{ fontSize: 12, color: "#8e8e93", marginTop: 4 }}>
                  {r.applicant_id || "—"} · {r.period || ""}
                </div>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <div style={{ fontSize: 16, fontWeight: 600 }}>¥{r.total_amount || "0"}</div>
                <div style={{ fontSize: 11, color: "#8e8e93", marginTop: 2 }}>{r.status}</div>
              </div>
            </div>
          </div>
        ))
      )}
    </>
  );
}
```

- [ ] **Step 6: 实现 `ReimbursementDetail.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { bossApi } from "../../api/client";
import type { Reimbursement } from "../../types";

export function BossReimbursementDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [r, setR] = useState<Reimbursement | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    (async () => {
      setError("");
      try {
        const data = await bossApi.reimbursementDetail(Number(id));
        setR(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载失败");
      }
    })();
  }, [id]);

  if (error) return (
    <>
      <button className="boss-back-btn" onClick={() => navigate(-1)}>←</button>
      <div className="boss-error">{error}</div>
    </>
  );
  if (!r) return <div className="boss-loading">加载中…</div>;

  const fields: [string, any][] = [
    ["报销单号", `#${r.id}`],
    ["申请人", r.applicant_id],
    ["周期", r.period],
    ["总金额", r.total_amount ? `¥${r.total_amount}` : null],
    ["状态", r.status],
    ["申请理由", r.reason],
    ["创建时间", r.created_at],
  ];

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", background: "#fff", borderBottom: "1px solid #e5e5ea" }}>
        <button className="boss-back-btn" onClick={() => navigate(-1)}>←</button>
        <h1 style={{ fontSize: 17, fontWeight: 600, margin: 0, padding: "14px 0" }}>报销单详情</h1>
      </div>
      <div className="boss-card">
        {fields.map(([label, value]) => (
          <div key={label} className="boss-field-row">
            <span className="boss-field-row__label">{label}</span>
            <span className="boss-field-row__value">{value || "—"}</span>
          </div>
        ))}
      </div>

      {r.invoice_ids && r.invoice_ids.length > 0 && (
        <div className="boss-card">
          <div style={{ fontSize: 13, color: "#8e8e93", marginBottom: 8 }}>关联发票（{r.invoice_ids.length}）</div>
          {r.invoice_ids.map((invId) => (
            <div
              key={invId}
              className="boss-card--clickable"
              style={{ padding: "10px 0", borderBottom: "1px solid #f0f0f4" }}
              onClick={() => navigate(`/boss/invoices/${invId}`)}
            >
              <span style={{ color: "#007aff" }}>发票 #{invId} →</span>
            </div>
          ))}
        </div>
      )}

      <div className="boss-card">
        <div style={{ fontSize: 13, color: "#8e8e93", marginBottom: 8 }}>报表</div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="boss-filter-chip" onClick={() => bossApi.downloadReport(r.id, "excel").catch(() => {})}>
            📊 下载 Excel
          </button>
          <button className="boss-filter-chip" onClick={() => bossApi.downloadReport(r.id, "pdf").catch(() => {})}>
            📄 下载 PDF
          </button>
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 7: 验证 TypeScript 编译**

Run:
```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```
Expected: 无报错。如果有 `Reimbursement.invoice_ids` 类型不存在的错误，检查 `frontend/src/types.ts` 中 `Reimbursement` 类型定义——若实际 API 返回的是关联发票数组，可能字段名是 `invoices` 或 `item_count` 等，按实际类型修正。

- [ ] **Step 8: 启动 dev server 手动验证**

Run:
```bash
cd frontend && npm run dev &
sleep 4
echo "请用浏览器访问 http://localhost:5173/boss/login"
```

手动验证清单（写在 commit message 末尾）：
1. 访问 `/boss/login` → 输入 `zhang/zhang` → 跳 `/boss/chat` ✅
2. 输入「本月发票总额」→ AI 返回文本 ✅
3. 底部 Tab 切到「发票」→ 列表加载 ✅
4. 点发票卡片 → 详情页 ✅
5. 切「报销单」Tab → 列表 ✅
6. 点报销单卡片 → 详情 → 点关联发票 → 跳发票详情 ✅

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/boss/
git commit -m "feat(boss): 实现 5 个移动端页面（登录/问数/发票列表+详情/报销单列表+详情）"
```

---

## Task 6：端到端验证脚本 + 最终回归

**Files:**
- Create: `backend/scripts/e2e_boss_test.py`

- [ ] **Step 1: 创建 `backend/scripts/e2e_boss_test.py`**

```python
"""BOSS 端端到端验证脚本

验证：
1. 登录拿 token
2. 读发票列表
3. 读报销单列表
4. 读员工列表
5. 调对话问数
6. 写端点拒绝（403）
"""

import json
import sys
import requests

BASE = "http://localhost:18080"

def main():
    # 1. 登录
    print("== 1. 登录 ==")
    resp = requests.post(f"{BASE}/api/boss/auth/login", json={"username": "zhang", "password": "zhang"})
    assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    print(f"   ✓ token len={len(token)}")
    headers = {"Authorization": f"Bearer {token}"}

    # 2. 读发票列表
    print("== 2. GET /api/invoices ==")
    resp = requests.get(f"{BASE}/api/invoices", headers=headers)
    assert resp.status_code == 200, f"读发票失败: {resp.status_code} {resp.text}"
    print(f"   ✓ 发票数={len(resp.json())}")

    # 3. 读报销单列表
    print("== 3. GET /api/reimbursements ==")
    resp = requests.get(f"{BASE}/api/reimbursements", headers=headers)
    assert resp.status_code == 200, f"读报销单失败: {resp.status_code} {resp.text}"
    print(f"   ✓ 报销单数={len(resp.json())}")

    # 4. 读员工列表
    print("== 4. GET /api/employees ==")
    resp = requests.get(f"{BASE}/api/employees", headers=headers)
    assert resp.status_code == 200, f"读员工失败: {resp.status_code} {resp.text}"
    print(f"   ✓ 员工数={len(resp.json())}")

    # 5. 调对话
    print("== 5. POST /api/dialog/message (role=boss) ==")
    resp = requests.post(
        f"{BASE}/api/dialog/message",
        json={"user_id": "zhang", "text": "本月发票总额", "role": "boss"},
        headers={**headers, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, f"对话失败: {resp.status_code} {resp.text}"
    body = resp.json()
    print(f"   ✓ text={body.get('text', '')[:80]}")

    # 6. 写端点拒绝
    print("== 6. DELETE /api/invoices/9999 (应 403) ==")
    resp = requests.delete(f"{BASE}/api/invoices/9999", headers=headers)
    assert resp.status_code == 403, f"应该 403 但返回 {resp.status_code}"
    print("   ✓ 403 拒绝")

    print("\n所有验证通过 ✓")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行 E2E 验证**

Run:
```bash
docker cp backend/scripts/e2e_boss_test.py ai-reimbursement-agent-backend-1:/app/scripts/e2e_boss_test.py
docker exec ai-reimbursement-agent-backend-1 python3 /app/scripts/e2e_boss_test.py
```
Expected: 输出 6 个 ✓，最后 `所有验证通过 ✓`。

- [ ] **Step 3: 后端测试全量回归**

Run:
```bash
docker exec ai-reimbursement-agent-backend-1 python -m pytest tests/test_boss_auth.py -v
```
Expected: 12 个测试 PASS。

- [ ] **Step 4: 管理端 + 员工端回归验证**

Run:
```bash
# Admin 登录
curl -s -X POST http://localhost:18080/api/admin/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"123456"}' | head -c 100
echo
# 员工端登录
curl -s -X POST http://localhost:18080/api/portal/auth/login -H "Content-Type: application/json" -d '{"employee_no":"EMP001","password":"123456"}' | head -c 100
```
Expected: 两个登录都返回 `access_token`，admin 端 + 员工端不受影响。

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/e2e_boss_test.py
git commit -m "test(boss): 端到端验证脚本 + 回归测试"
```

---

## Self-Review 检查清单

执行完所有任务后，逐项验证：

- [ ] 后端 `/api/boss/auth/login` 用 `zhang/zhang` 返回 200 + token
- [ ] 后端 `/api/boss/auth/login` 用错误密码返回 401
- [ ] 后端 BOSS token 调 GET `/api/invoices` 返回 200
- [ ] 后端 BOSS token 调 DELETE `/api/invoices/{id}` 返回 403
- [ ] 后端 BOSS token 调 POST `/api/dialog/message` (role=boss) 返回 200
- [ ] 后端 admin token 调写端点仍 200（admin 权限不受影响）
- [ ] 后端 `pytest tests/test_boss_auth.py` 12 个测试全 PASS
- [ ] 前端 `/boss/login` 可访问，输入 `zhang/zhang` 跳 `/boss/chat`
- [ ] 前端 `/boss/chat` 输入「本月发票总额」返回 AI 文本回复
- [ ] 前端 `/boss/invoices` 列表加载，状态筛选可用
- [ ] 前端 `/boss/invoices/:id` 详情页字段正确显示
- [ ] 前端 `/boss/reimbursements` 列表加载
- [ ] 前端 `/boss/reimbursements/:id` 详情页可点关联发票跳详情
- [ ] 前端底部 Tab 在列表/对话页显示，在详情页隐藏
- [ ] 前端 `/admin/login` + `/portal/login` 不受影响
- [ ] iPhone Safari / Android Chrome 访问 `/boss/login` 移动端布局正常

## 完成后交付

1. 所有 commit 已推送到 `develop/v2` 分支
2. spec 文档 `docs/superpowers/specs/2026-08-17-boss-portal-design.md` 已存在
3. 本计划文档 `docs/superpowers/plans/2026-08-17-boss-portal.md` 已存在
4. `backend/scripts/e2e_boss_test.py` 可独立运行验证
