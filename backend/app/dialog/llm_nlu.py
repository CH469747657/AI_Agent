"""LLM NLU — 单层大模型意图理解引擎

替代 L1 正则 + L2 语义分类 + L3 LLM 分类器的三级瀑布架构，
通过单次 LLM 调用完成意图识别和槽位提取。

架构优势：
- 语义理解能力强，自然理解各种表述
- 开发维护成本低，无需为每个意图写正则
- 一步完成意图识别 + 槽位提取，无需两套正则
- 新意图只需在 prompt 中添加描述，无需写正则

性能优化：
- 响应缓存：相同 (text, role) 在 TTL 内直接命中，零延迟零成本
- 幂等性：相同请求不重复调 LLM
- 超时保护：5s 自动降级到"未识别"
"""

from __future__ import annotations

import json
import logging
import asyncio
import hashlib
import time
from typing import Any, Optional

from pydantic import ValidationError

from .models import NluResult, NluLevel, UserRole, DialogContext
from app.schemas.nlu_schema import NluResultSchema

logger = logging.getLogger(__name__)


# ============================================================
# LLM NLU System Prompt — 完整意图定义 + 槽位格式
# ============================================================

# 全量意图 prompt — 作为 RAG 检索不可用时的 fallback
# Step 2.1.5：新增 _build_prompt(candidates) 动态拼接候选意图，优先使用
_FALLBACK_PROMPT = """你是AI报销智能体的意图识别引擎。根据用户输入和角色，识别意图并提取槽位。

## 角色与可用意图

### employee（员工）可用意图：
- **emp_upload_invoice**: 上传发票（通过发送图片/文件触发，不在本文本分类范围内）
- **emp_no_receipt**: 无票报销，用户说"无发票""没有发票"等
- （注意：员工端不提供"提交报销单"功能，报销单由系统按报销周期自动生成与归集。请勿为"提交""完成""报完了""done"等返回 emp_submit_reimbursement）
- **emp_batch_upload**: 批量上传，如"还有一张""继续上传""再加一张"
- **emp_fill_purpose**: 填写报销用途，如"用于差旅""用途是培训""出差"
- **emp_delete_invoice**: 删除/撤销已上传但未提交的发票，如"删除上一张""撤销上传""删掉第2张""删除那张机票"。注意：只能删除未关联报销单的发票，已提交的不能删
- **emp_batch_describe**: 批量用途描述——用户一条说明为多张发票分配用途，如"前两张是差旅-交通，第三张是差旅-餐饮""1和3是打车，2是餐费"。只有当用户明确同时对多张发票描述不同用途时才触发此意图，单张发票描述仍走 emp_fill_invoice_desc
- **emp_batch_modify**: 批量修改发票字段——用户一次描述多个字段的修改，如"金额改为100，日期改为2026-08-01""把销售方改成XX公司，税号改成123"。只有当用户同时修改多个字段时才触发此意图，单字段修改仍走 emp_modify_field
- **emp_modify_field**: 修改单张发票的某个字段，如"把金额改成100""销售方改成XX公司""第一张发票的日期改成2026-08-01""把这张的用途改成投标费""修改第二张的税号"。可修改字段：金额、日期、销售方、税号、发票号、用途。槽位：field_name（字段名，如金额/日期/销售方/税号/发票号/用途）、field_value（新值）、invoice_index（可选，"第N张"→N，如"第一张"→1）
- **emp_query_status**: 查询报销进度，如"报销到哪了""批了没""查报销"
- **emp_query_invoices**: 查询已上传发票，如"我的发票""查看发票"
- **emp_query_my_reimbursement**: 查询我的报销单列表（含报销周期、费用/补贴明细、封账状态），如"我的报销单""我有哪些报销单""报销单列表""我的报销周期""看看我的报销单"
- **self_insight_total**: 我的报销总额，如"我花了多少""我报了多少"
- **self_insight_pending**: 我的未提交票据，如"有没有没报的""还有发票没提交""还有多少没报的"
  注意：这个意图名是 self_insight_pending，不是 emp_query_pending
- **self_insight_category**: 我的费用分类占比，如"我哪类费用多""我的费用分布"
- **self_insight_trend**: 我的费用趋势，如"我的费用变化""我最近开支走势"
- **self_insight_compare**: 我的期间费用对比，如"这个月比上个月花得多吗"
- **self_insight_category_amount**: 我的某类费用金额/明细。如"快递费花了多少""差旅费报了多少""我有哪些快递费的发票""我有哪些打车费的发票""哪些是打车费""打车费明细"
- **self_insight_invoice_total**: 我的发票统计，如"我上传了多少发票""我有多少张发票""我的发票总金额"
- **emp_permission_denied**: 员工越权查询拦截。员工询问非本人数据时返回此意图。判定流程：先读 user_msg 中的"用户身份: 工号=XXX 姓名=YYY"，若文本提到的人名/工号正是当前用户本人，按本人查询正常返回（如 self_insight_invoice_total），不返回此意图。仅当文本提到的人是**非当前用户**或公司全员范围时才返回此意图。
  示例：用户身份=工号EMP001姓名陈辉
  - "查看陈辉的发票" → self_insight_invoice_total（本人，不拦截）
  - "陈辉的发票" → self_insight_invoice_total（本人，不拦截）
  - "查看张三的发票" → emp_permission_denied（非本人，拦截）
  - "查看公司所有的发票" → emp_permission_denied（公司范围，拦截）

### admin（管理员）可用意图：
员工全部意图 + 以下：
- **emp_submit_reimbursement**: 提交/完成报销单，如"提交""完成""报完了""done"。管理员可代为提交（员工端禁用此意图）
- **admin_query_pending**: 待审批列表，如"待审批""还没处理的"
- **admin_query_person**: 查询指定员工报销，如"查张三的报销""陈辉报销了多少"。功能同 insight_person（管理员专属入口）
- **admin_query_cycle_summary**: 查询某报销周期汇总（报销单数、费用/补贴分拆、封账状态、各申请人明细），如"这个周期汇总""周期统计""7月周期报销了多少""封账了吗""本月周期情况"
- **admin_mark_reimbursed**: 标记已审核报销单为已打款（REVIEWED→REIMBURSED），如"给30号打款""30号已打款""标记报销""确认打款""给陈辉打款"。支持 person 槽位按姓名操作
- **admin_aggregate_invoices**: 批量归集游离发票到报销单，如"生成报销单""归集发票""生成所有人的报销单""汇总发票到报销单""把发票生成报销单"
- **admin_approve**: 批准报销，如"批准""通过""approve""批准陈辉的报销""通过陈辉报销单"。支持 person 槽位按姓名操作
- **admin_reject**: 驳回报销，如"驳回""不通过""拒绝"
- **insight_total**: 公司报销总额，如"公司花了多少""报销总额"
- **insight_by_dept**: 按部门统计，如"哪个部门花得多""各部门报销"
- **insight_by_category**: 费用类别分布，如"差旅费占多少""各类占比"
- **insight_category_amount**: 某分类费用金额，如"快递费花了多少"
- **insight_trend**: 公司费用趋势，如"趋势""变化""增长"
- **insight_compare**: 公司期间对比，如"环比""上月比本月"
- **insight_anomaly**: 异常检测（可指定类型），如"有没有异常""超标"。指定类型如"重复发票"→ filter_type=duplicate
- **insight_invoice_total**: 全公司发票统计，如"上传了多少发票""发票总金额""一共多少张发票"。支持 person 槽位按员工筛选，如"陈辉有多少张发票""8月陈辉有多少张发票"→ person="陈辉"
- **insight_invoice_filter**: 按条件筛选发票，如"重复的发票""验真失败的""高风险的发票""待审核的发票""有收据吗""收据有哪些""陈辉的重复发票""张三的收据"。支持 person 槽位按人员筛选
- **insight_top**: 费用排名，如"前5名""排行榜"
- **insight_person**: 查看某人报销，如"查看张三的报销""admin的费用"
- **insight_project**: 项目费用，如"XX项目花了多少"

### boss（老板）可用意图：
- common_help, common_cancel, common_greeting
- insight_total, insight_by_dept, insight_by_category, insight_category_amount
- insight_trend, insight_compare, insight_anomaly, insight_top
- insight_person, insight_project, insight_invoice_total, insight_invoice_filter
- emp_query_status, emp_query_my_reimbursement

## 关键语义判别规则（请严格遵守）

1. **角色感知**：员工说"我花了多少"→ self_insight_total（个人开支）；老板说同样的话 → insight_total（公司开支）。绝不能为老板返回 self_insight_* 意图！
2. **具体人名**：提到具体人名（中文/英文/工号）的费用 → insight_person，而非 insight_total
3. **占比/分布**："占比""分布""各占多少" → insight_by_category 或 self_insight_category
4. **分类名+金额/明细**：提到单个具体分类名，无论是问金额还是问明细（如"快递费花了多少""哪些是差旅费""差旅费有哪些"）→ insight_category_amount 或 self_insight_category_amount，而非 insight_by_category
5. **趋势/增长**："增长""波动""趋势""走势" → insight_trend 或 self_insight_trend
6. **上传引导**："怎么上传""发票怎么传" → common_help
7. **发票统计 vs 报销总额**：用户提到"发票数量""发票张数""发票总额""上传多少发票"→ insight_invoice_total（查发票表），而非 insight_total（查报销单表）。员工用 self_insight_invoice_total
8. **发票筛选 vs 异常检测**：用户明确问"重复的发票""验真失败的发票""高风险发票"→ insight_invoice_filter（返回筛选列表），而非 insight_anomaly（返回综合报告）。只有说"有没有异常""超标"才走 insight_anomaly
9. **anomaly_type**：用户指定异常类型时，insight_anomaly 应提取 anomaly_type 槽位。"重复"→duplicate，"验真失败"→invalid，"高风险"→high_risk，"超标"→over_budget。未指定则不提取此槽位
10. **员工越权查询**：员工（role=employee）询问非本人数据时，intent_name 返回 "emp_permission_denied"。
    **判定流程（必须执行）**：
    第一步：从 user_msg 中读取"用户身份: 工号=XXX 姓名=YYY"，记住当前用户的姓名 YYY 和工号 XXX
    第二步：检查用户输入中是否提到人名/工号
      - 若提到的人名/工号 == YYY 或 XXX（即本人）→ 按本人查询正常处理（如 self_insight_invoice_total），**不返回** emp_permission_denied
      - 若提到的人名/工号 != YYY 且 != XXX（即他人）→ 返回 emp_permission_denied
      - 若提到公司全员范围词（"公司所有""所有员工""全公司""各部门""全员"）→ 返回 emp_permission_denied
      - 若未提到人名/工号 → 按本人查询正常处理
    示例（假设用户身份=工号EMP001姓名陈辉）：
      - "查看陈辉的发票" → self_insight_invoice_total（陈辉是本人）
      - "陈辉的发票" → self_insight_invoice_total（陈辉是本人）
      - "陈辉的重复发票" → self_insight_invoice_filter（陈辉是本人）
      - "查看张三的发票" → emp_permission_denied（张三非本人）
      - "admin的发票" → emp_permission_denied（admin非本人）
      - "EMP002的发票" → emp_permission_denied（EMP002非本人工号）
      - "查看公司所有的发票" → emp_permission_denied（公司范围）
    返回该意图即可，由 FSM 回复"没有权限，只能看本人的信息。"

## 语义边界精细化（易混淆意图区分）

### insight_anomaly vs insight_top
- insight_anomaly：关注**数据是否异常**。关键词："异常""超标""违规""重复报销""不对劲""有问题"
- insight_top：关注**排名/排序**。关键词："最多""最少""最大""最小""排名""前N""排行""谁花得最多/最少"
- **关键区分**："谁报销金额特别大"→ insight_top（问的是排名），"有没有异常报销"→ insight_anomaly（问的是异常检测）
- 如果用户同时表达"最多"和"异常"，优先按**排名**意图处理 → insight_top

### insight_by_dept vs insight_top
- insight_by_dept：关注**部门维度的费用分布/对比**。关键词："哪个部门""各部门""按部门""部门花得多/少"
- insight_top：关注**个人排名**。关键词："谁""前N名""排行""花钱最多的人"
- **关键区分**："哪个部门花钱最多"→ insight_by_dept，"谁花钱最多"→ insight_top

### insight_trend vs insight_compare
- insight_trend：关注**变化趋势/走势**。关键词："趋势""变化""走势""增长""波动""逐月"
- insight_compare：关注**两个时间段对比**。关键词："比""对比""环比""同比""A月和B月"
- **关键区分**："最近半年费用怎么变化"→ insight_trend，"上月和本月对比"→ insight_compare

### insight_by_category vs insight_category_amount
- insight_by_category：关注**全部分类的分布/占比**。关键词："占比""分布""各占多少""哪些分类""有多少类费用"
- insight_category_amount：关注**某个具体分类的发票明细/金额**。关键词："哪些是XX费""XX费有哪些""XX费有哪些发票""XX费花了多少""XX费详情""XX费明细""XX费报了多少"
- **关键区分**："差旅费占多少""各类费用分布"→ insight_by_category（问全局分布占比），"哪些是差旅费""差旅费有哪些""差旅费有哪些发票""差旅费花了多少"→ insight_category_amount（问某分类的具体发票/金额）
- 判断原则：问的是「全局分布/各分类占比」→ insight_by_category；问的是「某个分类的具体发票或金额」→ insight_category_amount。即使没有金额词（如"哪些是差旅费"），只要聚焦在某个具体分类上就是 insight_category_amount

### insight_category_amount vs insight_invoice_filter（按分类查 vs 异常筛选）
- insight_category_amount：用户指定**费用分类名**（快递费/差旅费/餐饮费/打车费/投标费等），问该分类下的发票或金额。如"我有哪些快递费的发票""我有哪些打车费的发票""快递费明细""差旅费报了多少"
- insight_invoice_filter：用户指定**异常条件**（重复/验真失败/高风险/待审核/收据），筛选符合异常条件的发票。如"重复的发票""验真失败的""高风险的发票""待审核的发票""有收据吗"
- **关键区分**：宾语是「费用分类名」→ insight_category_amount（按分类查发票明细）；宾语是「异常条件」→ insight_invoice_filter（按异常筛发票）
- 判定流程：用户问"X的发票有哪些"时，先看 X 是费用分类名（如打车费/快递费/差旅费）还是异常条件（如重复/验真失败/高风险）。前者走 category_amount，后者走 invoice_filter
- 示例（必看）：
  - "我有哪些打车费的发票" → self_insight_category_amount（打车费是分类名）
  - "快递费的发票有哪些" → self_insight_category_amount（快递费是分类名）
  - "我有哪些差旅费的发票" → self_insight_category_amount（差旅费是分类名）
  - "重复的发票有哪些" → self_insight_invoice_filter（重复是异常条件）
  - "验真失败的发票有哪些" → self_insight_invoice_filter（验真失败是异常条件）
  - "待审核的发票有哪些" → self_insight_invoice_filter（待审核是状态条件）
- **绝不能**把"我有哪些X费的发票"误判为 invoice_filter

### insight_anomaly vs insight_invoice_filter
- insight_anomaly：关注**整体异常状况扫描**。关键词："有没有异常""超标""不对劲""有没有问题"——返回4类异常检测综合报告
- insight_invoice_filter：关注**按条件筛选发票列表**。用户明确说"重复的发票""验真失败的发票""高风险的发票""待审核的发票"——只返回符合条件的发票列表
- **关键区分**："发票里有没有重复的"→ insight_invoice_filter（用户只想看重复发票列表），"有没有异常报销"→ insight_anomaly（用户想看整体异常状况扫描）
- 如果用户指定了明确的筛选条件（重复/验真失败/高风险/待审核/收据），优先走 insight_invoice_filter

### insight_invoice_filter vs insight_invoice_total
- insight_invoice_filter：关注**按条件筛选特定类型发票**。用户说"有收据吗""收据有哪些""重复的发票""验真失败的"——筛选特定条件的发票列表
- insight_invoice_total：关注**发票统计汇总**。用户说"上传了多少发票""发票总金额""多少张发票"——统计发票张数和金额
- **关键区分**："有收据吗""收据有哪些"→ insight_invoice_filter（筛选收据），"有多少张发票"→ insight_invoice_total（统计）
10. **发票筛选 vs 人员查询**：用户问"这个收据/发票是谁上传的""这张发票谁传的"→ insight_invoice_filter（筛选后展示上传者），而非 insight_person。insight_person 是查看某人的报销费用，不是查发票上传者
11. **收据/票据类型筛选**：用户提到"收据""有收据吗""收据有哪些"→ insight_invoice_filter + filter_type="receipt"，不是 insight_invoice_total。员工用 self_insight_invoice_filter
12. **删除发票 vs 取消操作**："删除上一张""撤销上传""删掉第2张""删除那张机票"→ emp_delete_invoice（删除特定已上传发票记录），"取消""算了""不做了"→ common_cancel（取消整个对话流程）。emp_delete_invoice 只对未提交的发票有效
13. **人名 vs 时间词**：中文常见时间副词（目前、现在、当前、今天、昨天、本周、本月等）不是人名，绝不能提取到 person 槽位。"目前上传了多少发票"→ person 不填，而非 person="目前"

### insight_total vs insight_invoice_total
- insight_total：查询**报销单维度**的统计（报销总额、报销单笔数、报销人数）。关键词："公司花了多少""报销总额""报销了多少"
- insight_invoice_total：查询**发票维度**的统计（发票张数、发票总额、按状态分组），**支持 person 槽位按员工筛选**。关键词："上传了多少发票""发票总金额""多少张发票""发票统计""查看公司所有发票""查看XX的发票"
  - 当用户指定员工（如"员工admin上传了多少发票""陈辉的发票有多少张""查看陈辉的发票"）→ insight_invoice_total + person="admin"/"陈辉"
  - 未指定员工或"所有/全部/公司所有" → 全公司统计，**不填 person**（不要把"所有/全部/all"填入 person）
- **关键区分**：用户提到"发票""上传""张""的发票"→ insight_invoice_total（发票表），用户提到"报销""花了多少""的报销"→ insight_total（报销单表）

### insight_invoice_total vs admin_query_person/insight_person
- insight_invoice_total：关注**发票**。用户说"查看XX的发票""XX的发票""XX有多少张发票"→ 查发票表，person 槽位填 XX
- admin_query_person/insight_person：关注**报销单/费用**。用户说"查XX的报销""XX报销了多少""XX的费用"→ 查报销单
- **关键区分**："XX的发票"→ insight_invoice_total（发票表），"XX的报销/费用"→ admin_query_person（报销单）。即使"查看"是动词，只要宾语是"发票"就走 insight_invoice_total

### insight_top 的 order 和 data_scope 槽位
- order: "最多/最大/最高/榜首" → "desc"，"最少/最小/最低/末位" → "asc"，默认 "desc"
- data_scope: 数据来源范围
  - 用户提到"发票""票据""票" → data_scope="invoice"（按单张发票排序）
  - 用户提到"报销""报销单""人"或无明确词 → data_scope="reimbursement"（按人汇总，默认）
  - 关键区分："哪张发票金额最少"→ data_scope="invoice"，"谁报销最少"→ data_scope="reimbursement"

### emp_query_my_reimbursement vs emp_query_status vs self_insight_total
- emp_query_status：关注**审批进度**。关键词："报销到哪了""批了没""进度""查报销"
- emp_query_my_reimbursement：关注**报销单列表与周期明细**（含报销周期、费用/补贴分拆、封账状态）。关键词："我的报销单""报销单列表""报销周期""我有哪些报销单""看看我的报销单"
- self_insight_total：关注**报销总额汇总**（只给总额和按状态分组金额，无逐单列表）。关键词："我花了多少""我报了多少""总额"
- **关键区分**："报销到哪了"→ emp_query_status（进度），"我的报销单"→ emp_query_my_reimbursement（列表+周期明细），"我花了多少"→ self_insight_total（金额汇总）

### admin_query_cycle_summary vs insight_total vs admin_query_pending
- admin_query_cycle_summary：关注**某报销周期（21-20制）的汇总统计**，包括报销单数、费用/补贴分拆、封账状态、各申请人明细。关键词："周期汇总""周期统计""这个周期""封账了吗""本月周期情况"
- insight_total：关注**公司报销总额**，不区分周期维度。关键词："公司花了多少""报销总额"
- admin_query_pending：关注**待审批列表**。关键词："待审批""还没处理的"
- **关键区分**："这个周期报销了多少"→ admin_query_cycle_summary（周期维度+明细），"公司花了多少"→ insight_total（总额），"待审批"→ admin_query_pending（审批队列）

## 可提取的槽位

- **period**: 时间段，映射值：today/yesterday/current_week/last_week/current_month/last_month/current_year/last_year/last_6_months/last_12_months/YYYY-MM/YYYY
  - today=今天/今日, yesterday=昨天/昨日, current_week=本周/这周/这一周, last_week=上周/上一周
  - current_month=本月/这个月, last_month=上月/上个月, current_year=今年, last_year=去年
- **person**: 人员姓名或工号（中文2-4字或英文/工号如admin/EMP001）。注意：**不要**将以下时间/通用词识别为人名：目前、现在、当前、今天、昨天、本周、上周、本月、上月、今年、去年、最近、全部、一共、总共、至今、迄今、暂时、刚才、刚刚、近期、这几天、个月
  - 示例："目前上传了多少发票"→ person 不填；"陈辉的发票有多少张"→ person="陈辉"；"员工admin上传了多少"→ person="admin"；"8月一共上传多少"→ person 不填；"小李最近的上传"→ person="小李"
- **project_name**: 项目名称
- **fee_category_keyword**: 费用分类关键词（差旅/交通/住宿/餐饮/培训/快递/办公/投标/运营）
- **fee_category_aliases**: 费用分类别名列表（JSON数组字符串），根据 fee_category_keyword 自动推导。例如差旅→["差旅","住宿","交通","出差"]，餐饮→["餐饮","餐费","伙食","吃饭"]，培训→["培训","课程","学习"]，快递→["快递","物流","邮寄"]，办公→["办公","文具","耗材"]，投标→["投标","招标"]，运营→["运营"]。当识别到 fee_category_keyword 时必须同时输出此槽位
- **limit**: 排名数量（整数，如前5→5，前10→10）
- **order**: 排序方向，仅insight_top有效。"desc"=金额从多到少（最多/最大/最高，默认），"asc"=金额从少到多（最少/最小/最低）
- **data_scope**: 数据范围，仅insight_top有效。"invoice"=按单张发票排名，"reimbursement"=按人汇总排名（默认）
- **reimbursement_id**: 报销单编号（整数）
- **anomaly_type**: 异常类型，仅insight_anomaly有效。"duplicate"=重复发票，"invalid"=验真失败，"high_risk"=高风险，"over_budget"=超标报销。未指定则检测全部类型
- **filter_type**: 筛选类型，仅insight_invoice_filter有效。**严格枚举**：仅可为 "duplicate"（重复发票）、"invalid"（验真失败）、"high_risk"（高风险）、"pending"（待审核）、"receipt"（收据）之一。**绝不能填入费用分类名**（如"打车费""快递费""差旅费""餐饮费""培训费""投标费""办公费""住宿费"），分类名应走 self_insight_category_amount 的 fee_category_keyword 槽位。
  - 用户说"重复的发票"→ filter_type="duplicate"
  - 用户说"验真失败的发票"→ filter_type="invalid"
  - 用户说"高风险的发票"→ filter_type="high_risk"
  - 用户说"待审核的发票"→ filter_type="pending"
  - 用户说"收据有哪些"→ filter_type="receipt"
  - 用户说"打车费的发票"/"我有哪些打车费的发票"→ **不填 filter_type，不返回 invoice_filter**，应返回 self_insight_category_amount + fee_category_keyword="打车费"
  - 用户说"快递费的发票"/"我有哪些快递费的发票"→ **不填 filter_type，不返回 invoice_filter**，应返回 self_insight_category_amount + fee_category_keyword="快递费"
- **delete_target**: 删除目标，仅emp_delete_invoice有效。"last"=最近一张（默认），"index:N"=第N张（如"删除第2张"→"index:2"），"type:关键词"=按发票类型/销售方匹配（如"删除那张机票"→"type:机票"）
- **field_name**: 字段名，仅emp_modify_field有效。可选值：金额/日期/销售方/税号/发票号/用途。如"把金额改成100"→"金额"，"用途改成投标费"→"用途"，"销售方改一下"→"销售方"
- **field_value**: 字段新值，仅emp_modify_field有效。如"金额改成100"→"100"，"用途改成投标费"→"投标费"，"日期改成2026-08-01"→"2026-08-01"
- **invoice_index**: 发票序号（整数，1-based），仅emp_modify_field/emp_fill_invoice_desc等需要指定具体发票时有效。如"第一张"→1，"第2张"→2，"第三张"→3。未指定则不填（默认操作最近一张或上下文中的pending发票）

## 输出格式

严格返回以下 JSON，不要包含其他文字：
```json
{
  "intent_name": "意图名称，如果都不匹配则为空字符串",
  "confidence": 0.0到1.0的浮点数,
  "slots": {"槽位名": "槽位值"},
  "reasoning": "简要推理过程"
}
```"""


