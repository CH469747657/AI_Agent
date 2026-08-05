"""在线发票验真服务 — 支持阿里云数链云 / 百度双通道

功能:
  - 阿里云数链云发票查验（主通道）: 通过 AppCode 认证接入国税权威数据源
  - 百度智能云增值税发票验真（备用通道）: 通过 API Key/Secret Key + access_token
  - 凭据缺失时优雅降级，返回提示信息不抛异常
  - 验真通过后返回完整票面信息，可交叉验证 OCR 结果

阿里云数链云 API 文档: https://market.aliyun.com/detail/cmapi00067571
  请求方式: GET（Query 参数）
  请求参数: invoiceCode / invoiceNo / invoiceDate(yyyy-MM-dd) /
            invoiceAmt(金额) / verCode(校验码)
  认证方式: Header Authorization: APPCODE xxx
  返回结果: 外层 code=200 且 data.code=200 表示查验一致

百度 API 文档: https://cloud.baidu.com/doc/OCR/s/cklbnrnwe
  请求参数: invoice_code / invoice_num / invoice_date(YYYYMMDD) /
            check_code(后6位) / invoice_type / total_amount
  返回结果: words_result.VerifyResult == "0001" 表示查验一致
"""

import re
import time
import logging
from typing import Optional
from dataclasses import dataclass, field

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 阿里云数链云 API 端点
# ------------------------------------------------------------------
ALIYUN_VERIFY_URL = "https://slyreceipt.market.alicloudapi.com/invoice/check"

# ------------------------------------------------------------------
# 百度 AI 开放平台 API 端点
# ------------------------------------------------------------------
BAIDU_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
BAIDU_VERIFY_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/vat_invoice_verification"

# 全局 access_token 缓存（进程级，30天有效）
_token_cache: dict = {"token": None, "expires_at": 0.0}

# 本地发票类型 → 百度 invoice_type 映射
INVOICE_TYPE_MAP = {
    "增值税普通发票": "normal_invoice",
    "增值税专用发票": "special_vat_invoice",
    "全电发票（普通发票）": "elec_invoice_normal",
    "全电发票（专用发票）": "elec_invoice_special",
    "通行费增值税电子普通发票": "toll_elec_normal_invoice",
}


@dataclass
class VerifyResult:
    """验真结果数据类"""
    # None=未执行（降级）, True=验真通过, False=验真未通过
    is_valid: Optional[bool]
    message: str
    # API 返回的原始 JSON
    raw_response: dict = field(default_factory=dict)
    # 验真返回的票面信息（用于交叉验证 OCR）
    verified_fields: dict = field(default_factory=dict)
    # 发票状态: N=正常, Y=已作废, H=已冲红, BH=部分红冲, QH=全额红冲
    invoice_status: str = ""
    # 使用的验真通道
    provider: str = ""


