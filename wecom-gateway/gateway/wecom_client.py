"""企业微信 API 客户端

封装企微服务端API调用：
- 获取/刷新 access_token（自动缓存）
- 下载媒体文件（用户上传的图片/语音）
- 发送文本/图文/markdown 消息
- 发送交互式卡片消息

参考: 企业微信API文档 v3
https://developer.work.weixin.qq.com/document/path/90313
"""

import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class WeComClient:
    """企业微信 API 客户端"""

    BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"

    def __init__(self, corp_id: str, secret: str, agent_id: str = ""):
        self.corp_id = corp_id
        self.secret = secret
        self.agent_id = agent_id
        self._access_token: Optional[str] = None
        self._token_expires: float = 0.0

    async def _get_token(self) -> str:
        """获取 access_token，带本地缓存"""
        # 提前5分钟刷新
        if self._access_token and time.time() < self._token_expires - 300:
            return self._access_token

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/gettoken",
                params={"corpid": self.corp_id, "corpsecret": self.secret},
            )
            data = resp.json()

        if data.get("errcode", 0) != 0:
            logger.error(f"获取 access_token 失败: {data}")
            raise RuntimeError(f"WeCom API error: {data.get('errmsg')}")

        self._access_token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 7200)
        logger.info("企业微信 access_token 已刷新")
        return self._access_token

    async def download_media(self, media_id: str) -> bytes:
        """下载媒体文件（图片/语音/文件）

        企微回调消息中只包含 media_id，需调用此接口下载实际文件内容
        """
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/media/get",
                params={"access_token": token, "media_id": media_id},
            )

        # 企微返回 json 错误 或 二进制文件
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            error_data = resp.json()
            logger.error(f"下载媒体失败: {error_data}")
            raise RuntimeError(f"Media download error: {error_data.get('errmsg')}")

        return resp.content

    async def send_text(self, user_id: str, content: str):
        """发送文本消息给用户"""
        token = await self._get_token()
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {"content": content},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE_URL}/message/send",
                params={"access_token": token},
                json=payload,
            )
        return self._check_response(resp.json())

    async def send_markdown(self, user_id: str, content: str):
        """发送 markdown 消息（企微支持有限 Markdown 语法）"""
        token = await self._get_token()
        payload = {
            "touser": user_id,
            "msgtype": "markdown",
            "agentid": self.agent_id,
            "markdown": {"content": content},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE_URL}/message/send",
                params={"access_token": token},
                json=payload,
            )
        return self._check_response(resp.json())

    async def send_textcard(
        self,
        user_id: str,
        title: str,
        description: str,
        url: str = "",
        btntxt: str = "详情",
    ):
        """发送文本卡片消息

        用于展示发票处理结果，用户可点击跳转详情页
        """
        token = await self._get_token()
        payload = {
            "touser": user_id,
            "msgtype": "textcard",
            "agentid": self.agent_id,
            "textcard": {
                "title": title,
                "description": description,
                "url": url,
                "btntxt": btntxt,
            },
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE_URL}/message/send",
                params={"access_token": token},
                json=payload,
            )
        return self._check_response(resp.json())

    async def send_news(self, user_id: str, articles: list[dict]):
        """发送图文消息（仅1条）

        articles 格式:
        [{
            "title": "报销汇总",
            "description": "共3张票据，总计1560元",
            "url": "https://...",
            "picurl": "https://..."
        }]
        """
        token = await self._get_token()
        payload = {
            "touser": user_id,
            "msgtype": "news",
            "agentid": self.agent_id,
            "news": {"articles": articles[:8]},  # 企微最多8条
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE_URL}/message/send",
                params={"access_token": token},
                json=payload,
            )
        return self._check_response(resp.json())

    async def get_user_detail(self, user_id: str) -> dict:
        """获取成员详细信息（通讯录API）

        需要在企微管理后台为自建应用开通「通讯录读取」权限。
        失败时返回空字典（非致命，调用方降级处理）。
        """
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/user/get",
                params={"access_token": token, "userid": user_id},
            )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            logger.warning(f"获取用户信息失败: {data.get('errmsg')}")
            return {}
        return data

    async def get_department_list(self) -> list[dict]:
        """获取部门列表（通讯录API）

        返回 [{"id": 1, "name": "总部", ...}, ...]
        失败时返回空列表。
        """
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/department/list",
                params={"access_token": token},
            )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            logger.warning(f"获取部门列表失败: {data.get('errmsg')}")
            return []
        return data.get("department", [])

    async def upload_file(self, file_data: bytes, filename: str, filetype: str = "file") -> str:
        """上传临时素材文件，返回 media_id

        filetype: image | voice | video | file
        用于发送文件/图片消息
        """
        token = await self._get_token()
        files = {"media": (filename, file_data)}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.BASE_URL}/media/upload",
                params={"access_token": token, "type": filetype},
                files=files,
            )
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"Upload error: {data.get('errmsg')}")
        return data.get("media_id", "")

    @staticmethod
    def _check_response(data: dict) -> dict:
        errcode = data.get("errcode", 0)
        if errcode != 0:
            logger.error(f"企微API返回错误: {data}")
            # access_token 过期时清除缓存
            if errcode in (40014, 42001):
                pass  # 下次请求会自动重新获取
        return data
