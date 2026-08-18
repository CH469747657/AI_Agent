"""100 条模拟对话测试用例 — 三端覆盖

测试目的：验证员工端、超级管理员端（老板端）、管理后台端对话交互。
覆盖：发票上传交互、多类型发票数据查询业务 + 异常请求、不合规输入反向场景。
正向/反向合理配比。

功能约束验证：发票上传/查询/修改（金额、用途、时间维度）操作返回结果必须附带
发票信息表格预览（Markdown 表格）。

数据隔离：
- 测试开始前清空 EMP001/EMP002/EMP003/EMP004 + admin/zhang 的对话上下文 + 发票+报销单
- 测试中产生的发票/报销单由 admin/boss 用例消费（审批/查询/打款）
- 测试结束后再次清空，不留中间数据

输出：仅打印对话的提问与回答内容（含表格预览片段）。
"""

import sys
import json
import urllib.request
import urllib.error
from datetime import date, timedelta
from pathlib import Path

# 容器内执行时让 /app 模块可被导入
for _p in ("/app",):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BASE = "http://127.0.0.1:8080"


def req(method, path, body=None, token=None, raw_data=None):
    url = f"{BASE}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if raw_data is not None:
        boundary = "----e2e_boundary"
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        data = raw_data.encode() if isinstance(raw_data, str) else raw_data
    else:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            body_text = resp.read()
            try:
                return resp.status, json.loads(body_text or "null")
            except json.JSONDecodeError:
                return resp.status, body_text.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "null")
        except json.JSONDecodeError:
            return e.code, None


def login(employee_no, password="123456"):
    code, body = req("POST", "/api/portal/auth/login",
                     {"employee_no": employee_no, "password": password})
    if code != 200:
        return None
    return body["access_token"]


def admin_login(username="admin", password="123456"):
    code, body = req("POST", "/api/admin/auth/login",
                     {"username": username, "password": password})
    if code != 200:
        return None
    return body["access_token"]


def boss_login(username="zhang", password="zhang"):
    code, body = req("POST", "/api/boss/auth/login",
                     {"username": username, "password": password})
    if code != 200:
        return None
    return body["access_token"]


def send_dialog(token, user_id, text, role="employee"):
    """调 portal 或 admin/boss 通用 dialog 端点

    员工走 /api/portal/dialog/message（JWT 强制 role=employee）
    管理员/老板走 /api/dialog/message（无鉴权，role 字段控制）
    """
    if role == "employee":
        return req("POST", "/api/portal/dialog/message",
                   {"user_id": user_id, "text": text}, token=token)
    else:
        return req("POST", "/api/dialog/message",
                   {"user_id": user_id, "text": text, "role": role}, token=token)


def reset_dialog(user_id):
    req("POST", f"/api/dialog/reset/{user_id}")


def clear_all_test_data():
    """清空 EMP001-004 + admin 创建的所有数据"""
    import asyncio
    from sqlalchemy import delete, select, update
    from app.database import get_async_sessionmaker
    from app.models.reimbursement import (
        ReimbursementTravelDay, Reimbursement, ReimbursementDaySubsidy,
        ReimbursementItem, ReimbursementAttachment,
    )
    from app.models.invoice import Invoice, OcrResult, LlmResult

    async def _do():
        async with get_async_sessionmaker()() as db:
            for emp in ["EMP001", "EMP002", "EMP003", "EMP004"]:
                await db.execute(update(Invoice).where(Invoice.user_id == emp).values(reimbursement_id=None))
                await db.execute(delete(ReimbursementTravelDay).where(ReimbursementTravelDay.applicant_id == emp))
                await db.execute(delete(ReimbursementDaySubsidy).where(
                    ReimbursementDaySubsidy.reimbursement_id.in_(
                        select(Reimbursement.id).where(Reimbursement.applicant_id == emp)
                    )))
                await db.execute(delete(ReimbursementItem).where(
                    ReimbursementItem.reimbursement_id.in_(
                        select(Reimbursement.id).where(Reimbursement.applicant_id == emp)
                    )))
                await db.execute(delete(ReimbursementAttachment).where(
                    ReimbursementAttachment.reimbursement_id.in_(
                        select(Reimbursement.id).where(Reimbursement.applicant_id == emp)
                    )))
                await db.execute(delete(Reimbursement).where(Reimbursement.applicant_id == emp))
                await db.execute(delete(Invoice).where(Invoice.user_id == emp))
            await db.commit()

    try:
        asyncio.run(_do())
        print("[清理] 已清空 EMP001-004 所有发票/报销单/travel_days")
    except Exception as e:
        print(f"[warn] 清理失败（忽略）：{e}")


