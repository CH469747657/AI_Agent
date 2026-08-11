"""对话上下文持久化存储

支持两种后端:
    - RedisContextStore: 生产级，对话上下文持久化到 Redis（跨进程/多实例）
    - MemoryContextStore: 开发/测试用，内存 dict 存储（单进程）

Key Schema:
    dialog:ctx:{user_id}  → JSON 序列化的 DialogContext

TTL:
    默认 24h，通过 DIALOG_CTX_TTL 环境变量可调。
    每次写入自动续期（滑动过期）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import redis.asyncio as aioredis

from .models import DialogContext, UserRole

logger = logging.getLogger(__name__)

# 默认 TTL：24 小时（秒）
DEFAULT_TTL = int(os.getenv("DIALOG_CTX_TTL", "86400"))

# Redis key 前缀
KEY_PREFIX = "dialog:ctx:"


class BaseContextStore:
    """上下文存储抽象基类"""

    async def get(self, user_id: str) -> Optional[DialogContext]:
        raise NotImplementedError

    async def set(self, ctx: DialogContext) -> None:
        raise NotImplementedError

    async def delete(self, user_id: str) -> None:
        raise NotImplementedError

    async def exists(self, user_id: str) -> bool:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class MemoryContextStore(BaseContextStore):
    """内存存储 — 开发/测试用，单进程"""

    def __init__(self):
        self._store: dict[str, dict] = {}

    async def get(self, user_id: str) -> Optional[DialogContext]:
        data = self._store.get(user_id)
        if data is None:
            return None
        return DialogContext.from_dict(data)

    async def set(self, ctx: DialogContext) -> None:
        self._store[ctx.user_id] = ctx.to_dict()

    async def delete(self, user_id: str) -> None:
        self._store.pop(user_id, None)

    async def exists(self, user_id: str) -> bool:
        return user_id in self._store


class RedisContextStore(BaseContextStore):
    """Redis 存储 — 生产级，支持跨进程/多实例

    连接参数从 config.settings.redis_url 读取。
    如果 Redis 不可用，自动降级到 MemoryContextStore（优雅降级）。
    """

    def __init__(self, redis_url: str, ttl: int = DEFAULT_TTL):
        self._redis_url = redis_url
        self._ttl = ttl
        self._redis: Optional[aioredis.Redis] = None
        self._fallback = MemoryContextStore()
        self._use_fallback = False

    async def _init(self) -> None:
        """初始化 Redis 连接"""
        if self._redis is not None:
            return
        try:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            # 健康检查
            await self._redis.ping()
            self._use_fallback = False
            logger.info("Redis context store connected: %s", self._redis_url)
        except Exception as e:
            logger.warning(
                "Redis unavailable (%s), falling back to memory store. "
                "Context will NOT survive process restarts.",
                e,
            )
            self._use_fallback = True
            self._redis = None

    def _key(self, user_id: str) -> str:
        return f"{KEY_PREFIX}{user_id}"

    async def get(self, user_id: str) -> Optional[DialogContext]:
        await self._init()
        if self._use_fallback:
            return await self._fallback.get(user_id)

        try:
            raw = await self._redis.get(self._key(user_id))
            if raw is None:
                return None
            return DialogContext.from_dict(json.loads(raw))
        except Exception as e:
            logger.error("Redis GET failed for user=%s: %s", user_id, e)
            return await self._fallback.get(user_id)

    async def set(self, ctx: DialogContext) -> None:
        await self._init()
        ctx.touch()
        if self._use_fallback:
            await self._fallback.set(ctx)
            return

        try:
            await self._redis.set(
                self._key(ctx.user_id),
                json.dumps(ctx.to_dict(), ensure_ascii=False),
                ex=self._ttl,
            )
        except Exception as e:
            logger.error("Redis SET failed for user=%s: %s", ctx.user_id, e)
            await self._fallback.set(ctx)

    async def delete(self, user_id: str) -> None:
        await self._init()
        if self._use_fallback:
            await self._fallback.delete(user_id)
            return

        try:
            await self._redis.delete(self._key(user_id))
        except Exception as e:
            logger.error("Redis DELETE failed for user=%s: %s", user_id, e)
            await self._fallback.delete(user_id)

    async def exists(self, user_id: str) -> bool:
        await self._init()
        if self._use_fallback:
            return await self._fallback.exists(user_id)

        try:
            return bool(await self._redis.exists(self._key(user_id)))
        except Exception as e:
            logger.error("Redis EXISTS failed for user=%s: %s", user_id, e)
            return await self._fallback.exists(user_id)

    async def health_check(self) -> dict:
        """健康检查 — 返回 Redis 状态信息"""
        info = {
            "backend": "redis" if not self._use_fallback else "memory_fallback",
            "redis_url": self._redis_url,
            "ttl": self._ttl,
        }
        if self._redis and not self._use_fallback:
            try:
                info["redis_ping"] = await self._redis.ping()
                info["redis_connected"] = True
                # 统计对话上下文 key 数量
                keys = await self._redis.keys(f"{KEY_PREFIX}*")
                info["active_contexts"] = len(keys)
            except Exception as e:
                info["redis_connected"] = False
                info["error"] = str(e)
        else:
            info["active_contexts"] = len(self._fallback._store)
        return info

    async def close(self) -> None:
        """关闭连接"""
        if self._redis:
            await self._redis.aclose()
            self._redis = None
