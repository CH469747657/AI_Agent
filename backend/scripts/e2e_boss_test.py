"""老板端 E2E 验证脚本

用法：
    docker exec ai-reimbursement-agent-backend-1 python /app/scripts/e2e_boss_test.py

或本机直接跑（依赖 backend 容器在 18080 端口监听）：
    python backend/scripts/e2e_boss_test.py

验证项：
1. zhang/zhang 登录 → 拿到 token + role=boss
2. GET /api/invoices → 200 + 列表（穿透全公司）
3. GET /api/reimbursements → 200 + 列表
4. GET /api/employees → 200
5. GET /api/projects → 200
6. POST /api/dialog/message → 200 + 返回文本
7. DELETE /api/invoices/{id} → 403（写端点被拒）
8. PUT /api/reimbursements/{id}/approve → 403
9. POST /api/admin/auth/change-password → 403（admin 写端点拒 BOSS token）
"""

import sys
import json
import urllib.request
import urllib.error

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
    print("BOSS 端 E2E 验证")
    print("=" * 60)

    # 1. 登录
    code, body = req("POST", "/api/boss/auth/login", {"username": "zhang", "password": "zhang"})
    assert code == 200, f"[FAIL] 登录期望 200，实际 {code}：{body}"
    token = body["access_token"]
    assert body["profile"]["role"] == "boss"
    print(f"[OK] 1. 登录成功，role=boss")

    # 2. 发票列表
    code, body = req("GET", "/api/invoices", token=token)
    assert code == 200, f"[FAIL] GET /invoices 期望 200，实际 {code}：{body}"
    print(f"[OK] 2. GET /invoices → 200，{len(body)} 行")

    # 3. 报销单列表
    code, body = req("GET", "/api/reimbursements", token=token)
    assert code == 200, f"[FAIL] GET /reimbursements 期望 200，实际 {code}：{body}"
    print(f"[OK] 3. GET /reimbursements → 200，{len(body)} 行")

    # 4. 员工列表
    code, body = req("GET", "/api/employees", token=token)
    assert code == 200, f"[FAIL] GET /employees 期望 200，实际 {code}：{body}"
    print(f"[OK] 4. GET /employees → 200，{len(body)} 行")

    # 5. 项目列表
    code, body = req("GET", "/api/projects", token=token)
    assert code == 200, f"[FAIL] GET /projects 期望 200，实际 {code}：{body}"
    print(f"[OK] 5. GET /projects → 200，{len(body)} 行")

    # 6. 问数
    code, body = req(
        "POST",
        "/api/dialog/message",
        {"message": "公司本月发票总额是多少", "role": "boss", "user_id": "zhang"},
        token=token,
    )
    assert code == 200, f"[FAIL] POST /dialog/message 期望 200，实际 {code}：{body}"
    text = body.get("text") or ""
    print(f"[OK] 6. POST /dialog/message → 200，text 长度 {len(text)}")

    # 7. 删除发票 → 403
    code, _ = req("DELETE", "/api/invoices/9999", token=token)
    assert code == 403, f"[FAIL] DELETE /invoices/9999 期望 403，实际 {code}"
    print(f"[OK] 7. DELETE /invoices/9999 → 403")

    # 8. 审批报销单 → 403
    code, _ = req("PUT", "/api/reimbursements/9999/approve", token=token)
    assert code == 403, f"[FAIL] PUT /reimbursements/9999/approve 期望 403，实际 {code}"
    print(f"[OK] 8. PUT /reimbursements/9999/approve → 403")

    # 9. admin 改密 → 403
    code, _ = req(
        "POST",
        "/api/admin/auth/change-password",
        {"old_password": "zhang", "new_password": "newpass123"},
        token=token,
    )
    assert code == 403, f"[FAIL] POST /admin/auth/change-password 期望 403，实际 {code}"
    print(f"[OK] 9. POST /admin/auth/change-password → 403")

    print("=" * 60)
    print("✓ 全部 9 项 BOSS E2E 验证通过")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n✗ {e}", file=sys.stderr)
        sys.exit(1)
