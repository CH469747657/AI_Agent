"""企业微信回调网关服务

FastAPI 应用，处理企业微信回调消息：
- GET  /wecom/callback  → 验证回调URL
- POST /wecom/callback  → 接收用户消息（图片/文字/语音）

消息处理流程：
1. 用户发送图片 → 下载媒体 → 转发base64到后端API → 异步返回结果
2. 用户发送文字 → 命令解析 / 无票报销 / 确认操作
3. 用户发送语音 → 语音识别转文字 → 复用文字处理流程

企微回调有5秒超时限制，因此所有处理都走异步：
- 收到消息后立即返回"正在处理"
- 后台处理完成后通过消息接口主动推送结果
"""

import os
import base64
import logging
import asyncio
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response, BackgroundTasks
import httpx

from gateway.crypto import WeComCrypto
from gateway.session import (
    SessionManager,
    STATE_IDLE, STATE_BATCH, STATE_WAIT_CATEGORY, STATE_WAIT_PROJECT,
    STATE_WAIT_REASON,
    CMD_HELP, CMD_DONE, CMD_CANCEL, CMD_QUERY, CMD_REPORT, CMD_NORECEIPT,
)
from gateway.wecom_client import WeComClient

# ===== 配置 =====
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")
WECOM_SECRET = os.getenv("WECOM_SECRET", "")
WECOM_TOKEN = os.getenv("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = os.getenv("WECOM_ENCODING_AES_KEY", "")
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8080")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/1")
WECOM_WEB_BASE = os.getenv("WECOM_WEB_BASE", "")  # 前端详情页基地址

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("wecom-gateway")

# ===== 全局实例 =====
crypto = WeComCrypto(WECOM_TOKEN, WECOM_ENCODING_AES_KEY, WECOM_CORP_ID)
wecom_client = WeComClient(WECOM_CORP_ID, WECOM_SECRET, WECOM_AGENT_ID)
session_mgr = SessionManager(REDIS_URL)
backend = httpx.AsyncClient(base_url=BACKEND_URL, timeout=120)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("企业微信网关服务启动")
    logger.info(f"  BACKEND_URL = {BACKEND_URL}")
    logger.info(f"  REDIS_URL   = {REDIS_URL}")
    yield
    await backend.aclose()
    logger.info("企业微信网关服务关闭")


app = FastAPI(title="AI报销-企微网关", lifespan=lifespan)


# ====================================================================
# 回调入口
# ====================================================================

@app.get("/wecom/callback")
async def verify_url(
    request: Request,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
):
    """企微回调URL验证（GET请求）

    企微后台配置回调URL时，会发送GET请求验证：
    解密 echostr 并原样返回明文即可
    """
    try:
        # 验证签名
        if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
            logger.warning("URL验证签名失败")
            return Response(content="signature error", status_code=403)

        # 解密 echostr
        plaintext = crypto.decrypt(echostr)
        logger.info("回调URL验证成功")
        return Response(content=plaintext, media_type="text/plain")
    except Exception as e:
        logger.error(f"URL验证异常: {e}")
        return Response(content=str(e), status_code=500)


@app.post("/wecom/callback")
async def receive_message(
    request: Request,
    background_tasks: BackgroundTasks,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
):
    """接收企微回调消息（POST请求）

    企微要求5秒内响应，否则会重试3次。
    策略：立即解密消息 → 返回空响应（不触发重试）→ 后台异步处理
    """
    body = await request.body()

    try:
        msg_dict = crypto.decrypt_message(body, msg_signature, timestamp, nonce)
    except Exception as e:
        logger.error(f"消息解密失败: {e}")
        return _empty_xml()

    msg_type = msg_dict.get("MsgType", "")
    from_user = msg_dict.get("FromUserName", "")
    to_user = msg_dict.get("ToUserName", "")

    logger.info(f"收到消息: type={msg_type}, from={from_user}")

    # 立即返回响应（防止企微超时重试），实际处理放到后台
    background_tasks.add_task(_dispatch_message, msg_dict, from_user)

    return _empty_xml()


