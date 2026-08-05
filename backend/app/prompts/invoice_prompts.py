"""LLM 提示词定义（参考 Invoice-Manager prompts.py）"""

import json

# ===== 发票字段JSON Schema =====
INVOICE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": ["string", "null"], "description": "发票号码，8-20位数字"},
        "invoice_code": {"type": ["string", "null"], "description": "发票代码，10-12位数字"},
        "issue_date": {"type": ["string", "null"], "description": "开票日期 YYYY-MM-DD"},
        "buyer_name": {"type": ["string", "null"], "description": "购买方名称"},
        "buyer_tax_id": {"type": ["string", "null"], "description": "购买方税号"},
        "seller_name": {"type": ["string", "null"], "description": "销售方名称"},
        "seller_tax_id": {"type": ["string", "null"], "description": "销售方税号"},
        "item_name": {"type": ["string", "null"], "description": "项目名称/货物名称"},
        "total_with_tax": {"type": ["string", "null"], "description": "价税合计，纯数字"},
        "amount": {"type": ["string", "null"], "description": "金额(不含税)，纯数字"},
        "tax_amount": {"type": ["string", "null"], "description": "税额，纯数字"},
        "tax_rate": {"type": ["string", "null"], "description": "税率，如6%、13%"},
    },
    "required": [
        "invoice_number", "invoice_code", "issue_date",
        "buyer_name", "buyer_tax_id", "seller_name", "seller_tax_id",
        "item_name", "total_with_tax", "amount", "tax_amount", "tax_rate"
    ],
}

REQUIRED_FIELDS = list(INVOICE_JSON_SCHEMA["required"])

# ===== Vision 系统提示词 =====
INVOICE_VISION_SYSTEM_PROMPT = """你是一个专业的中国发票信息提取助手。
严格按照JSON格式返回结果，无法识别的字段返回null。
只返回JSON对象，不要包含其他文字或markdown标记。"""

_field_desc = json.dumps(
    {k: v["description"] for k, v in INVOICE_JSON_SCHEMA["properties"].items()},
    ensure_ascii=False, indent=2
)

# ===== Vision 提取提示词 =====
INVOICE_VISION_PROMPT = f"""请分析这张中国发票图片，提取发票信息。

## 输出格式（必须严格遵守）
返回JSON对象，包含以下12个字段：
{_field_desc}

字段规则：
- 所有值为 string 或 null
- 日期格式 YYYY-MM-DD
- 金额仅含数字和小数点
- 税率格式如 "6%"、"13%"、"免税"

## 关键消歧规则（务必遵守）

### 购买方与销售方 MUST DIFFER
- 购买方和销售方是**不同的两家公司**，绝不可能相同
- 购买方 = "购买方"/"购方"标签下的"名称"
- 销售方 = "销售方"/"销方"标签下的"名称"
- 如果两个名称看起来一样，说明你看错了 — 重新仔细辨认

### 发票号码必须完整
- 新版数电发票号码为**20位纯数字**
- 必须完整提取全部20位，不可截断
- 发票号码通常在发票右上角

### 三个金额字段不可混淆
- amount = "金额"列 = **不含税金额**（较小）
- tax_amount = "税额" = 税款（最小）
- total_with_tax = "价税合计" = **含税总额**（最大）
- 关系: total_with_tax = amount + tax_amount
- "价税合计"通常有大写（叁佰元整）和小写（¥300.00）两种形式，取小写数字

### 项目名称完整提取
- 格式通常为 *分类*商品名称，需完整提取包括星号内分类
- 例如: *其他咨询服务*服务费，不要只提取"服务费"

## 字段提取规则
1. invoice_number: "发票号码"后的数字（20位）
2. invoice_code: "发票代码"后的数字（如有）
3. issue_date: "开票日期"，转YYYY-MM-DD
4. buyer_name: "购买方"区域的"名称"后公司全称
5. seller_name: "销售方"区域的"名称"后公司全称
6. buyer_tax_id: "购买方"的"纳税人识别号"
7. seller_tax_id: "销售方"的"纳税人识别号"
8. item_name: 商品行完整名称（含*分类*前缀）
9. total_with_tax: "价税合计"小写金额
10. amount: "金额"列不含税金额
11. tax_amount: "税额"列金额
12. tax_rate: "税率"列值

## 数据清洗
- 去除¥ ￥ $ 逗号
- 日期统一YYYY-MM-DD
- 无法识别返回null

请直接返回JSON对象："""

# ===== 费用分类提示词 =====
CLASSIFY_PROMPT = """你是企业费用分类助手。根据以下信息判断费用类别。

## 费用分类体系
- personal（个人类）
  - 差旅-住宿：出差住宿
  - 差旅-交通：火车/飞机/打车/加油
  - 差旅-餐饮：出差期间餐饮
  - 培训费：员工培训费、考试报名费、课程费用
  - 补贴：每日60/80元标准
- company（公司类）
  - 投标费：招投标报名费、标书制作费、投标保证金手续费
  - 咨询费：招标代理费、审计费、评估费、法律咨询费、设计服务费、勘察费
  - 快递物流费：快递费、物流费、邮政寄递费
  - 办公费：办公用品、打印耗材、文具
  - 软件开发费：软件开发、系统服务、信息技术服务
  - 安装费：设备安装、调试维修
  - 搬运费：物资搬运、吊装装卸
  - 配合费：小额现金工地协调（通常无票）
  - 运营费：其他日常运营支出（仅当无法归入以上具体类别时使用）

## 分类原则
1. 优先匹配具体类别（投标费/咨询费/快递物流费/培训费/办公费/软件开发费等）
2. 只有当费用内容确实无法归入任何具体类别时，才使用"运营费"
3. 根据销售方名称和用户描述综合判断，如"招标有限公司"→咨询费，"顺丰"→快递物流费

## 输入信息
- 票据类型: {receipt_type}
- 销售方: {seller_name}
- 金额: {amount}
- 用户描述: {user_description}

## 输出
返回JSON: {{"category": "personal或company", "subcategory": "具体类别", "confidence": 0.0到1.0}}"""

# ===== 项目名提取提示词 =====
PROJECT_EXTRACT_PROMPT = """从用户描述中提取项目名称。

已知项目列表: {project_names}
用户描述: "{description}"

返回匹配的项目名，无匹配返回null。只返回项目名称字符串。"""