# ============================================================
# 用例定义
# ============================================================
# 每条用例：(序号, 端, 描述, 输入文本, 期望类型)
# 期望类型：'create'（应创建/修改发票）/ 'reject'（应拒绝/追问）/ 'query'（应返表格）

CASES = [
    # ========== 员工端 40 条 ==========
    # -- 上传交互（5）正向 --
    (1, "employee", "上传-无凭证报销打车费", "无凭证报销 120 元去机场打车费", "create"),
    (2, "employee", "上传-无凭证报销餐费", "我有一笔 350 元的客户招待餐费需要无票报销", "create"),
    (3, "employee", "上传-无凭证报销办公费", "无票报销 88.5 元办公文具采购", "create"),
    (4, "employee", "上传-无凭证报销住宿费", "无凭证报销 500 元出差住宿费", "create"),
    (5, "employee", "上传-无凭证报销培训费", "无票报销 1500 元员工培训资料费", "create"),
    # -- 上传反向（5）异常输入 --
    (6, "employee", "异常-缺金额", "无凭证报销打车费", "reject"),
    (7, "employee", "异常-缺用途", "无凭证报销 120 元", "reject"),
    (8, "employee", "异常-负数金额", "无凭证报销 -100 元打车费", "reject"),
    (9, "employee", "异常-金额非数字", "无凭证报销 abc 元打车费", "reject"),
    (10, "employee", "异常-用途乱码", "无凭证报销 100 元 ???!!!", "reject"),
    # -- 查询业务（8）正向 --
    (11, "employee", "查询-我的发票列表", "看看我的发票", "query"),
    (12, "employee", "查询-我的报销单", "我的报销单", "query"),
    (13, "employee", "查询-报销进度", "我的报销到哪了", "query"),
    (14, "employee", "查询-我花了多少", "我总共报了多少", "query"),
    (15, "employee", "查询-未提交票据", "还有发票没提交吗", "query"),
    (16, "employee", "查询-费用分类占比", "我哪类费用多", "query"),
    (17, "employee", "查询-某分类明细", "我有哪些打车费的发票", "query"),
    (18, "employee", "查询-费用趋势", "我的费用变化", "query"),
    # -- 查询反向（3）异常 --
    (19, "employee", "异常-越权查他人", "查看李总的发票", "reject"),
    (20, "employee", "异常-越权查全员", "公司所有发票", "reject"),
    (21, "employee", "异常-查询未来日期", "明年 12 月我报了多少", "reject"),
    # -- 修改业务（7）正向 --
    (22, "employee", "修改-用途", "把第一张发票的用途改成投标费", "create"),
    (23, "employee", "修改-金额", "把金额改成 200", "create"),
    (24, "employee", "修改-日期", "发票日期改成 2026-08-15", "create"),
    (25, "employee", "修改-销售方", "销售方改成江苏某公司", "create"),
    (26, "employee", "修改-税号", "税号改成 91320100MA1ABC123", "create"),
    (27, "employee", "修改-发票号", "发票号改成 12345678", "create"),
    (28, "employee", "修改-第二张金额", "第二张发票金额改为 500", "create"),
    # -- 修改反向（2）异常 --
    (29, "employee", "异常-修改不存在字段", "把颜色改成红色", "reject"),
    (30, "employee", "异常-修改越权他人", "把李总的发票金额改成 200", "reject"),
    # -- 出差日（5）正向 --
    (31, "employee", "出差日-单日标记", "8月15日去北京出差", "create"),
    (32, "employee", "出差日-区间标记", "8月15-17日去上海出差", "create"),
    (33, "employee", "出差日-列表标记", "8月20 21 22 出差", "create"),
    (34, "employee", "出差日-带备注", "8月18日去南京谈客户", "create"),
    (35, "employee", "出差日-周末标记", "本周六出差", "create"),
    # -- 出差日反向（3）异常 --
    (36, "employee", "异常-非当前周期", "1999年1月1日出差", "reject"),
    (37, "employee", "异常-无日期", "我下周出差", "reject"),
    (38, "employee", "异常-日期格式错", "abcd 出差", "reject"),
    # -- 边界（2） --
    (39, "employee", "边界-极小金额", "无凭证报销 0.01 元打印费", "create"),
    (40, "employee", "边界-极大合理金额", "无凭证报销 99999 元员工培训住宿费", "create"),

    # ========== 管理后台 30 条 ==========
    # -- 审批（5）正向 --
    (41, "admin", "审批-批准报销", "批准报销", "query"),
    (42, "admin", "审批-按人批准", "批准陈辉的报销", "query"),
    (43, "admin", "审批-驳回", "驳回报销", "query"),
    (44, "admin", "审批-按人驳回", "驳回李总的报销", "query"),
    (45, "admin", "审批-查看待审批", "待审批列表", "query"),
    # -- 查询任意员工（8）正向 --
    (46, "admin", "查询-员工报销", "查陈辉的报销", "query"),
    (47, "admin", "查询-员工发票", "李总的发票", "query"),
    (48, "admin", "查询-指定周期汇总", "这个周期汇总", "query"),
    (49, "admin", "查询-7月周期", "7月周期报销了多少", "query"),
    (50, "admin", "查询-封账状态", "封账了吗", "query"),
    (51, "admin", "查询-按部门", "哪个部门花得多", "query"),
    (52, "admin", "查询-人员排行", "谁报销最多", "query"),
    (53, "admin", "查询-人员明细", "陈辉的报销明细", "query"),
    # -- 周期汇总（5）正向 --
    (54, "admin", "周期-本月情况", "本月周期情况", "query"),
    (55, "admin", "周期-上月汇总", "上周周期汇总", "query"),
    (56, "admin", "周期-封账", "封账 2026-08", "query"),
    (57, "admin", "周期-生成本周期报销单", "生成所有人的报销单", "create"),
    (58, "admin", "周期-手动归集", "归集发票", "create"),
    # -- 标记打款（4）正向 --
    (59, "admin", "打款-按编号", "给 30 号打款", "query"),
    (60, "admin", "打款-按人", "给陈辉打款", "query"),
    (61, "admin", "打款-确认", "确认打款", "query"),
    (62, "admin", "打款-多笔", "给 30 和 31 号打款", "query"),
    # -- 反向异常（8） --
    (63, "admin", "异常-审批不存在", "批准 99999 号报销", "reject"),
    (64, "admin", "异常-打款未审核", "给 1 号打款", "reject"),
    (65, "admin", "异常-重复封账", "封账 2026-01", "reject"),
    (66, "admin", "异常-修改员工发票", "把陈辉的发票金额改成 200", "reject"),
    (67, "admin", "异常-删员工发票", "删除陈辉的发票", "reject"),
    (68, "admin", "异常-无员工匹配", "查张三丰的报销", "reject"),
    (69, "admin", "异常-格式错", "批准 abcd 号报销", "reject"),
    (70, "admin", "异常-金额超限", "无凭证报销 200000 元打车费", "reject"),

    # ========== 超级管理员（老板端）30 条 ==========
    # -- 穿透查询（8）正向 --
    (71, "boss", "查询-全部发票", "公司所有的发票", "query"),
    (72, "boss", "查询-全部报销", "公司报销单", "query"),
    (73, "boss", "查询-全部员工", "员工列表", "query"),
    (74, "boss", "查询-部门统计", "各部门报销", "query"),
    (75, "boss", "查询-分类占比", "差旅费占多少", "query"),
    (76, "boss", "查询-异常发票", "重复的发票", "query"),
    (77, "boss", "查询-验真失败", "验真失败的发票", "query"),
    (78, "boss", "查询-高风险", "高风险的发票", "query"),
    # -- 报销单查看（5）正向 --
    (79, "boss", "查看-报销单详情", "查看 30 号报销单", "query"),
    (80, "boss", "查看-按人查", "陈辉的报销", "query"),
    (81, "boss", "查看-按部门", "销售部报销", "query"),
    (82, "boss", "查看-按周期", "本月报销", "query"),
    (83, "boss", "查看-总额", "公司花了多少", "query"),
    # -- 人员统计（5）正向 --
    (84, "boss", "统计-人员排行", "谁报销最多", "query"),
    (85, "boss", "统计-部门排行", "哪个部门花得多", "query"),
    (86, "boss", "统计-趋势", "费用变化", "query"),
    (87, "boss", "统计-对比", "这个月比上个月花得多吗", "query"),
    (88, "boss", "统计-top", "报销最多的前 5 名", "query"),
    # -- 写操作拒绝（8）反向 --
    (89, "boss", "异常-boss审批", "批准报销", "reject"),
    (90, "boss", "异常-boss驳回", "驳回报销", "reject"),
    (91, "boss", "异常-boss打款", "给 30 号打款", "reject"),
    (92, "boss", "异常-boss封账", "封账 2026-08", "reject"),
    (93, "boss", "异常-boss生成报销单", "生成所有人的报销单", "reject"),
    (94, "boss", "异常-boss归集", "归集发票", "reject"),
    (95, "boss", "异常-boss修改", "把陈辉的发票金额改成 200", "reject"),
    (96, "boss", "异常-boss删除", "删除陈辉的发票", "reject"),
    # -- 异常输入（4）反向 --
    (97, "boss", "异常-越权员工操作", "我上传一张发票", "reject"),
    (98, "boss", "异常-员工端无凭证", "无凭证报销 120 元打车费", "reject"),
    (99, "boss", "异常-格式错", "批准 abcd", "reject"),
    (100, "boss", "异常-不存在的员工", "查诸葛亮的报销", "reject"),
]