# ====================================================================
# 消息分发 & 处理
# ====================================================================

async def _dispatch_message(msg_dict: dict, user_id: str):
    """消息分发调度器"""
    try:
        msg_type = msg_dict.get("MsgType", "")

        if msg_type == "image":
            await _handle_image(msg_dict, user_id)
        elif msg_type == "text":
            await _handle_text(msg_dict, user_id)
        elif msg_type == "voice":
            await _handle_voice(msg_dict, user_id)  # 预留
        elif msg_type == "event":
            await _handle_event(msg_dict, user_id)
        else:
            await wecom_client.send_text(
                user_id, f"暂不支持 {msg_type} 类型的消息，请发送图片或文字。"
            )
    except Exception as e:
        logger.error(f"消息处理异常: {e}", exc_info=True)
        await wecom_client.send_text(
            user_id, "处理过程中出现错误，请稍后重试或联系管理员。"
        )


async def _handle_image(msg_dict: dict, user_id: str):
    """处理图片消息 → 票据识别"""
    media_id = msg_dict.get("MediaId", "")

    # 先回复"正在处理"
    await wecom_client.send_text(user_id, "📋 正在识别票据，请稍候...")

    # 下载企微媒体文件
    file_data = await wecom_client.download_media(media_id)
    file_b64 = base64.b64encode(file_data).decode()

    # 调用后端处理API
    try:
        resp = await backend.post(
            "/api/invoices/wecom-process",
            json={
                "user_id": user_id,
                "file_data": file_b64,
                "file_type": "jpg",
                "receipt_type": "增值税普通发票",
                "description": "",
            },
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        logger.error(f"后端处理失败: {e}")
        await wecom_client.send_text(user_id, "❌ 票据处理失败，请重新发送或稍后重试。")
        return

    # 根据处理结果展示
    await _reply_invoice_result(user_id, result)

    # 检查是否需要后续交互（分类待确认等）
    await _check_pending_action(user_id, result)


async def _handle_text(msg_dict: dict, user_id: str):
    """处理文字消息 → 命令 / 无票报销 / 状态回复"""
    content = msg_dict.get("Content", "").strip()

    # 先获取会话状态
    state = await session_mgr.get_state(user_id)

    # ===== 处于待确认状态时优先处理 =====
    if state["state"] == STATE_WAIT_CATEGORY:
        await _handle_category_reply(user_id, content, state)
        return

    if state["state"] == STATE_WAIT_PROJECT:
        await _handle_project_reply(user_id, content, state)
        return

    if state["state"] == STATE_WAIT_REASON:
        await _handle_reason_reply(user_id, content, state)
        return

    # ===== 命令匹配 =====
    if content.lower() in CMD_HELP:
        await _send_help(user_id)
        return

    if content.lower() in CMD_DONE:
        await _handle_batch_done(user_id, state)
        return

    if content.lower() in CMD_CANCEL:
        await session_mgr.reset_to_idle(user_id)
        await wecom_client.send_text(user_id, "已取消当前操作。")
        return

    if content.lower() in CMD_QUERY:
        await _handle_query(user_id)
        return

    if content.lower() in CMD_REPORT:
        await _handle_report_request(user_id)
        return

    if content.lower() in CMD_NORECEIPT:
        # 进入无票报销信息收集模式
        await wecom_client.send_text(
            user_id,
            "📝 无票报销模式\n请描述：金额 + 说明\n例如：120元 去机场打车的出租车费"
        )
        await session_mgr.save_state(user_id, {**state, "state": "wait_amount"})
        return

    # ===== 无票报销金额输入 =====
    if state.get("state") == "wait_amount":
        await _handle_no_receipt(user_id, content)
        return

    # ===== 默认：视为票据描述补充 =====
    if state["state"] == STATE_BATCH and state.get("batch_invoice_ids"):
        # 将描述附加到最近一张暂存的发票
        last_invoice_id = state["batch_invoice_ids"][-1]
        await _update_invoice_description(user_id, last_invoice_id, content)
        await wecom_client.send_text(user_id, f"已补充说明到票据 #{last_invoice_id}")
        return

    # 未识别的文本
    await _send_help(user_id)


async def _handle_voice(msg_dict: dict, user_id: str):
    """处理语音消息

    企业微信管理后台开启「语音识别」后，语音消息回调 XML 自动带 Recognition 字段，
    内容为微信引擎识别出的文字。将其注入 Content，复用文字消息处理逻辑：
    - 识别到命令（帮助/查询/报表/无票/取消）→ 执行对应操作
    - 处于状态等待（分类/项目/事由/金额）→ 回复状态处理
    - 批量模式下 → 补充说明到最近票据
    - 无法匹配 → 发送帮助信息
    """
    recognition = msg_dict.get("Recognition", "").strip()
    if recognition:
        logger.info(f"Voice recognition from {user_id}: {recognition}")
        # 将语音识别文字注入 Content，完全复用 _handle_text 处理流程
        msg_dict["Content"] = recognition
        await _handle_text(msg_dict, user_id)
    else:
        # 未开启语音识别或识别为空
        logger.warning(f"Voice message from {user_id} has no Recognition field (speech-to-text not enabled?)")
        await wecom_client.send_text(
            user_id,
            "未识别到语音内容。请发送文字消息，或联系管理员在企业管理后台开启语音识别功能后重试。"
        )


async def _handle_event(msg_dict: dict, user_id: str):
    """处理事件消息（关注/取消关注/菜单点击等）"""
    event = msg_dict.get("Event", "")
    if event == "subscribe":
        await _send_welcome(user_id)
    elif event == "unsubscribe":
        await session_mgr.reset_to_idle(user_id)
    elif event == "CLICK":
        event_key = msg_dict.get("EventKey", "")
        await _handle_menu_click(user_id, event_key)


# ====================================================================
# 业务处理辅助函数
# ====================================================================

async def _reply_invoice_result(user_id: str, result: dict):
    """展示发票处理结果（Markdown 卡片）"""
    invoice_id = result.get("id", "?")
    invoice_num = result.get("invoice_number") or "(未识别到发票号)"
    seller = result.get("seller_name") or "(未识别)"
    amount = result.get("total_with_tax") or "0"
    date = result.get("issue_date") or "(未识别)"
    category = result.get("fee_subcategory") or "待分类"
    verify = result.get("verify_status", "unknown")
    duplicate = result.get("duplicate_status", "unknown")

    # 状态标记
    status_emoji = {
        "VALID": "✅",            # 验真通过
        "PENDING": "⏳",          # 待验真
        "INVALID": "❌",          # 验真失败
        "UNABLE_TO_VERIFY": "⚠️",  # 无法验真
    }.get(verify, "❓")

    dup_emoji = "🔴 重复!" if duplicate == "DUPLICATE" else ""

    md = (
        f"## 票据识别结果 #{invoice_id}\n"
        f"> **发票号**: {invoice_num}\n"
        f"> **销售方**: {seller}\n"
        f"> **金额**: ¥{amount}\n"
        f"> **日期**: {date}\n"
        f"> **分类**: {category}\n"
        f"> **验真**: {status_emoji} {verify}\n"
        f"> **查重**: {dup_emoji or '✅ 正常'}\n"
    )

    # 有冲突需人工确认
    if result.get("diff_conflicts"):
        md += "\n> ⚠️ OCR与AI识别结果存在差异，请人工复核\n"

    await wecom_client.send_markdown(user_id, md)


async def _check_pending_action(user_id: str, result: dict):
    """检查发票处理后是否需要用户补充信息"""
    state = await session_mgr.get_state(user_id)

    # 需确认费用分类
    if result.get("classify_source") == "manual_pending" or not result.get("fee_subcategory"):
        await session_mgr.set_pending(
            user_id,
            invoice_id=result["id"],
            pending_type="category",
        )
        options = [
            "投标费", "咨询费", "快递物流费", "办公费",
            "差旅-交通", "差旅-住宿", "差旅-餐饮", "培训费", "运营费", "其他",
        ]
        await wecom_client.send_text(
            user_id,
            f"该票据的分类不太确定，请回复数字选择：\n"
            + "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options))
        )

    # 需确认项目归属
    elif result.get("project_match_source") == "candidate":
        await session_mgr.set_pending(
            user_id,
            invoice_id=result["id"],
            pending_type="project",
        )
        await wecom_client.send_text(
            user_id,
            f"该票据涉及多个项目，请回复项目名称或编号进行归属确认。"
        )

    else:
        # 正常完成，加入批量
        await session_mgr.add_to_batch(user_id, result["id"])


async def _handle_category_reply(user_id: str, content: str, state: dict):
    """处理用户选择的费用分类"""
    options = state.get("pending_options") or [
        "投标费", "咨询费", "快递物流费", "办公费",
        "差旅-交通", "差旅-住宿", "差旅-餐饮", "培训费", "运营费", "其他",
    ]

    try:
        idx = int(content) - 1
        selected = options[idx]
    except (ValueError, IndexError):
        await wecom_client.send_text(user_id, "请回复正确的数字编号。")
        return

    invoice_id = state["pending_invoice_id"]

    # 更新后端数据：子分类写入 fee_subcategory，fee_category 保持不变
    await backend.put(
        f"/api/invoices/{invoice_id}",
        json={"fee_subcategory": selected},
    )

    await wecom_client.send_text(user_id, f"✅ 已设置为「{selected}」")
    await session_mgr.add_to_batch(user_id, invoice_id)
    await session_mgr.clear_pending(user_id)


async def _handle_project_reply(user_id: str, content: str, state: dict):
    """处理用户选择的项目"""
    invoice_id = state["pending_invoice_id"]
    # 简化：用户输入直接作为项目ID或关键词
    try:
        project_id = int(content)
    except ValueError:
        await wecom_client.send_text(
            user_id, "请回复项目的数字编号（可发送「查询」查看项目列表）。"
        )
        return

    await backend.put(
        f"/api/invoices/{invoice_id}",
        json={"project_id": project_id},
    )
    await wecom_client.send_text(user_id, f"✅ 已关联到项目 #{project_id}")
    await session_mgr.add_to_batch(user_id, invoice_id)
    await session_mgr.clear_pending(user_id)


async def _handle_no_receipt(user_id: str, content: str):
    """处理无票报销文字描述"""
    # 简单解析 "120元 去机场打车"
    amount = ""
    description = content
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*元?", content)
    if m:
        amount = m.group(1)
        description = content[m.end():].strip() or content

    try:
        resp = await backend.post(
            "/api/invoices/no-receipt",
            json={
                "user_id": user_id,
                "user_description": description,
                "amount": amount,
            },
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        logger.error(f"无票报销处理失败: {e}")
        await wecom_client.send_text(user_id, "❌ 处理失败，请稍后重试。")
        await session_mgr.reset_to_idle(user_id)
        return

    await _reply_invoice_result(user_id, result)
    await session_mgr.reset_to_idle(user_id)


async def _handle_batch_done(user_id: str, state: dict):
    """批量提交完成"""
    batch_ids = state.get("batch_invoice_ids", [])
    if not batch_ids:
        await wecom_client.send_text(user_id, "当前没有待提交的票据。")
        await session_mgr.reset_to_idle(user_id)
        return

    # 标记所有为已确认状态
    for invoice_id in batch_ids:
        try:
            await backend.put(
                f"/api/invoices/{invoice_id}",
                json={"status": "CONFIRMED"},
            )
        except Exception:
            pass

    await wecom_client.send_text(
        user_id,
        f"✅ 已提交 {len(batch_ids)} 张票据进入报销流程。"
    )
    await session_mgr.reset_to_idle(user_id)


async def _handle_query(user_id: str):
    """查询用户发票统计"""
    try:
        resp = await backend.get(f"/api/wecom/invoices/{user_id}")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"查询失败: {e}")
        await wecom_client.send_text(user_id, "查询失败，请稍后重试。")
        return

    count = data.get("count", 0)
    total = data.get("total_amount", 0)

    if count == 0:
        await wecom_client.send_text(user_id, "您还没有任何票据记录。")
        return

    items_text = ""
    for i, item in enumerate(data.get("items", []), 1):
        dup = " 🔴重复" if item.get("is_duplicate") else ""
        items_text += (
            f"\n{i}. {item.get('seller', '?')} ¥{item.get('amount', 0)}"
            f" [{item.get('category', '?')}]{dup}"
        )

    await wecom_client.send_markdown(
        user_id,
        f"## 您的票据汇总\n> 共 **{count}** 张，总计 **¥{total}**{items_text}",
    )


async def _handle_report_request(user_id: str):
    """报表导出请求：先收集报销事由，再创建报销单 → 关联发票 → 生成报表"""
    try:
        # 1. 查询用户已确认的发票
        inv_resp = await backend.get(f"/api/invoices?user_id={user_id}&status=CONFIRMED")
        inv_resp.raise_for_status()
        invoices = inv_resp.json()

        if not invoices:
            await wecom_client.send_text(user_id, "您没有已确认的票据，无法生成报表。请先发送发票图片进行识别。")
            return

        invoice_ids = [inv["id"] for inv in invoices]

        # 2. 保存发票列表到会话，进入报销事由收集状态
        state = await session_mgr.get_state(user_id)
        state["state"] = STATE_WAIT_REASON
        state["report_invoice_ids"] = invoice_ids
        await session_mgr.save_state(user_id, state)

        await wecom_client.send_text(
            user_id,
            f"您有 {len(invoice_ids)} 张已确认的票据，需要创建报销单。\n"
            "请输入报销事由（如：XX项目差旅费），或发送「跳过」跳过此步骤。"
        )
    except Exception as e:
        logger.error(f"报表请求失败: {e}")
        await wecom_client.send_text(user_id, "操作失败，请稍后重试。")


async def _handle_reason_reply(user_id: str, content: str, state: dict):
    """处理报销事由输入 → 创建报销单 → 生成报表"""
    # 允许取消
    if content.strip().lower() in CMD_CANCEL:
        await session_mgr.reset_to_idle(user_id)
        await wecom_client.send_text(user_id, "已取消报表生成。")
        return

    reason = "" if content.strip() in ("跳过", "无", "skip") else content.strip()
    invoice_ids = state.get("report_invoice_ids", [])

    if not invoice_ids:
        await wecom_client.send_text(user_id, "会话已过期，请重新发送「报表」。")
        await session_mgr.reset_to_idle(user_id)
        return

    # 自动获取员工姓名和部门（通讯录API）
    applicant_name = None
    department = None
    try:
        user_detail = await wecom_client.get_user_detail(user_id)
        if user_detail:
            applicant_name = user_detail.get("name")
            dept_ids = user_detail.get("department", [])
            if dept_ids:
                dept_list = await wecom_client.get_department_list()
                dept_map = {d["id"]: d.get("name", "") for d in dept_list}
                department = dept_map.get(dept_ids[0])
    except Exception as e:
        logger.warning(f"获取用户信息失败（非致命）: {e}")

    try:
        # 创建报销单并关联发票
        reimb_resp = await backend.post(
            "/api/reimbursements",
            json={
                "applicant_id": user_id,
                "applicant_name": applicant_name,
                "department": department,
                "reason": reason or None,
                "invoice_ids": invoice_ids,
            },
        )
        reimb_resp.raise_for_status()
        reimb_data = reimb_resp.json()
        reimb_id = reimb_data["id"]

        # 自动提交报销单（DRAFT → SUBMITTED）
        try:
            submit_resp = await backend.put(f"/api/reimbursements/{reimb_id}/submit")
            submit_resp.raise_for_status()
            logger.info(f"报销单 #{reimb_id} 已自动提交")
        except Exception as e:
            logger.warning(f"报销单 #{reimb_id} 自动提交失败（非致命）: {e}")

        # 生成报表
        report_resp = await backend.post(f"/api/reports/generate/{reimb_id}")
        report_resp.raise_for_status()
        report_data = report_resp.json()
    except Exception as e:
        logger.error(f"报表生成失败: {e}")
        await wecom_client.send_text(user_id, "报表生成失败，请稍后重试。")
        await session_mgr.reset_to_idle(user_id)
        return

    files = report_data.get("files", {})
    file_names = {k: os.path.basename(v) for k, v in files.items() if v}

    reason_line = f"> 报销事由: **{reason}**\n" if reason else ""
    md = (
        f"## 📊 报表已生成\n"
        f"> 报销单编号: **#{reimb_id}**（已提交）\n"
        f"> 关联票据: **{len(invoice_ids)}** 张\n"
        f"> 总金额: **¥{reimb_data.get('total_amount', 0)}**\n"
        f"{reason_line}"
        f">\n"
        f"> 可下载文件:\n"
    )
    for fmt in ["excel", "pdf", "zip"]:
        if fmt in file_names:
            md += f"> - [{file_names[fmt]}]({WECOM_WEB_BASE}/reports/{reimb_id})\n"

    await wecom_client.send_markdown(user_id, md)
    await session_mgr.reset_to_idle(user_id)


async def _handle_menu_click(user_id: str, event_key: str):
    """处理菜单点击事件"""
    if event_key == "upload_receipt":
        await wecom_client.send_text(
            user_id, "请直接发送发票图片，支持多张连续发送。"
        )
        await session_mgr.start_batch(user_id)
    elif event_key == "no_receipt":
        await wecom_client.send_text(
            user_id,
            "📝 无票报销模式\n请描述：金额 + 说明\n例如：120元 去机场打车的出租车费"
        )
        state = await session_mgr.get_state(user_id)
        await session_mgr.save_state(user_id, {**state, "state": "wait_amount"})
    elif event_key == "query_status":
        await _handle_query(user_id)
    elif event_key == "generate_report":
        await _handle_report_request(user_id)
    else:
        await _send_help(user_id)


async def _update_invoice_description(user_id: str, invoice_id: int, description: str):
    """更新发票的用户补充描述"""
    try:
        await backend.put(
            f"/api/invoices/{invoice_id}",
            json={"user_description": description},
        )
    except Exception:
        pass


# ====================================================================
# 辅助函数
# ====================================================================

def _category_to_enum(name: str) -> str:
    """费用子类名称 → 费用大类枚举值（personal/company）

    已废弃：子分类不再映射到 fee_category。
    保留函数以兼容，默认返回 company。
    """
    return "company"


async def _send_welcome(user_id: str):
    """新关注欢迎语"""
    await wecom_client.send_markdown(
        user_id,
        "## 👋 欢迎使用发票报销智能助手\n"
        "我可以帮你：\n"
        "- 📷 发送发票图片自动识别\n"
        "- 📝 无票报销文字描述\n"
        "- 📊 查询票据汇总\n"
        "- 📋 导出报销报表\n\n"
        "发送 **帮助** 查看完整功能说明",
    )


async def _send_help(user_id: str):
    """帮助说明"""
    await wecom_client.send_markdown(
        user_id,
        "## 🔧 功能说明\n"
        "**发送图片** — 上传发票自动识别\n"
        "**完成** — 提交批量票据\n"
        "**取消** — 取消当前操作\n"
        "**查询** — 查看我的票据\n"
        "**报表** — 生成报销报表\n"
        "**无票** — 无票报销文字描述",
    )


def _empty_xml() -> Response:
    """返回空XML响应（企微要求返回text/xml）"""
    return Response(content="", media_type="text/xml")


# ====================================================================
# 健康检查
# ====================================================================

@app.get("/health")
async def health():
    return {"status": "ok", "service": "wecom-gateway"}
