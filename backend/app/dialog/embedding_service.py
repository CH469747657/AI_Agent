"""Embedding Service — 文本向量化服务（Step 2.1.2）

为 RAG 意图检索提供 embedding 计算，支持两种后端：

1. **dashscope**（默认）：调用阿里云 text-embedding-v2，无需本地依赖，质量好
2. **local**：使用 sentence-transformers + bge-small-zh，离线可用，零成本

后端选择通过环境变量 LLM_EMBEDDING_BACKEND 控制（dashscope / local）。

设计要点：
- 内存缓存：相同文本不重复调 API，避免意图 embedding 重复计算
- 批量接口：支持一次 embedding 多条文本（intent typical_utterances 批量预计算）
- 优雅降级：API 失败时返回零向量，让 retriever 自然过滤
- 异步接口：dashscope 调用走 asyncio.to_thread，不阻塞事件循环
"""

from __future__ import annotations

import logging
import os
import asyncio
import hashlib
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ============================================================
# 配置
# ============================================================

# embedding 后端：dashscope（默认）或 local
EMBEDDING_BACKEND = os.getenv("LLM_EMBEDDING_BACKEND", "dashscope").lower()

# dashscope embedding 模型
DASHSCOPE_EMBEDDING_MODEL = os.getenv("LLM_EMBEDDING_MODEL", "text-embedding-v2")

# 本地 embedding 模型（sentence-transformers）
LOCAL_EMBEDDING_MODEL = os.getenv("LLM_EMBEDDING_MODEL_LOCAL", "BAAI/bge-small-zh-v1.5")

# embedding 维度（v2 = 1536, bge-small-zh = 512）
EMBEDDING_DIM = int(os.getenv("LLM_EMBEDDING_DIM", "1536"))


# ============================================================
# EmbeddingService
# ============================================================

