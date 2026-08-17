#!/usr/bin/env python3
"""管理端 30 条用例验证"""
import json, subprocess

ADMIN_CASES = [
    ("查看公司所有的发票", "发票", "查", "允许"),
    ("查看陈辉的发票", "发票", "查", "允许"),
    ("上传了多少张发票", "发票", "查", "允许"),
    ("有没有重复的发票", "发票", "查", "允许"),
    ("验真失败的发票有哪些", "发票", "查", "允许"),
    ("待审核的发票有哪些", "发票", "查", "允许"),
    ("无凭证报销200元，原因是打车费", "发票", "增", "允许"),
    ("帮陈辉上传这张发票", "发票", "增", "允许"),
    ("修改发票388的金额为100", "发票", "改", "允许"),
    ("把陈辉的发票金额改成500", "发票", "改", "允许"),
    ("修改发票销售方为XX公司", "发票", "改", "允许"),
    ("批量修改金额和日期", "发票", "改", "允许"),
    ("删除发票390", "发票", "删", "允许"),
    ("删除陈辉上传的重复发票", "发票", "删", "允许"),
    ("删除上一张发票", "发票", "删", "允许"),
    ("查看待审批的报销单", "报销单", "查", "允许"),
    ("查看报销单65的详情", "报销单", "查", "允许"),
    ("这个周期的报销汇总", "报销单", "查", "允许"),
    ("公司报销总额是多少", "报销单", "查", "允许"),
    ("哪个部门花得多", "报销单", "查", "允许"),
    ("查看陈辉的报销", "报销单", "查", "允许"),
    ("批准报销单65", "报销单", "改", "允许"),
    ("通过陈辉的报销", "报销单", "改", "允许"),
    ("驳回报销单65，原因是金额不符", "报销单", "改", "允许"),
    ("给报销单65打款", "报销单", "改", "允许"),
    ("归集游离发票生成报销单", "报销单", "增", "允许"),
    ("批量批准待审批的报销单", "报销单", "改", "允许"),
    ("删除报销单65", "报销单", "删", "拒绝"),
    ("给陈辉的发票打款", "发票", "改", "拒绝"),
    ("批准发票388", "发票", "改", "拒绝"),
]

def call_api(text):
    url = "http://127.0.0.1:18080/api/dialog/message"
    payload = json.dumps({"user_id":"admin","text":text,"role":"admin"})
    out = subprocess.check_output(
        ['curl','-s','-N','-X','POST',url,'-H','Content-Type: application/json',
         '-d', payload, '--max-time', '120']
    ).decode()
    try:
        return json.loads(out)
    except:
        return {"intent": "(parse_fail)", "text": out[:200]}

def reset():
    subprocess.run(['curl','-s','-X','POST','http://127.0.0.1:18080/api/dialog/reset/admin'],
                   capture_output=True)

print(f"{'#':>3} {'预期':>4} {'实际intent':<30} {'判定':<6} 问题")
print("-"*130)
results = []
for i, (text, entity, op, expected) in enumerate(ADMIN_CASES, 1):
    reset()
    r = call_api(text)
    intent = r.get('intent') or '(空)'
    text_resp = (r.get('text') or '')[:100].replace('\n',' ')
    # 判定：admin 大部分操作允许，但删除报销单/实体混淆应拒绝
    # 拒绝信号：无对应意图(intent空)、提示无权限/不支持、实体混淆提示
    deny_signals = ['无权限','没有权限','暂不支持','不支持修改','实体','不能','无法删除报销单']
    if intent == '(空)':
        actual = '拒绝'
    elif any(s in text_resp for s in deny_signals):
        actual = '拒绝'
    else:
        actual = '允许'
    passed = '✓' if actual == expected else '✗'
    print(f"{i:>3} {expected:>4} {intent:<30} {actual:>4} {passed} {text}")
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