# ============================================================
# 动态 prompt 构造 — Step 2.1.5
# ============================================================

def _format_candidates(candidates: list) -> str:
    """格式化候选意图清单为 prompt 片段

    Args:
        candidates: Intent 对象列表（来自 IntentRetriever.retrieve）

    Returns:
        形如：
            - **intent_name**: description
              典型表述：utterance1 / utterance2 / ...
              槽位：required: [field_name, field_value] | optional: [invoice_index]
    """
    if not candidates:
        return ""
    lines: list[str] = []
    for intent in candidates:
        utts = " / ".join(intent.typical_utterances[:3]) if intent.typical_utterances else "无"
        slot_info = ""
        if intent.required_slots or intent.optional_slots:
            parts = []
            if intent.required_slots:
                parts.append(f"必填: {intent.required_slots}")
            if intent.optional_slots:
                parts.append(f"可选: {intent.optional_slots}")
            slot_info = f"\n  槽位（{' | '.join(parts)}）"
        lines.append(f"- **{intent.name}**: {intent.description}\n  典型表述：{utts}{slot_info}")
    return "\n".join(lines)


def _build_prompt(candidates: list | None, role_str: str = "") -> str:
    """构造 LLM system prompt

    策略：
    - candidates 非空：用 RAG 检索的 Top-K 候选意图构造精简 prompt（~800 tokens）
    - candidates 为空：降级到全量意图 prompt（_FALLBACK_PROMPT，~2500 tokens）

    Args:
        candidates: IntentRetriever.retrieve 返回的候选 Intent 列表
        role_str: 用户角色字符串（用于上下文提示）

    Returns:
        完整的 system prompt 字符串
    """
    if not candidates:
        # 降级：retriever 不可用或返回空，用全量意图 prompt
        return _FALLBACK_PROMPT

    candidates_block = _format_candidates(candidates)
    return f"""你是AI报销智能体的意图识别引擎。根据用户输入识别意图并提取槽位。

## 候选意图（从全库检索出的 Top-{len(candidates)} 个最相关意图）

{candidates_block}

## 关键判别规则

1. **角色感知**：当前用户角色为 {role_str or "未知"}，请基于此判断意图合理性
2. **置信度**：若用户输入与所有候选意图都不匹配，intent_name 返回空字符串
3. **槽位提取**：从用户输入中提取候选意图定义的槽位值，槽位名必须严格使用候选意图列出的标准名
4. **典型表述参考**：每个意图的"典型表述"是该意图的常见说法，可作为匹配参考
5. **发票查询 vs 报销查询**：用户说"查看XX的发票""XX的发票""列出XX的发票"→ insight_invoice_total（查发票表，person=XX）；用户说"查看XX的报销""XX报销了多少""XX的费用"→ admin_query_person/insight_person（查报销单）。**宾语是"发票"走 insight_invoice_total，宾语是"报销/费用"走 admin_query_person**
6. **全公司查询**：用户说"查看公司所有发票""所有发票""全部发票"→ insight_invoice_total，**不填 person**（不要把"所有/全部/all/公司"填入 person 槽位）
7. **员工越权查询**：员工（role=employee）询问非本人数据时，返回 intent_name="emp_permission_denied"。
   **判定流程（必须执行）**：
   第一步：从 user_msg 中读取"用户身份: 工号=XXX 姓名=YYY"
   第二步：检查用户输入是否提到人名/工号
     - 若人名/工号 == YYY 或 XXX（本人）→ 按本人查询正常返回（如 self_insight_invoice_total），不返回 emp_permission_denied
     - 若人名/工号 != YYY 且 != XXX（他人）→ 返回 emp_permission_denied
     - 若提到公司全员范围（"公司所有""所有员工""全公司""各部门""全员"）→ 返回 emp_permission_denied
     - 未提到人名/工号 → 按本人查询正常返回
   示例（用户身份=工号EMP001姓名陈辉）：
     - "查看陈辉的发票" → self_insight_invoice_total（陈辉是本人）
     - "查看张三的发票" → emp_permission_denied（张三非本人）
     - "EMP002的发票" → emp_permission_denied（EMP002非本人工号）
     - "查看公司所有的发票" → emp_permission_denied（公司范围）
   不在候选列表中也返回该意图，由 FSM 直接回复"没有权限，只能看本人的信息。"

## 通用槽位说明

- **invoice_index**: 发票序号（整数，1-based）。用户说"第一张"→1，"第2张"→2，"第三张"→3。当意图涉及具体发票操作（如 emp_modify_field/emp_fill_invoice_desc/emp_delete_invoice）且用户提到"第N张"时必须提取
- **field_name**: 字段名，仅 emp_modify_field 有效。可选值：金额/日期/销售方/税号/发票号/用途
- **field_value**: 字段新值，仅 emp_modify_field 有效
- **delete_target**: 删除目标，仅 emp_delete_invoice 有效。"last"=最近一张，"index:N"=第N张，"type:关键词"=按类型匹配

## 输出格式

严格返回以下 JSON，不要包含其他文字：
```json
{{
  "intent_name": "意图名称，如果都不匹配则为空字符串",
  "confidence": 0.0到1.0的浮点数,
  "slots": {{"槽位名": "槽位值"}},
  "reasoning": "简要推理过程"
}}
```"""


