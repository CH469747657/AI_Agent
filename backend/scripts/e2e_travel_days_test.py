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

# 容器内执行时让 /app 模块可被导入（用于 _reset_cycle_unlock 直接改 DB）
for _p in ("/app",):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 容器内 backend 监听 8080，本机走 docker 映射的 18080
def _detect_base() -> str:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", 8080))
            return "http://127.0.0.1:8080"
        except OSError:
            pass
    finally:
        try:
            s.close()
        except Exception:
            pass
    return "http://127.0.0.1:18080"

BASE = _detect_base()


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


def _reset_cycle_unlock():
    """E2E 前重置 EMP001 当前周期报销单的封账标志（避免上轮测试残留）

    优先在 backend 容器内跑（用 app 模块），失败则尝试直连 DB
    """
    import asyncio
    import os
    from app.services.cycle_engine import current_cycle_key
    from app.database import get_async_sessionmaker
    from app.models.reimbursement import Reimbursement
    from sqlalchemy import select, update

    async def _do():
        async with get_async_sessionmaker()() as db:
            ck = current_cycle_key(date.today())
            await db.execute(
                update(Reimbursement)
                .where(Reimbursement.applicant_id == "EMP001")
                .where(Reimbursement.cycle_key == ck)
                .values(is_cycle_locked=False, locked_at=None)
            )
            await db.commit()

    try:
        asyncio.run(_do())
    except Exception as e:
        print(f"  [warn] reset cycle lock 失败（忽略）：{e}", file=sys.stderr)


def main():
    print("=" * 60)
    print("出差日 E2E 验证")
    print("=" * 60)

    # 0. 重置封账标志（防止上轮测试残留封账状态导致后续 POST 409）
    _reset_cycle_unlock()

    # 1. 员工登录
    code, body = req(
        "POST", "/api/portal/auth/login",
        {"employee_no": "EMP001", "password": "123456"},
    )
    assert code == 200, f"[FAIL] 员工登录 期望 200，实际 {code}：{body}"
    emp_token = body["access_token"]
    print("[OK] 1. 员工登录成功")

    # 2. 拿当前周期内一个日期
    today = date.today()
    test_date = today
    d = test_date.isoformat()
    print(f"  测试日期: {d}")

    # 3. 标记
    code, body = req(
        "POST", "/api/portal/travel-days",
        {"travel_date": d, "note": "E2E 测试"},
        token=emp_token,
    )
    assert code == 200, f"[FAIL] 标记出差日 期望 200，实际 {code}：{body}"
    assert body["travel_date"] == d
    print(f"[OK] 2. 标记出差日 {d}")

    # 4. 重复标记
    code, body = req(
        "POST", "/api/portal/travel-days",
        {"travel_date": d, "note": None},
        token=emp_token,
    )
    assert code == 409, f"[FAIL] 重复标记 期望 409，实际 {code}"
    print("[OK] 3. 重复标记 → 409")

    # 5. 标记周期外
    code, _ = req(
        "POST", "/api/portal/travel-days",
        {"travel_date": "1999-01-01", "note": None},
        token=emp_token,
    )
    assert code == 400, f"[FAIL] 周期外 期望 400，实际 {code}"
    print("[OK] 4. 周期外日期 → 400")

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
    assert any(td["travel_date"] == d for td in detail.get("travel_days", [])), \
        "travel_days 缺少已标日期"
    assert detail["subsidy_total"] > 0, f"subsidy_total 应>0，实际 {detail['subsidy_total']}"
    subsidy_before = detail["subsidy_total"]
    print(f"[OK] 6. 报销单详情 → travel_days 含 {d}, subsidy_total={subsidy_before}")

    # 8. DELETE by date
    code, body = req("DELETE", f"/api/portal/travel-days/by-date/{d}", token=emp_token)
    assert code == 200, f"[FAIL] 删除 期望 200，实际 {code}"
    print("[OK] 7. DELETE by date → 200")

    # 9. 验证 subsidy_total 减少
    code, detail = req("GET", f"/api/portal/reimbursements/{reimb_id}", token=emp_token)
    assert code == 200
    assert detail["subsidy_total"] < subsidy_before, \
        f"subsidy_total 应减少，{subsidy_before} → {detail['subsidy_total']}"
    print(f"[OK] 8. subsidy_total {subsidy_before} → {detail['subsidy_total']}")

    # 10. admin GET
    code, body = req(
        "POST", "/api/admin/auth/login",
        {"username": "admin", "password": "123456"},
    )
    admin_token = body["access_token"]
    code, body = req(
        "GET", f"/api/admin/travel-days?reimbursement_id={reimb_id}",
        token=admin_token,
    )
    assert code == 200, f"[FAIL] admin GET 期望 200，实际 {code}"
    print("[OK] 9. admin GET /api/admin/travel-days → 200")

    # 11. boss POST → 401/403
    code, body = req(
        "POST", "/api/boss/auth/login",
        {"username": "zhang", "password": "zhang"},
    )
    boss_token = body["access_token"]
    code, _ = req(
        "POST", "/api/portal/travel-days",
        {"travel_date": d, "note": None},
        token=boss_token,
    )
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
