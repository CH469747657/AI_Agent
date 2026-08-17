#!/usr/bin/env python3
"""批量验证对话用例权限"""
import json, subprocess, time, sys

EMP_TOKEN = subprocess.check_output(
    ['curl', '-s', '-X', 'POST', 'http://127.0.0.1:13000/api/portal/auth/login',
     '-H', 'Content-Type: application/json',
     '-d', '{"employee_no":"EMP001","password":"Test1234"}']
).decode()
EMP_TOKEN = json.loads(EMP_TOKEN)['access_token']

EMP_CASES = [
    ("查我的发票", "发票", "查", "允许"),
    ("我上传了多少张发票", "发票", "查", "允许"),
    ("我有哪些未提交的票据", "发票", "查", "允许"),
    ("我的发票总金额是多少", "发票", "查", "允许"),
    ("我的第一张发票详情", "发票", "查", "允许"),
    ("查我的报销单", "报销单", "查", "允许"),
    ("无凭证报销200元，原因是打车费", "发票", "增", "允许"),
    ("这张发票用途是差旅费", "发票", "增", "允许"),
    ("前两张是打车费，第三张是餐费", "发票", "增", "允许"),
    ("帮我上传这张发票，用途是办公用品", "发票", "增", "允许"),
    ("再上传一张发票", "发票", "增", "允许"),
    ("第一张发票的金额改成100", "发票", "改", "允许"),
    ("把这张发票的用途改成投标费", "发票", "改", "允许"),
    ("第二张发票的日期改成2026-08-01", "发票", "改", "允许"),
    ("修改发票销售方为XX公司", "发票", "改", "允许"),
    ("把这张的税号改成12345678", "发票", "改", "允许"),
    ("金额改为100，日期改为2026-08-01", "发票", "改", "允许"),
    ("删除上一张发票", "发票", "删", "允许"),
    ("删除第2张发票", "发票", "删", "允许"),
    ("撤销刚才上传的发票", "发票", "删", "允许"),
    ("查我的报销进度", "报销单", "查", "允许"),
    ("报销单65到哪一步了", "报销单", "查", "允许"),
    ("我本期报销了多少", "报销单", "查", "允许"),
    ("我的报销单有哪些周期", "报销单", "查", "允许"),
    ("删除我的报销单65", "报销单", "删", "拒绝"),
    ("提交我的报销单", "报销单", "增", "拒绝"),
    ("修改报销单65的事由", "报销单", "改", "拒绝"),
    ("查看陈辉的发票", "发票", "查", "拒绝"),
    ("查看所有员工的报销单", "报销单", "查", "拒绝"),
    ("批准陈辉的报销单", "报销单", "改", "拒绝"),
]

def call_api(text, is_admin=False):
    if is_admin:
        url = "http://127.0.0.1:18080/api/dialog/message"
        payload = json.dumps({"user_id":"admin","text":text,"role":"admin"})
        headers = ['Content-Type: application/json']
    else:
        url = "http://127.0.0.1:13000/api/portal/dialog/message"
        payload = json.dumps({"user_id":"EMP001","text":text,"role":"employee"})
        headers = [f'Authorization: Bearer {EMP_TOKEN}','Content-Type: application/json']
    args = ['curl','-s','-N','-X','POST',url,'-H',headers[0]]
    if len(headers) > 1:
        args += ['-H', headers[1]]
    args += ['-d', payload, '--max-time', '90']
    out = subprocess.check_output(args).decode()
    try:
        return json.loads(out)
    except:
        return {"intent": "(parse_fail)", "text": out[:200]}

# 每条用例前重置上下文，避免多轮污染
def reset(is_admin):
    if is_admin:
        subprocess.run(['curl','-s','-X','POST','http://127.0.0.1:18080/api/dialog/reset/admin'],
                       capture_output=True)
    else:
        subprocess.run(['curl','-s','-X','POST','http://127.0.0.1:13000/api/portal/dialog/reset',
                       '-H', f'Authorization: Bearer {EMP_TOKEN}'], capture_output=True)

print(f"{'#':>3} {'预期':>4} {'实际intent':<28} {'判定':<6} 问题")
print("-"*120)
results = []
for i, (text, entity, op, expected) in enumerate(EMP_CASES, 1):
    reset(False)
    r = call_api(text, is_admin=False)
    intent = r.get('intent') or '(空)'
    text_resp = (r.get('text') or '')[:100].replace('\n',' ')
    # 判定实际允许/拒绝：intent 非空且不是 emp_submit_reimbursement 黑名单
    blocked = ['emp_submit_reimbursement']
    deny_signals = ['无权限','没有权限','不允许','暂不支持','员工端']
    if intent in blocked:
        actual = '拒绝'
    elif intent == '(空)':
        actual = '拒绝'
    elif any(s in text_resp for s in deny_signals):
        actual = '拒绝'
    else:
        actual = '允许'
    passed = '✓' if actual == expected else '✗'
    print(f"{i:>3} {expected:>4} {intent:<28} {actual:>4} {passed} {text}")
    results.append((i, text, entity, op, expected, actual, intent, text_resp[:80]))

print("\n\n汇总:")
ok = sum(1 for r in results if r[5] == r[4])
print(f"通过 {ok}/{len(results)}")
fails = [r for r in results if r[5] != r[4]]
if fails:
    print("\n不一致用例:")
    for r in fails:
        print(f"  #{r[0]} 预期{r[4]} 实际{r[5]} intent={r[6]}")
        print(f"     问题: {r[1]}")
        print(f"     响应: {r[7]}")
