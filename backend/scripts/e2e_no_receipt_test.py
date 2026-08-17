"""无凭证报销对话指令测试

测试目的：验证员工在对话框输入指令发起无凭证报销的覆盖范围

测试用例：
- 正常示例：金额 + 用途清晰
- 反向异常：缺金额 / 缺用途 / 金额负数 / 金额非数字 / 用途过短 / 文本含异常字符
"""

import sys
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:18080"


def req(method, path, body=None, token=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "null")
        except json.JSONDecodeError:
            return e.code, None


def login(employee_no="EMP001", password="123456"):
    code, body = req("POST", "/api/portal/auth/login",
                     {"employee_no": employee_no, "password": password})
    assert code == 200, f"登录失败: {code} {body}"
    return body["access_token"]


def send_dialog(token, user_id, text):
    return req("POST", "/api/portal/dialog/message",
               {"user_id": user_id, "text": text}, token=token)


def print_case(idx, desc, text_input, expect_pass):
    print(f"\n--- 用例 {idx}：{desc}")
    print(f"  输入：{text_input!r}")
    print(f"  期望：{'成功创建' if expect_pass else '拒绝/追问'}")


def main():
    print("=" * 60)
    print("无凭证报销对话指令测试")
    print("=" * 60)

    token = login("EMP001", "123456")
    print("[OK] 陈辉 (EMP001) 登录成功")

    cases = [
        # === 正常示例 ===
        (1, "正常-简单金额+用途", "无凭证报销 120 元打车费", True),
        (2, "正常-完整句子", "我有一笔 350 元的客户招待餐费需要无票报销", True),
        (3, "正常-含小数", "无票报销 88.5 元办公文具采购", True),
        (4, "正常-用途详细", "无票报销 200 元，用途是出差打车（机场往返）", True),
        (5, "正常-含币种符号", "无凭证报销 ¥150 培训资料打印费", True),

        # === 反向异常：缺金额 ===
        (6, "异常-缺金额", "无凭证报销打车费", False),
        (7, "异常-只说无票", "我没有发票想报销", False),

        # === 反向异常：缺用途 ===
        (8, "异常-缺用途", "无凭证报销 120 元", False),
        (9, "异常-只金额", "无票 500", False),

        # === 反向异常：金额非法 ===
        (10, "异常-金额为负", "无凭证报销 -100 元打车费", False),
        (11, "异常-金额非数字", "无凭证报销 abc 元打车费", False),
        (12, "异常-金额为零", "无凭证报销 0 元打车费", False),
        (13, "异常-金额过大", "无凭证报销 999999 元打车费", False),

        # === 反向异常：用途异常 ===
        (14, "异常-用途过短", "无凭证报销 100 元 x", False),
        (15, "异常-用途乱码", "无凭证报销 100 元 ???!!!", False),

        # === 边界 ===
        (16, "正常-最小金额", "无凭证报销 1 元打印费", True),
        (17, "正常-较大金额合理", "无凭证报销 5000 元员工培训住宿费", True),
    ]

    results = []
    for idx, desc, text_input, expect_pass in cases:
        print_case(idx, desc, text_input, expect_pass)
        code, body = send_dialog(token, "EMP001", text_input)
        if code != 200:
            print(f"  [FAIL] HTTP {code}: {body}")
            results.append((idx, desc, "FAIL", f"HTTP {code}"))
            continue

        text = body.get("text", "")
        action_taken = body.get("action_taken", False)
        intent = body.get("intent")
        # 提取关键信息
        print(f"  返回：intent={intent}, action_taken={action_taken}")
        print(f"  助手：{text[:150]}{'...' if len(text) > 150 else ''}")

        # 判定：助手回复含创建标志（编号 #、已创建、已成功创建、加入批量列表等）
        created_invoice = (
            "编号：#" in text
            or "编号**：#" in text
            or "已成功创建" in text
            or "已为您成功创建" in text
            or ("已创建" in text and "批量" in text)
        )
        if expect_pass:
            if created_invoice:
                print(f"  [PASS] ✓ 期望成功，已创建无票报销")
                results.append((idx, desc, "PASS", "created"))
            else:
                print(f"  [WARN] 期望成功但未创建")
                results.append((idx, desc, "WARN", "not_created"))
        else:
            if created_invoice:
                print(f"  [FAIL] ✗ 期望拒绝但创建成功了")
                results.append((idx, desc, "FAIL", "should_reject"))
            else:
                print(f"  [PASS] ✓ 期望拒绝/追问，助手正确引导")
                results.append((idx, desc, "PASS", "rejected"))

    # === 总结 ===
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    passed = sum(1 for r in results if r[2] == "PASS")
    warned = sum(1 for r in results if r[2] == "WARN")
    failed = sum(1 for r in results if r[2] == "FAIL")
    print(f"通过：{passed} / {len(results)}")
    print(f"警告：{warned}")
    print(f"失败：{failed}")
    if warned > 0 or failed > 0:
        print("\n异常用例：")
        for idx, desc, status, msg in results:
            if status in ("WARN", "FAIL"):
                print(f"  #{idx} {desc}: {status} ({msg})")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n✗ {e}", file=sys.stderr)
        sys.exit(1)