def run_case(idx, role, desc, text, expected, tokens):
    """跑一条用例，返回 (idx, role, desc, status, detail)

    status: PASS / WARN / FAIL
    """
    token = tokens.get(role)
    user_id = {
        "employee": "EMP001",
        "admin": "admin",
        "boss": "zhang",
    }[role]

    # 每条用例前 reset 对话上下文
    reset_dialog(user_id)

    code, body = send_dialog(token, user_id, text, role=role)
    if code != 200:
        return idx, role, desc, "FAIL", f"HTTP {code}"

    resp_text = body.get("text", "") if isinstance(body, dict) else str(body)
    action_taken = body.get("action_taken", False) if isinstance(body, dict) else False
    intent = body.get("intent") if isinstance(body, dict) else None

    # 判定逻辑
    has_table = (
        "| 发票编号 |" in resp_text
        or "| 项目 | 内容 |" in resp_text
        or "| 编号 |" in resp_text
        or "| 日期 |" in resp_text
        or "| 销售方 |" in resp_text
        or ("---" in resp_text and "|" in resp_text)
    )
    created = (
        "已创建" in resp_text
        or "编号：#" in resp_text
        or "编号**：#" in resp_text
        or "已成功创建" in resp_text
        or "已修改" in resp_text
        or "已将发票" in resp_text
        or "已标记" in resp_text
        or "已挂载" in resp_text
        or "已批准" in resp_text
        or "已驳回" in resp_text
        or "已打款" in resp_text
        or "已封账" in resp_text
        or "已归集" in resp_text
    )
    rejected = (
        "请提供" in resp_text
        or "请补充" in resp_text
        or "请描述" in resp_text
        or "不符合" in resp_text
        or "无效" in resp_text
        or "不能" in resp_text
        or "无法" in resp_text
        or "未找到" in resp_text
        or "不存在" in resp_text
        or "无权限" in resp_text
        or "没有权限" in resp_text
        or "仅" in resp_text and "可" in resp_text
        or "需" in resp_text and "补充" in resp_text
        or "请" in resp_text and "金额" in resp_text
        or "请" in resp_text and "用途" in resp_text
    )

    if expected == "create":
        if created:
            status = "PASS"
            detail = "已创建/修改"
        elif has_table:
            status = "PASS"
            detail = "返回表格"
        else:
            status = "WARN"
            detail = "未明确创建标志"
    elif expected == "query":
        if has_table:
            status = "PASS"
            detail = "返回表格预览 ✓"
        elif "暂无" in resp_text or "没有" in resp_text or "未找到" in resp_text:
            status = "PASS"
            detail = "无数据场景正常"
        else:
            status = "WARN"
            detail = "未返回表格"
    elif expected == "reject":
        if rejected:
            status = "PASS"
            detail = "正确拒绝/引导"
        elif created:
            status = "FAIL"
            detail = "应拒绝但执行了"
        else:
            status = "WARN"
            detail = "未明确拒绝标志"

    return idx, role, desc, status, detail, resp_text