class EmbeddingService:
    """文本向量化服务 — 支持 dashscope / local 双后端

    使用方式：
        svc = get_embedding_service()
        vec = await svc.embed("公司花了多少")
        vecs = await svc.embed_batch(["text1", "text2"])
    """

    def __init__(self, backend: str = EMBEDDING_BACKEND):
        self._backend = backend
        self._cache: dict[str, np.ndarray] = {}
        # 延迟初始化的客户端
        self._dashscope_client = None
        self._local_model = None
        self._initialized = False

    def _ensure_initialized(self):
        """延迟初始化后端客户端（避免启动时加载模型）

        若首次初始化失败（backend 被设为 "none"），允许后续重试，
        避免 SDK 安装/环境变量补齐后仍无法恢复。
        """
        global EMBEDDING_DIM
        if self._initialized and self._backend != "none":
            return
        try:
            if self._backend == "dashscope":
                # dashscope 通过 SDK 调用，无需预初始化 client
                # 仅校验 API key 可用性
                api_key = os.getenv("LLM_API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", "")
                if not api_key:
                    logger.warning("EmbeddingService: LLM_API_KEY not set, dashscope backend will fail")
                logger.info(
                    "EmbeddingService initialized: backend=dashscope model=%s dim=%d",
                    DASHSCOPE_EMBEDDING_MODEL, EMBEDDING_DIM,
                )
            elif self._backend == "local":
                try:
                    from sentence_transformers import SentenceTransformer
                    self._local_model = SentenceTransformer(LOCAL_EMBEDDING_MODEL)
                    # 用实际维度覆盖配置维度
                    test_vec = self._local_model.encode("测试")
                    actual_dim = len(test_vec)
                    EMBEDDING_DIM = actual_dim
                    logger.info(
                        "EmbeddingService initialized: backend=local model=%s dim=%d",
                        LOCAL_EMBEDDING_MODEL, actual_dim,
                    )
                except ImportError:
                    logger.warning(
                        "EmbeddingService: sentence-transformers not installed, "
                        "local backend unavailable. Falling back to zero vectors."
                    )
                    self._backend = "none"  # 标记为不可用
            else:
                logger.warning("EmbeddingService: unknown backend %r", self._backend)
                self._backend = "none"
        except Exception as e:
            logger.warning("EmbeddingService init failed: %s", e)
            self._backend = "none"
        finally:
            self._initialized = True

    @staticmethod
    def _cache_key(text: str) -> str:
        """生成缓存 key（hash 文本）"""
        return hashlib.md5(text.strip().lower().encode()).hexdigest()

    async def embed(self, text: str) -> np.ndarray:
        """单条文本向量化

        Args:
            text: 待向量化的文本

        Returns:
            np.ndarray，维度为 EMBEDDING_DIM；失败时返回零向量
        """
        if not text or not text.strip():
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)

        key = self._cache_key(text)
        if key in self._cache:
            return self._cache[key]

        vec = await self._embed_uncached(text)
        self._cache[key] = vec
        return vec

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """批量向量化

        先查缓存命中的，未命中的批量调后端。
        """
        if not texts:
            return []

        results: list[Optional[np.ndarray]] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            if not text or not text.strip():
                results[i] = np.zeros(EMBEDDING_DIM, dtype=np.float32)
                continue
            key = self._cache_key(text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            batch_vecs = await self._embed_batch_uncached(uncached_texts)
            for idx, vec in zip(uncached_indices, batch_vecs):
                results[idx] = vec
                # 写缓存
                key = self._cache_key(texts[idx])
                self._cache[key] = vec

        return [v if v is not None else np.zeros(EMBEDDING_DIM, dtype=np.float32) for v in results]

    async def _embed_uncached(self, text: str) -> np.ndarray:
        """单条向量化（不查缓存）"""
        vecs = await self._embed_batch_uncached([text])
        return vecs[0] if vecs else np.zeros(EMBEDDING_DIM, dtype=np.float32)

    async def _embed_batch_uncached(self, texts: list[str]) -> list[np.ndarray]:
        """批量向量化（不查缓存）"""
        self._ensure_initialized()

        if self._backend == "none":
            return [np.zeros(EMBEDDING_DIM, dtype=np.float32) for _ in texts]

        try:
            if self._backend == "dashscope":
                return await self._embed_dashscope(texts)
            elif self._backend == "openai":
                return await self._embed_openai(texts)
            elif self._backend == "local":
                return await self._embed_local(texts)
        except Exception as e:
            logger.warning("EmbeddingService batch failed: %s", e)
        return [np.zeros(EMBEDDING_DIM, dtype=np.float32) for _ in texts]

    async def _embed_openai(self, texts: list[str]) -> list[np.ndarray]:
        """通过 OpenAI 兼容协议批量向量化（适配自建网关 https://aigw.telecomjs.com/v1）"""
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai SDK not installed, returning zero vectors")
            return [np.zeros(EMBEDDING_DIM, dtype=np.float32) for _ in texts]

        api_key = os.getenv("LLM_API_KEY", "")
        base_url = os.getenv("LLM_BASE_URL", "")
        model = os.getenv("LLM_EMBEDDING_MODEL", "text-embedding-v3")
        if not api_key or not base_url:
            return [np.zeros(EMBEDDING_DIM, dtype=np.float32) for _ in texts]

        def _call():
            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.embeddings.create(model=model, input=texts)
            return [np.array(d.embedding, dtype=np.float32) for d in resp.data]

        return await asyncio.to_thread(_call)


    async def _embed_dashscope(self, texts: list[str]) -> list[np.ndarray]:
        """通过 dashscope API 批量向量化"""
        try:
            import dashscope
        except ImportError:
            logger.warning("dashscope SDK not installed, returning zero vectors")
            return [np.zeros(EMBEDDING_DIM, dtype=np.float32) for _ in texts]

        api_key = os.getenv("LLM_API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", "")
        if not api_key:
            return [np.zeros(EMBEDDING_DIM, dtype=np.float32) for _ in texts]

        # dashscope 同步 API → 用 to_thread 包装为异步
        def _call():
            resp = dashscope.TextEmbedding.call(
                model=DASHSCOPE_EMBEDDING_MODEL,
                input=texts,
                api_key=api_key,
            )
            if resp.status_code != 200:
                logger.warning("dashscope embedding failed: %s", resp.message)
                return None
            return resp.output.get("embeddings", [])

        result = await asyncio.to_thread(_call)
        if result is None:
            return [np.zeros(EMBEDDING_DIM, dtype=np.float32) for _ in texts]

        # 每个 embedding 是 dict {"text_index": int, "embedding": list[float]}
        vecs_by_index: dict[int, np.ndarray] = {}
        for item in result:
            idx = item.get("text_index", 0)
            emb = item.get("embedding", [])
            vecs_by_index[idx] = np.array(emb, dtype=np.float32)

        return [vecs_by_index.get(i, np.zeros(EMBEDDING_DIM, dtype=np.float32)) for i in range(len(texts))]

    async def _embed_local(self, texts: list[str]) -> list[np.ndarray]:
        """通过本地 sentence-transformers 批量向量化"""
        if self._local_model is None:
            return [np.zeros(EMBEDDING_DIM, dtype=np.float32) for _ in texts]

        # 模型 encode 是 CPU 密集型，用 to_thread 避免阻塞
        def _encode():
            return self._local_model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

        vecs = await asyncio.to_thread(_encode)
        return [np.array(v, dtype=np.float32) for v in vecs]

    def clear_cache(self) -> int:
        """清空缓存，返回清除的条目数"""
        count = len(self._cache)
        self._cache.clear()
        return count

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIM


# ============================================================
# 全局单例
# ============================================================

_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """获取 EmbeddingService 单例"""
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service


def reset_embedding_service() -> None:
    """重置单例（测试用）"""
    global _service
    _service = None
