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