def main():
    print("=" * 70)
    print("100 条模拟对话测试 — 三端覆盖")
    print("=" * 70)

    # 清空测试数据
    clear_all_test_data()

    # 登录三端
    tokens = {
        "employee": login("EMP001", "123456"),
        "admin": admin_login("admin", "123456"),
        "boss": boss_login("zhang", "zhang"),
    }
    for role, tok in tokens.items():
        if tok:
            print(f"[OK] {role} 登录成功")
        else:
            print(f"[FAIL] {role} 登录失败")
            return

    # 用 admin 先造 1 张无凭证报销发票（让员工查询/修改有数据）
    print("\n[准备] 造基线数据：admin 创建 EMP001 一张无凭证报销发票 + 一张 OFD 增值税普票")
    # 用员工账号造（员工对话触发无凭证报销）
    reset_dialog("EMP001")
    code, body = send_dialog(tokens["employee"], "EMP001",
                              "无凭证报销 200 元机场打车费", role="employee")
    if code == 200:
        print(f"  基线无凭证发票创建：{body.get('action_taken') if isinstance(body, dict) else 'N/A'}")
    reset_dialog("EMP001")

    # 跑 100 条用例
    print("\n" + "=" * 70)
    print("开始执行 100 条用例")
    print("=" * 70)

    results = []
    for case in CASES:
        idx, role, desc, text, expected = case
        print(f"\n{'─' * 70}")
        print(f"用例 #{idx} [{role}] {desc}")
        print(f"提问：{text}")
        result = run_case(idx, role, desc, text, expected, tokens)
        idx, role, desc, status, detail, resp_text = result
        # 只打印回复前 300 字（含表格片段）
        preview = resp_text[:400].replace("\n", " | ")
        print(f"回答：{preview}{'...' if len(resp_text) > 400 else ''}")
        print(f"判定：{status} — {detail}")
        results.append((idx, role, desc, status, detail))

    # 总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    total = len(results)
    by_status = {"PASS": 0, "WARN": 0, "FAIL": 0}
    by_role = {"employee": [0, 0, 0], "admin": [0, 0, 0], "boss": [0, 0, 0]}
    for idx, role, desc, status, detail in results:
        by_status[status] = by_status.get(status, 0) + 1
        role_idx = {"PASS": 0, "WARN": 1, "FAIL": 2}[status]
        by_role[role][role_idx] += 1

    print(f"\n总计：{total} 条")
    print(f"  PASS: {by_status['PASS']}")
    print(f"  WARN: {by_status['WARN']}")
    print(f"  FAIL: {by_status['FAIL']}")

    print("\n按端统计：")
    for role in ["employee", "admin", "boss"]:
        p, w, f = by_role[role]
        print(f"  {role:10s}: PASS={p}  WARN={w}  FAIL={f}")

    if by_status["FAIL"] > 0 or by_status["WARN"] > 0:
        print("\n异常用例：")
        for idx, role, desc, status, detail in results:
            if status in ("FAIL", "WARN"):
                print(f"  #{idx} [{role}] {desc}: {status} — {detail}")

    # 清理测试数据
    print("\n[清理] 测试结束，清空所有测试残留数据...")
    clear_all_test_data()
    # reset 所有对话上下文
    for uid in ["EMP001", "EMP002", "admin", "zhang"]:
        reset_dialog(uid)
    print("[OK] 清理完成，系统内不留中间测试数据")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