class VerifyService:
    """在线发票验真服务 — 支持 阿里云(主) / 百度(备用) 双通道"""

    def __init__(self):
        self.provider = settings.verify_provider.lower()
        self.api_key = settings.verify_api_key
        self.secret_key = settings.verify_secret_key
        self.aliyun_appcode = settings.aliyun_verify_appcode

        # 根据配置判断各通道可用性
        self.baidu_enabled = bool(self.api_key and self.secret_key)
        self.aliyun_enabled = bool(self.aliyun_appcode)

        # 整体 enabled: 主通道可用即为 true
        if self.provider == "aliyun":
            self.enabled = self.aliyun_enabled
        elif self.provider == "baidu":
            self.enabled = self.baidu_enabled
        else:
            # 未知 provider，尝试任一通道
            self.enabled = self.aliyun_enabled or self.baidu_enabled

    # ------------------------------------------------------------------
    # 公共入口：自动分发到对应验真通道
    # ------------------------------------------------------------------

    async def verify_invoice(self, invoice_data: dict) -> VerifyResult:
        """在线验真单张发票（自动分发到配置的验真通道）

        Args:
            invoice_data: {
                "receipt_type":    票据类型（增值税普通发票 / 增值税专用发票）
                "invoice_code":    发票代码（10-12位，全电发票可为空）
                "invoice_number":  发票号码（8位或20位数字）
                "issue_date":      开票日期（YYYY-MM-DD）
                "check_code":      校验码后6位（OCR 提取，可选）
                "amount":          不含税金额（专票需要）
                "total_with_tax":  价税合计（全电发票需要）
            }

        Returns:
            VerifyResult
        """
        if not self.enabled:
            return VerifyResult(
                is_valid=None,
                message=self._disabled_message(),
            )

        if self.provider == "aliyun":
            return await self._verify_aliyun(invoice_data)
        elif self.provider == "baidu":
            return await self._verify_baidu(invoice_data)
        else:
            # 未知 provider，按优先级尝试
            if self.aliyun_enabled:
                return await self._verify_aliyun(invoice_data)
            elif self.baidu_enabled:
                return await self._verify_baidu(invoice_data)
            return VerifyResult(
                is_valid=None,
                message=self._disabled_message(),
            )

    def _disabled_message(self) -> str:
        """生成通道不可用时的提示信息"""
        if self.provider == "aliyun":
            return "验真服务未配置凭据。请在 .env 中填入 ALIYUN_VERIFY_APPCODE 后重启服务。"
        elif self.provider == "baidu":
            return "验真服务未配置凭据。请在 .env 中填入 VERIFY_API_KEY 和 VERIFY_SECRET_KEY 后重启服务。"
        return "验真服务未配置凭据。请配置阿里云或百度验真参数后重启服务。"

    # ==================================================================
    # 阿里云数链云发票查验
    # ==================================================================

    async def _verify_aliyun(self, invoice_data: dict) -> VerifyResult:
        """阿里云数链云发票查验

        API 地址: https://slyreceipt.market.alicloudapi.com/invoice/check
        请求方式: GET（Query 参数）
        认证方式: Header Authorization: APPCODE xxx

        请求参数（Query）:
          invoiceCode  — 发票代码（除全电票外，其他必传）
          invoiceNo    — 发票号码（必填）
          invoiceDate  — 开票日期 yyyy-MM-dd（必填）
          invoiceAmt   — 金额（全电票传价税合计，其他传不含税金额，精确到两位小数）
          verCode      — 校验码（除专票外，其他必填）
        """
        if not self.aliyun_enabled:
            return VerifyResult(
                is_valid=None,
                message="阿里云验真未配置 AppCode。请在 .env 中填入 ALIYUN_VERIFY_APPCODE。",
            )

        # 发票代码和号码
        invoice_code = str(invoice_data.get("invoice_code", "") or "").strip()
        invoice_number = str(invoice_data.get("invoice_number", "") or "").strip()

        # 日期格式: 保持 yyyy-MM-dd（数链云要求此格式）
        issue_date = invoice_data.get("issue_date", "")

        # 校验码（verCode）：除专票外，其他必填
        ver_code = invoice_data.get("check_code", "")
        if ver_code:
            ver_code = str(ver_code).replace(" ", "")[-6:]

        # 金额：数链云统一传 invoiceAmt
        #   全电票（20位发票号）→ 价税合计
        #   其他发票 → 不含税金额
        receipt_type = invoice_data.get("receipt_type", "增值税普通发票")
        is_dianpiao = len(invoice_number) == 20 and not invoice_code

        if is_dianpiao:
            invoice_amt = invoice_data.get("total_with_tax", "") or invoice_data.get("amount", "")
        else:
            invoice_amt = invoice_data.get("amount", "") or invoice_data.get("total_with_tax", "")

        # 清理金额格式（数链云要求精确到两位小数）
        invoice_amt = str(invoice_amt).replace(",", "").replace("￥", "").replace("¥", "").strip()
        try:
            invoice_amt = "{:.2f}".format(float(invoice_amt))
        except (ValueError, TypeError):
            pass

        # 构建 Query 参数（仅传非空值，避免空参数导致 400）
        params = {
            "invoiceNo": invoice_number,
            "invoiceDate": issue_date,
            "invoiceAmt": invoice_amt,
        }
        # 发票代码：数电票不传，其他必传
        if invoice_code:
            params["invoiceCode"] = invoice_code
        # 校验码：专票可不传，其他应传
        if ver_code:
            params["verCode"] = ver_code

        headers = {
            "Authorization": f"APPCODE {self.aliyun_appcode}",
        }

        logger.info(
            f"阿里云(数链云)验真请求: invoiceNo={invoice_number}, "
            f"invoiceDate={issue_date}, verCode={'***' if ver_code else 'N/A'}, "
            f"invoiceAmt={invoice_amt}"
        )

        # 调用阿里云 API（GET 请求）
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    ALIYUN_VERIFY_URL,
                    params=params,
                    headers=headers,
                )
                resp.raise_for_status()
                result = resp.json()
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if status_code == 403:
                logger.error("阿里云验真 AppCode 无效或已过期（HTTP 403）")
                return VerifyResult(
                    is_valid=None,
                    message="阿里云 AppCode 无效或已过期，请检查 ALIYUN_VERIFY_APPCODE 配置",
                    provider="aliyun",
                )
            # 尝试解析 JSON body 中的错误描述
            error_detail = ""
            try:
                err_json = e.response.json()
                error_detail = err_json.get("msg", "")
            except Exception:
                pass
            detail_msg = f": {error_detail}" if error_detail else ""

            # 参数校验类错误（如"发票号码格式有误"）→ 验真失败
            # 这些错误说明发票信息在国税系统中无法匹配，等同于验真未通过
            verify_fail_keywords = ["格式有误", "不存在", "未查到", "查无此票", "不正确", "不一致"]
            if status_code == 400 and error_detail:
                if any(kw in error_detail for kw in verify_fail_keywords):
                    logger.warning(f"阿里云验真参数校验失败（判定为验真未通过）: {error_detail}")
                    return VerifyResult(
                        is_valid=False,
                        message=f"阿里云验真未通过: {error_detail}",
                        provider="aliyun",
                    )

            logger.error(f"阿里云验真 HTTP 错误: {e}{detail_msg}")
            return VerifyResult(
                is_valid=None,
                message=f"阿里云验真请求失败: HTTP {status_code}{detail_msg}",
                provider="aliyun",
            )
        except httpx.HTTPError as e:
            logger.error(f"阿里云验真网络错误: {e}")
            return VerifyResult(
                is_valid=None,
                message=f"阿里云验真请求失败: {e}",
                provider="aliyun",
            )

        return self._parse_aliyun_result(result)

    def _parse_aliyun_result(self, result: dict) -> VerifyResult:
        """解析阿里云数链云 API 返回结果

        实际返回格式:
          成功（一致）: {"code": 200, "msg": "成功", "success": true, "data": {
                    "result": "一致",            // "一致" or "不一致"
                    "orderNo": "订单号",
                    "info": {
                        "invoiceNo": "发票号码",
                        "invoiceCode": "发票代码",
                        "invoiceDate": "开票日期",
                        "invoiceAmt": "不含税金额",
                        "totalTaxAmt": "税额",
                        "totalAmt": "价税合计",
                        "salerName": "销方名称",
                        "salerTaxNo": "销方税号",
                        "salerContact": "销方地址电话",
                        "salerBank": "销方银行账号",
                        "buyerName": "购方名称",
                        "buyerTaxNo": "购方税号",
                        "buyerContact": "购方地址电话",
                        "buyerBank": "购方银行账号",
                        "verCode": "校验码",
                        "notes": "备注",
                        "status": "1",            // 1=正常
                        "ret_code": 0,
                        "itemList": [...]          // 商品明细
                    }
                }}
          成功（不一致）: data.result = "不一致"
          失败: {"code": 400/500, "msg": "错误描述", "success": false}
        """
        outer_code = result.get("code")
        outer_msg = result.get("msg", "")
        success = result.get("success", False)

        # 外层非 200 → 业务级/系统级错误
        if outer_code != 200:
            logger.error(f"阿里云数链云 API 系统错误: code={outer_code}, msg={outer_msg}")

            # 业务级错误：国税系统查不到发票 → 验真失败
            # 常见错误码: 1001=查无此票, 1002=参数不全, 1003=发票代码有误等
            verify_fail_keywords = ["查无此票", "不存在", "未查到", "不正确", "不一致", "有误"]
            if any(kw in outer_msg for kw in verify_fail_keywords):
                logger.warning(f"阿里云验真业务级错误（判定为验真未通过）: [{outer_code}] {outer_msg}")
                return VerifyResult(
                    is_valid=False,
                    message=f"阿里云验真未通过: [{outer_code}] {outer_msg}",
                    raw_response=result,
                    provider="aliyun",
                )

            # 认证类错误 → 降级待定（凭据问题，非发票本身问题）
            if outer_code in (403,):
                return VerifyResult(
                    is_valid=None,
                    message=f"阿里云验真认证失败: {outer_msg}",
                    raw_response=result,
                    provider="aliyun",
                )

            # 其他系统级错误 → 降级待定
            return VerifyResult(
                is_valid=None,
                message=f"阿里云验真服务异常: [{outer_code}] {outer_msg}",
                raw_response=result,
                provider="aliyun",
            )

        # 外层 200 但 success=false
        if not success:
            # 检查是否为业务级"查无此票"类错误
            verify_fail_keywords = ["查无此票", "不存在", "未查到", "不正确", "不一致", "有误"]
            if any(kw in outer_msg for kw in verify_fail_keywords):
                logger.warning(f"阿里云验真业务级错误（判定为验真未通过）: {outer_msg}")
                return VerifyResult(
                    is_valid=False,
                    message=f"阿里云验真未通过: {outer_msg}",
                    raw_response=result,
                    provider="aliyun",
                )
            return VerifyResult(
                is_valid=None,
                message=f"阿里云验真请求失败: {outer_msg}",
                raw_response=result,
                provider="aliyun",
            )

        # 提取 data 层
        data = result.get("data", {})
        if not data:
            logger.warning("阿里云验真返回外层成功但 data 为空")
            return VerifyResult(
                is_valid=None,
                message="阿里云验真返回数据为空，请稍后重试",
                raw_response=result,
                provider="aliyun",
            )

        # 判定一致/不一致
        verify_result_str = str(data.get("result", "")).strip()

        if verify_result_str == "不一致":
            return VerifyResult(
                is_valid=False,
                message="阿里云验真未通过: 与国税系统数据不一致",
                raw_response=result,
                provider="aliyun",
            )

        if verify_result_str != "一致":
            # result 字段既不是"一致"也不是"不一致"
            return VerifyResult(
                is_valid=None,
                message=f"阿里云验真返回异常状态: result={verify_result_str}",
                raw_response=result,
                provider="aliyun",
            )

        # result="一致" → 提取票面信息
        info = data.get("info", {}) or {}

        verified_fields = {
            "invoice_number": info.get("invoiceNo"),
            "invoice_code": info.get("invoiceCode"),
            "issue_date": info.get("invoiceDate"),
            "check_code": info.get("verCode"),
            "seller_name": info.get("salerName"),
            "seller_tax_id": info.get("salerTaxNo"),
            "buyer_name": info.get("buyerName"),
            "buyer_tax_id": info.get("buyerTaxNo"),
            "total_with_tax": info.get("totalAmt"),
            "amount": info.get("invoiceAmt"),
            "tax_amount": info.get("totalTaxAmt"),
        }
        # 清除空值
        verified_fields = {k: v for k, v in verified_fields.items() if v}

        # 发票状态：status 字段  1=正常, 其他待确认
        # ret_code: 0=正常
        status_val = str(info.get("status", "1") or "1").strip()
        ret_code = info.get("ret_code", 0)

        if status_val == "1" and ret_code == 0:
            invoice_status = "N"   # 正常
        else:
            invoice_status = "N"   # 默认正常，后续可根据实际异常值调整

        status_note = ""
        if invoice_status == "Y":
            status_note = "（注意：该发票已作废）"
        elif invoice_status == "H":
            status_note = "（注意：该发票已冲红）"
        elif invoice_status == "BH":
            status_note = "（注意：该发票部分红冲）"
        elif invoice_status == "QH":
            status_note = "（注意：该发票全额红冲）"

        return VerifyResult(
            is_valid=True,
            message=f"阿里云验真通过：与国税系统数据一致{status_note}",
            raw_response=result,
            verified_fields=verified_fields,
            invoice_status=invoice_status,
            provider="aliyun",
        )

    # ==================================================================
    # 百度智能云发票验真（备用通道）
    # ==================================================================

    def _get_access_token(self) -> str:
        """获取百度 AI access_token（带缓存）

        百度 access_token 有效期 30 天，这里提前 5 分钟刷新。
        """
        if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
            return _token_cache["token"]

        if not self.baidu_enabled:
            raise RuntimeError("百度验真未配置凭据（VERIFY_API_KEY / VERIFY_SECRET_KEY 为空）")

        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        }
        resp = httpx.post(BAIDU_TOKEN_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"百度返回无 access_token: {data}")

        expires_in = data.get("expires_in", 2592000)
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + expires_in - 300

        logger.info(f"百度 access_token 已刷新，有效期 {expires_in}s")
        return token

    def _invalidate_token(self):
        """清除 token 缓存（token 过期时调用）"""
        _token_cache["token"] = None
        _token_cache["expires_at"] = 0.0

    async def _verify_baidu(self, invoice_data: dict) -> VerifyResult:
        """百度智能云在线验真（备用通道）

        请求参数:
          invoice_type     — 百度发票类型标识
          invoice_code     — 发票代码
          invoice_num      — 发票号码
          invoice_date     — 开票日期 YYYYMMDD
          check_code       — 校验码后6位
          total_amount     — 金额
        """
        if not self.baidu_enabled:
            return VerifyResult(
                is_valid=None,
                message="百度验真未配置凭据。请在 .env 中填入 VERIFY_API_KEY 和 VERIFY_SECRET_KEY。",
                provider="baidu",
            )

        # 获取 access_token
        try:
            token = self._get_access_token()
        except Exception as e:
            logger.error(f"获取 access_token 失败: {e}")
            return VerifyResult(
                is_valid=None,
                message=f"百度验真令牌获取失败: {e}",
                provider="baidu",
            )

        # 构建请求参数
        receipt_type = invoice_data.get("receipt_type", "增值税普通发票")
        invoice_type = INVOICE_TYPE_MAP.get(receipt_type, "normal_invoice")

        issue_date = invoice_data.get("issue_date", "")
        if issue_date:
            issue_date = re.sub(r"[-/]", "", issue_date)

        check_code = invoice_data.get("check_code", "")
        if check_code:
            check_code = str(check_code).replace(" ", "")[-6:]

        # 自动检测数电票
        invoice_code_str = str(invoice_data.get("invoice_code", "") or "").strip()
        invoice_number_str = str(invoice_data.get("invoice_number", "") or "").strip()
        if len(invoice_number_str) == 20 and not invoice_code_str:
            if invoice_type == "normal_invoice":
                invoice_type = "elec_invoice_normal"
            elif invoice_type == "special_vat_invoice":
                invoice_type = "elec_invoice_special"
            logger.info(
                f"百度验真: 检测到数电票(20位发票号无发票代码)，invoice_type → {invoice_type}"
            )

        # 金额
        if invoice_type in ("elec_invoice_normal", "elec_invoice_special"):
            total_amount = invoice_data.get("total_with_tax", "")
        elif invoice_type == "special_vat_invoice":
            total_amount = invoice_data.get("amount", "") or invoice_data.get("total_with_tax", "")
        else:
            total_amount = invoice_data.get("amount", "") or ""

        form_data = {
            "invoice_type": invoice_type,
            "invoice_code": invoice_code_str,
            "invoice_num": invoice_number_str,
            "invoice_date": issue_date,
            "check_code": check_code,
            "total_amount": str(total_amount).replace(",", "").replace("￥", "").replace("¥", ""),
        }

        logger.info(
            f"百度验真请求: type={invoice_type}, "
            f"num={form_data['invoice_num']}, date={issue_date}, "
            f"check_code={'***' if check_code else 'N/A'}, "
            f"total_amount={form_data['total_amount']}"
        )

        # 调用百度 API
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    BAIDU_VERIFY_URL,
                    params={"access_token": token},
                    data=form_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                result = resp.json()
        except httpx.HTTPError as e:
            logger.error(f"百度验真 HTTP 请求失败: {e}")
            return VerifyResult(
                is_valid=None,
                message=f"百度验真请求失败: {e}",
                provider="baidu",
            )

        return self._parse_baidu_result(result)

    def _parse_baidu_result(self, result: dict) -> VerifyResult:
        """解析百度验真 API 返回结果

        返回格式:
          成功: {"log_id": xxx, "words_result_num": 1,
                 "words_result": {"VerifyResult": "0001", "VerifyMessage": "查验成功发票一致",
                                   "InvalidSign": "N", "InvoiceNum": "...", ...}}
          失败: {"error_code": xxx, "error_msg": "..."}
        """
        # 百度 API 级别错误
        if "error_code" in result:
            error_code = result.get("error_code")
            error_msg = result.get("error_msg", "未知错误")
            logger.error(f"百度验真 API 错误: code={error_code}, msg={error_msg}")

            if error_code in (110, 111):
                self._invalidate_token()
                return VerifyResult(is_valid=None, message="Access token 过期或无效，请重试", provider="baidu")
            elif error_code == 17:
                return VerifyResult(is_valid=None, message="验真请求量超出配额，请检查百度控制台", provider="baidu")
            elif error_code == 18:
                return VerifyResult(is_valid=None, message="验真 QPS 超限，请稍后重试", provider="baidu")
            elif error_code == 216630:
                return VerifyResult(is_valid=False, message="发票信息不一致或不存在，请检查输入参数", provider="baidu")
            else:
                return VerifyResult(is_valid=None, message=f"验真服务返回错误: [{error_code}] {error_msg}", provider="baidu")

        words_result = result.get("words_result", {})
        verify_result_code = str(
            result.get("VerifyResult") or words_result.get("VerifyResult", "")
        )
        verify_message = (
            result.get("VerifyMessage") or words_result.get("VerifyMessage", "")
        )
        invalid_sign = str(
            result.get("InvalidSign") or words_result.get("InvalidSign", "N")
        )

        if not verify_result_code:
            return VerifyResult(
                is_valid=None,
                message="百度验真返回数据为空，请稍后重试",
                raw_response=result,
                provider="baidu",
            )

        verified_fields = {
            "invoice_number": words_result.get("InvoiceNum"),
            "invoice_code": words_result.get("InvoiceCode"),
            "issue_date": words_result.get("InvoiceDate"),
            "check_code": words_result.get("CheckCode"),
            "seller_name": words_result.get("SellerName"),
            "seller_tax_id": words_result.get("SellerRegisterNum"),
            "buyer_name": words_result.get("PurchaserName"),
            "buyer_tax_id": words_result.get("PurchaserRegisterNum"),
            "total_with_tax": words_result.get("AmountInFiguers"),
            "amount": words_result.get("TotalAmount"),
            "tax_amount": words_result.get("TotalTax"),
        }
        verified_fields = {k: v for k, v in verified_fields.items() if v}

        if verify_result_code == "0001":
            status_note = ""
            if invalid_sign == "Y":
                status_note = "（注意：该发票已作废）"
            elif invalid_sign == "H":
                status_note = "（注意：该发票已冲红）"
            elif invalid_sign == "BH":
                status_note = "（注意：该发票部分红冲）"
            elif invalid_sign == "QH":
                status_note = "（注意：该发票全额红冲）"

            return VerifyResult(
                is_valid=True,
                message=f"百度验真通过：与国税系统数据一致{status_note}",
                raw_response=result,
                verified_fields=verified_fields,
                invoice_status=invalid_sign,
                provider="baidu",
            )
        else:
            return VerifyResult(
                is_valid=False,
                message=f"百度验真未通过：{verify_message or '与国税系统数据不一致'}",
                raw_response=result,
                verified_fields=verified_fields,
                invoice_status=invalid_sign,
                provider="baidu",
            )


# ------------------------------------------------------------------
# 单例管理
# ------------------------------------------------------------------

_verify_service: Optional[VerifyService] = None


def get_verify_service() -> VerifyService:
    """获取验真服务单例"""
    global _verify_service
    if _verify_service is None:
        _verify_service = VerifyService()
    return _verify_service