# ============================================================
# LLM 响应缓存 — TTL 过期 + 按缓存 key 去重
# ============================================================

class _CacheEntry:
    """缓存条目"""
    __slots__ = ('result', 'expires_at')

    def __init__(self, result: NluResult, ttl: float):
        self.result = result
        self.expires_at = time.monotonic() + ttl

    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


class LlmNluCache:
    """LLM NLU 响应缓存

    - 相同 (text, role, model) 在 TTL 内直接命中缓存，零延迟零成本
    - TTL 默认 300 秒（5 分钟），避免数据变更后缓存不一致
    - 最大条目数限制，防止内存泄漏
    - 幂等性：同一时刻相同请求只调一次 LLM（通过 asyncio.Lock 去重）

    分层模型路由（Step 1.1.3）：缓存 key 加入 model 字段，
    避免相同文本在不同模型下命中错误结果（跨模型污染）。
    """

    DEFAULT_TTL = 120          # 2 分钟（Step 2.2.3：从 300s 缩短，因历史变化快，长 TTL 缓存价值下降）
    MAX_ENTRIES = 500

    def __init__(self, ttl: float | None = None):
        self._cache: dict[str, _CacheEntry] = {}
        self._ttl = ttl or self.DEFAULT_TTL
        # 正在进行的 LLM 调用（防止并发重复调用）
        self._inflight: dict[str, asyncio.Task] = {}

    def _make_key(self, text: str, role: str, model: str = "", history_hash: str = "") -> str:
        """生成缓存 key

        Args:
            text: 用户输入
            role: 用户角色
            model: 模型名（隔离不同模型产生的结果）
            history_hash: 对话历史摘要的 hash（隔离不同历史下的结果）
        """
        raw = f"{model}:{history_hash}:{role}:{text.strip().lower()}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, text: str, role: str, model: str = "", history_hash: str = "") -> NluResult | None:
        """获取缓存结果"""
        key = self._make_key(text, role, model, history_hash)
        entry = self._cache.get(key)
        if entry and not entry.is_expired():
            logger.debug(
                "LLM NLU cache hit: text=%r role=%s model=%s history_hash=%s",
                text[:30], role, model, history_hash[:8] if history_hash else "(none)",
            )
            return entry.result
        return None

    def set(self, text: str, role: str, result: NluResult, model: str = "", history_hash: str = "") -> None:
        """写入缓存"""
        # 超出容量限制时清理过期条目
        if len(self._cache) >= self.MAX_ENTRIES:
            self._evict_expired()
            # 仍然超限则清空最早的一半
            if len(self._cache) >= self.MAX_ENTRIES:
                keys = list(self._cache.keys())
                for k in keys[:len(keys) // 2]:
                    del self._cache[k]

        key = self._make_key(text, role, model, history_hash)
        self._cache[key] = _CacheEntry(result, self._ttl)

    def _evict_expired(self) -> None:
        """清理过期条目"""
        expired = [k for k, v in self._cache.items() if v.is_expired()]
        for k in expired:
            del self._cache[k]
        if expired:
            logger.debug("LLM NLU cache evicted %d expired entries", len(expired))

    def invalidate(
        self,
        text: str | None = None,
        role: str | None = None,
        model: str | None = None,
    ) -> int:
        """使缓存失效

        - text=None, role=None: 清空全部缓存
        - 指定 text+role (+model): 只清除特定条目
        """
        if text is None and role is None:
            count = len(self._cache)
            self._cache.clear()
            return count
        if text and role:
            key = self._make_key(text, role, model or "")
            if key in self._cache:
                del self._cache[key]
                return 1
        return 0


# ============================================================
# LlmNlu — 单层 LLM NLU 引擎
# ============================================================

class LlmNlu:
    """单层 LLM NLU 引擎

    替代 L1+L2+L3 三级架构，通过单次 LLM 调用完成意图识别和槽位提取。
    内置响应缓存，相同 (text, role) 在 TTL 内零延迟返回。

    分层模型路由（Step 1.1.2）：通过 task_type 指定任务类型，
    由 settings.get_model_for_task() 解析具体模型，按 model 复用 OpenAI client。
    """

    TIMEOUT_SECONDS = 15.0
    CONFIDENCE_THRESHOLD = 0.6

    def __init__(self, task_type: str = "nlu_classify"):
        # task_type → 模型名解析延迟到 _ensure_client，便于运行时热更新
        self._task_type = task_type
        # 按 model 复用 client：相同 model 共享一个 OpenAI 实例，避免重复连接
        self._clients: dict[str, "OpenAI"] = {}
        self._initialized = False
        self._cache = LlmNluCache()
        # 并发去重锁：防止同一时刻多个协程对相同文本发起重复 LLM 调用
        self._locks: dict[str, asyncio.Lock] = {}

    def _resolve_model(self) -> str:
        """根据 task_type 解析当前应使用的模型名（每次调用都读，支持热更新）"""
        from app.config import settings
        return settings.get_model_for_task(self._task_type)

    def _ensure_client(self):
        """延迟初始化 LLM 客户端（按 model 复用，支持模型热更新）

        设计要点：
        - _initialized 仅标记"首次初始化已完成"，不阻止后续按需新增 client
        - 每次 _resolve_model() 返回的模型若不在 _clients 中，则新建一个 client
        - 模型热更新后（SystemSettings 表），下次调用自动用新模型
        """
        if not self._initialized:
            try:
                from app.config import settings, LLM_PROVIDERS
                from openai import OpenAI

                base_url = settings.llm_base_url
                if not base_url:
                    provider = settings.llm_provider.lower()
                    provider_info = LLM_PROVIDERS.get(provider, {})
                    base_url = provider_info.get("base_url", "")

                model = self._resolve_model()
                self._clients[model] = OpenAI(
                    api_key=settings.llm_api_key,
                    base_url=base_url,
                )
                self._initialized = True
                logger.info("LLM NLU initialized: task=%s model=%s", self._task_type, model)
            except Exception as e:
                logger.warning("Failed to init LLM NLU client: %s", e)
                self._initialized = True  # 避免反复重试

    def _get_client_and_model(self):
        """获取当前任务对应的 (client, model)，按需新建 client"""
        return self._get_client_and_model_for_task(self._task_type)

    def _get_client_and_model_for_task(self, task_type: str):
        """获取指定任务类型对应的 (client, model)，按需新建 client

        复用 self._clients dict，相同 model 共享 client。
        用于 batch_describe 等子任务需要切换模型的路由场景。
        """
        self._ensure_client()
        from app.config import settings
        model = settings.get_model_for_task(task_type)
        if model not in self._clients:
            try:
                from app.config import LLM_PROVIDERS
                from openai import OpenAI

                base_url = settings.llm_base_url
                if not base_url:
                    provider = settings.llm_provider.lower()
                    provider_info = LLM_PROVIDERS.get(provider, {})
                    base_url = provider_info.get("base_url", "")

                self._clients[model] = OpenAI(
                    api_key=settings.llm_api_key,
                    base_url=base_url,
                )
                logger.info("LLM NLU client added for model=%s (task=%s)", model, task_type)
            except Exception as e:
                logger.warning("Failed to create client for model=%s: %s", model, e)
                return None, model
        return self._clients.get(model), model

    def reset_client(self):
        """重置 LLM 客户端（配置变更后调用）

        清空所有按 model 缓存的 client，下次调用时按当前 task_type 重新建立。
        """
        self._clients.clear()
        self._initialized = False
        self._cache.invalidate()  # 配置变更，清空缓存
        logger.info("LLM NLU clients reset (task=%s)", self._task_type)

    async def classify(
        self,
        text: str,
        context: DialogContext,
    ) -> NluResult:
        """LLM 意图识别 + 槽位提取（带缓存 + 幂等去重）

        Args:
            text: 用户输入
            context: 对话上下文（含角色、当前状态）

        Returns:
            NluResult 识别结果
        """
        role = context.role.value
        # 解析当前任务对应的 model，用于缓存隔离（避免跨模型污染）
        model = self._resolve_model()
        # Step 2.2.3：缓存 key 加入 history_hash，避免相同文本在不同历史下命中错误结果
        # 历史摘要为空时 hash 固定，等价于无历史场景
        history_summary = context.get_history_summary(max_turns=3, max_tokens=500)
        history_hash = hashlib.md5(history_summary.encode()).hexdigest() if history_summary else ""

        # 1. 查缓存
        cached = self._cache.get(text, role, model, history_hash)
        if cached is not None:
            # 返回新对象，避免缓存被外部修改
            return NluResult(
                intent_name=cached.intent_name,
                confidence=cached.confidence,
                level=cached.level,
                raw_text=text,
                extracted_slots=dict(cached.extracted_slots),
            )

        # 2. 幂等去重：同一文本+角色+模型+历史只允许一个并发 LLM 调用
        cache_key = self._cache._make_key(text, role, model, history_hash)
        if cache_key not in self._locks:
            self._locks[cache_key] = asyncio.Lock()
        lock = self._locks[cache_key]

        if lock.locked():
            # 有其他协程正在调 LLM，等待其完成后再查缓存
            async with lock:
                cached = self._cache.get(text, role, model, history_hash)
                if cached is not None:
                    return NluResult(
                        intent_name=cached.intent_name,
                        confidence=cached.confidence,
                        level=cached.level,
                        raw_text=text,
                        extracted_slots=dict(cached.extracted_slots),
                    )
                # 等到了但缓存没写入（对方调用失败），返回未识别
                return NluResult(
                    intent_name="",
                    confidence=0.0,
                    level=NluLevel.L3_LLM,
                    raw_text=text,
                )

        async with lock:
            # 双重检查：获取锁后再查缓存
            cached = self._cache.get(text, role, model, history_hash)
            if cached is not None:
                return NluResult(
                    intent_name=cached.intent_name,
                    confidence=cached.confidence,
                    level=cached.level,
                    raw_text=text,
                    extracted_slots=dict(cached.extracted_slots),
                )

            # 3. 调 LLM
            result = await self._call_llm_classify(text, context)

            # 4. 写缓存（只缓存有意图的结果，未识别不缓存以允许重试）
            if result.intent_name:
                self._cache.set(text, role, result, model, history_hash)

            return result

    async def _resolve_user_identity(self, user_id: str) -> str:
        """查询当前用户工号+姓名，构造注入 NLU prompt 的身份描述

        返回形如 "用户身份: 工号=EMP001 姓名=陈辉\n"
        失败时返回空字符串（不影响主流程）
        """
        if not user_id:
            return ""
        try:
            from sqlalchemy import select
            from app.database import get_async_sessionmaker
            from app.models.employee import Employee
            sm = get_async_sessionmaker()
            async with sm() as db:
                result = await db.execute(
                    select(Employee.name, Employee.employee_no).where(
                        (Employee.employee_no == user_id)
                        | (Employee.wecom_user_id == user_id)
                    )
                )
                row = result.first()
                if row:
                    return f"用户身份: 工号={row.employee_no or user_id} 姓名={row.name}\n"
        except Exception as e:
            logger.warning("resolve_user_identity failed: %s", e)
        return ""

    async def _call_llm_classify(
        self,
        text: str,
        context: DialogContext,
    ) -> NluResult:
        """实际调用 LLM 进行意图识别"""
        client, model = self._get_client_and_model()
        if not client:
            logger.warning("LLM NLU client not available (task=%s model=%s)", self._task_type, model)
            return NluResult(
                intent_name="",
                confidence=0.0,
                level=NluLevel.L3_LLM,
                raw_text=text,
            )

        # 注入当前用户身份（工号 + 姓名）— 供 LLM 判断"X的发票"中的 X 是否本人
        # 例如陈辉本人问"陈辉的发票"应正常返回 self_insight_invoice_total，而非 emp_permission_denied
        user_identity = await self._resolve_user_identity(context.user_id)

        # Step 2.2.3：构造用户消息 — 注入对话历史摘要，让 LLM 自行处理省略句式与跨轮继承
        history_summary = context.get_history_summary(max_turns=3, max_tokens=500)
        if history_summary:
            user_msg = (
                f"用户角色: {context.role.value}\n"
                f"{user_identity}"
                f"{history_summary}\n"
                f"用户输入: {text}"
            )
        else:
            user_msg = f"用户角色: {context.role.value}\n{user_identity}用户输入: {text}"

        # Step 2.1.6：RAG 检索 Top-K 候选意图，构造精简 prompt
        candidates: list = []
        try:
            from .intent_retriever import get_intent_retriever
            retriever = get_intent_retriever()
            if retriever.is_built:
                candidates = await retriever.retrieve(text, context.role, top_k=8)
                if candidates:
                    logger.debug(
                        "RAG retrieved %d candidates for text=%r: %s",
                        len(candidates), text[:30],
                        [c.name for c in candidates],
                    )
        except Exception as e:
            logger.warning("RAG retrieve failed, falling back to full prompt: %s", e)

        # 动态构造 system prompt（candidates 为空时降级到 _FALLBACK_PROMPT）
        system_prompt = _build_prompt(candidates, context.role.value)

        try:
            result = await asyncio.wait_for(
                self._call_llm(user_msg, client, model, system_prompt),
                timeout=self.TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("LLM NLU timeout for text=%r", text)
            return NluResult(
                intent_name="",
                confidence=0.0,
                level=NluLevel.L3_LLM,
                raw_text=text,
            )
        except Exception as e:
            logger.warning("LLM NLU error: %s", e)
            return NluResult(
                intent_name="",
                confidence=0.0,
                level=NluLevel.L3_LLM,
                raw_text=text,
            )

        if not result:
            return NluResult(
                intent_name="",
                confidence=0.0,
                level=NluLevel.L3_LLM,
                raw_text=text,
            )

        # result 是 NluResultSchema 实例，属性访问（替代 dict.get）
        intent_name = result.intent_name
        confidence = result.confidence
        slots = result.slots
        reasoning = result.reasoning

        # 注：原 _INTENT_ALIASES / _SLOT_ALIASES 后处理已删除
        # Agent 模式（主路径）下 LLM 通过 Function Calling 调用 Tool，Tool 名是严格枚举
        # Legacy 路径下 prompt 已要求 LLM 输出标准意图名和槽位名
        # 若 LLM 返回非标准名，直接走 _handle_unrecognized 兜底，不再静默重映射

        # Step 2.1.6：badcase 监控 — 记录候选列表 vs 最终输出，便于分析 RAG 召回质量
        candidate_names = [c.name for c in candidates] if candidates else []
        logger.info(
            "LLM NLU result: text=%r intent=%s conf=%.2f slots=%s reasoning=%s | rag_candidates=%s",
            text, intent_name, confidence, slots, reasoning, candidate_names,
        )

        # badcase 检测：若 LLM 输出的意图不在候选列表中（且候选非空），标记为潜在误判
        if candidates and intent_name and intent_name not in candidate_names:
            logger.warning(
                "RAG badcase: LLM output %r not in retrieved candidates %r (text=%r)",
                intent_name, candidate_names, text[:50],
            )

        if not intent_name or confidence < self.CONFIDENCE_THRESHOLD:
            logger.debug(
                "LLM NLU low confidence: text=%r intent=%s conf=%.2f",
                text, intent_name, confidence,
            )
            # Step 1.2.7：低置信度时保留候选意图，供 DialogEngine 构造澄清追问
            candidates: list[tuple[str, float]] = []
            if intent_name and confidence >= 0.3:  # 太低置信度不作为候选
                candidates.append((intent_name, confidence))
            return NluResult(
                intent_name="",
                confidence=confidence,
                level=NluLevel.L3_LLM,
                raw_text=text,
                extracted_slots=slots,
                candidates=candidates,
            )

        return NluResult(
            intent_name=intent_name,
            confidence=confidence,
            level=NluLevel.L3_LLM,
            raw_text=text,
            extracted_slots=slots,
        )

    async def _call_llm(
        self,
        user_msg: str,
        client,
        model: str,
        system_prompt: str | None = None,
    ) -> Optional[NluResultSchema]:
        """调用 LLM API（client 和 model 由调用方传入，支持多模型路由）

        Step 1.2.2 改造：
        - 使用 response_format={"type": "json_object"} 强制 LLM 返回 JSON
        - 用 NluResultSchema Pydantic 校验替代脆弱的 split("```json") 解析
        - 校验失败时重试 1 次（带"请严格返回 JSON"提示）
        - 保留 markdown 代码块剥离作为 fallback（兼容不完整支持 response_format 的 Provider）

        Step 2.1.5 改造：
        - system_prompt 参数由调用方传入（_build_prompt 动态构造）
        - 默认 None 时降级用 _FALLBACK_PROMPT（全量意图）

        Returns:
            NluResultSchema 或 None（重试后仍失败）
        """
        schema = NluResultSchema.model_json_schema()
        # Step 2.1.5：system_prompt 由调用方传入，默认用全量 fallback
        sys_prompt = system_prompt or _FALLBACK_PROMPT

        for attempt in range(2):  # 1 次正常 + 1 次重试
            try:
                resp = await asyncio.to_thread(
                    client.chat.completions.create,
                    model=model,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.1,
                    max_tokens=256,
                    timeout=self.TIMEOUT_SECONDS,
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content.strip()
                # Fallback：若 Provider 仍返回 markdown 包裹的 JSON，剥离代码块
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                # Pydantic 校验（替代 json.loads + 手动 dict.get）
                try:
                    return NluResultSchema.model_validate_json(content)
                except ValidationError as ve:
                    logger.warning(
                        "LLM NLU schema validation failed (attempt=%d): %s content=%r",
                        attempt + 1, ve, content[:200],
                    )
                    # 校验失败 → 重试时追加"严格 JSON"提示
                    if attempt == 0:
                        user_msg = (
                            user_msg
                            + "\n\n[注意] 上次返回的内容不符合 JSON 格式要求，"
                            "请严格返回 JSON 对象，不要包含任何 markdown 标记或额外文字。"
                        )
                        continue
                    return None

            except json.JSONDecodeError as e:
                logger.warning(
                    "LLM NLU JSON parse error (attempt=%d): %s",
                    attempt + 1, e,
                )
                if attempt == 0:
                    continue
                return None
            except Exception as e:
                logger.warning("LLM NLU API call error (attempt=%d): %s", attempt + 1, e)
                return None  # API 错误不重试，避免无谓等待

        return None


    async def _call_llm_batch_describe(
        self,
        user_text: str,
        invoice_brief: str,
        invoice_count: int,
    ) -> list[dict] | None:
        """调用 LLM 将用户描述拆解为每张发票的用途映射

        Args:
            user_text: 用户输入的批量描述文本
            invoice_brief: 当前批量发票的简要信息
            invoice_count: 发票数量

        Returns:
            [{"invoice_id": int, "description": str}, ...] 或 None（拆解失败）
        """
        self._ensure_client()
        client, model = self._get_client_and_model_for_task("batch_describe")
        if not client:
            return None

        prompt = (
            f"用户说：\"{user_text}\"\n\n"
            f"当前批量发票列表（{invoice_count}张）：\n{invoice_brief}\n\n"
            f"请将用户的描述拆解为每张发票对应的用途。\n"
            f"返回JSON数组，每项含 invoice_id 和 description：\n"
            f'[{{"invoice_id": 1, "description": "差旅-交通"}}, ...]\n'
            f"如果用户描述无法精确对应到每张发票，对未提及的发票设置 description 为空字符串。\n"
            f"只返回JSON，不要其他文字。"
        )

        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat.completions.create,
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=256,
                    timeout=10.0,
                ),
                timeout=15.0,
            )
            content = resp.choices[0].message.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)
            if isinstance(result, list):
                return result
            return None
        except Exception as e:
            logger.warning("Batch describe LLM call failed: %s", e)
            return None


# 意图名别名映射 — LLM 可能返回非标准意图名
# 注：原 _INTENT_ALIASES / _SLOT_ALIASES 已删除
# Agent 模式（主路径）下 LLM 通过 Function Calling 调用 Tool，Tool 名是严格枚举
# Legacy 路径下 prompt 已要求 LLM 输出标准意图名和槽位名
# 若 LLM 返回非标准名，直接走 _handle_unrecognized 兜底，不再静默重映射


# 全局单例
_nlu: LlmNlu | None = None


def get_llm_nlu() -> LlmNlu:
    """获取 LLM NLU 单例"""
    global _nlu
    if _nlu is None:
        _nlu = LlmNlu()
    return _nlu
