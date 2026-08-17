"""Intent Retriever — 基于 embedding 的意图向量检索（Step 2.1.3 + 2.1.4）

为 LLM NLU 提供 Top-K 候选意图检索，替代把 60+ 意图全塞进 prompt 的做法。

架构：
1. 启动时（app/main.py lifespan）调用 build_index() 一次性计算所有意图 embedding
2. 每条意图的 embedding 由其 typical_utterances 的平均向量构成
3. retrieve(text, role, top_k=8) 计算用户文本 embedding，余弦相似度排序，按角色过滤

设计要点：
- _index: dict[str, np.ndarray]  意图名 → 平均 embedding
- _meta: dict[str, Intent]       意图名 → Intent 对象（含 role_scope 用于过滤）
- 启动失败时 _index 为空，retrieve 返回空列表，LLM NLU 自动降级到全量 prompt
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .models import Intent, UserRole
from .intent_registry import ALL_INTENTS
from .embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


class IntentRetriever:
    """意图向量检索器"""

    def __init__(self):
        # 意图名 → 平均 embedding
        self._index: dict[str, np.ndarray] = {}
        # 意图名 → Intent 对象
        self._meta: dict[str, Intent] = {}
        # 是否已构建索引
        self._built: bool = False

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def index_size(self) -> int:
        return len(self._index)

    async def build_index(self, intents: list[Intent] = None) -> int:
        """构建意图 embedding 索引

        对每个意图：
        1. 取其 typical_utterances（3-5 条）
        2. 批量 embedding
        3. 取平均向量作为该意图的 embedding
        4. 存入 _index

        Args:
            intents: 意图列表，默认 ALL_INTENTS

        Returns:
            成功索引的意图数
        """
        if intents is None:
            intents = ALL_INTENTS

        svc = get_embedding_service()
        built_count = 0

        logger.info(
            "Building intent embedding index: %d intents, backend=%s",
            len(intents), svc.backend,
        )

        for intent in intents:
            if not intent.typical_utterances:
                logger.debug("Intent %s has no typical_utterances, skipping", intent.name)
                continue

            try:
                # 批量 embedding 该意图的所有表述
                vecs = await svc.embed_batch(intent.typical_utterances)
                # 过滤掉零向量（embedding 失败的）
                valid_vecs = [v for v in vecs if not np.all(v == 0)]
                if not valid_vecs:
                    logger.warning(
                        "Intent %s: all embeddings are zero, skipping", intent.name
                    )
                    continue

                # 平均向量作为该意图的 embedding
                avg_vec = np.mean(valid_vecs, axis=0)
                # L2 归一化（便于余弦相似度计算 → 简化为点积）
                norm = np.linalg.norm(avg_vec)
                if norm > 0:
                    avg_vec = avg_vec / norm

                self._index[intent.name] = avg_vec.astype(np.float32)
                self._meta[intent.name] = intent
                built_count += 1
            except Exception as e:
                logger.warning("Failed to embed intent %s: %s", intent.name, e)

        self._built = True
        logger.info(
            "Intent embedding index built: %d/%d intents indexed",
            built_count, len(intents),
        )
        return built_count

    async def retrieve(
        self,
        text: str,
        role: UserRole,
        top_k: int = 8,
    ) -> list[Intent]:
        """检索 Top-K 候选意图（Step 2.1.4 实现）

        Args:
            text: 用户输入文本
            role: 用户角色（用于过滤不可见意图）
            top_k: 返回候选数

        Returns:
            按相似度降序排列的 Intent 列表；索引未构建时返回空列表
        """
        if not self._built or not self._index:
            logger.debug("IntentRetriever index not built, returning empty list")
            return []

        if not text or not text.strip():
            return []

        svc = get_embedding_service()
        query_vec = await svc.embed(text)

        # 查询向量为零（embedding 失败）→ 无法检索
        if np.all(query_vec == 0):
            logger.debug("Query embedding is zero, cannot retrieve")
            return []

        # L2 归一化查询向量
        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec = query_vec / norm

        # 计算与每个意图的余弦相似度（已归一化 → 点积）
        scores: list[tuple[str, float]] = []
        for intent_name, intent_vec in self._index.items():
            intent = self._meta.get(intent_name)
            if not intent:
                continue
            # 角色过滤：用户角色不在 role_scope 中则跳过
            if role not in intent.role_scope:
                continue
            score = float(np.dot(query_vec, intent_vec))
            scores.append((intent_name, score))

        # 按相似度降序排序，取 Top-K
        scores.sort(key=lambda x: x[1], reverse=True)
        top_names = [name for name, _ in scores[:top_k]]

        return [self._meta[name] for name in top_names if name in self._meta]

    def clear(self) -> None:
        """清空索引（测试用）"""
        self._index.clear()
        self._meta.clear()
        self._built = False


# ============================================================
# 全局单例
# ============================================================

_retriever: Optional[IntentRetriever] = None


def get_intent_retriever() -> IntentRetriever:
    """获取 IntentRetriever 单例"""
    global _retriever
    if _retriever is None:
        _retriever = IntentRetriever()
    return _retriever


def reset_intent_retriever() -> None:
    """重置单例（测试用）"""
    global _retriever
    _retriever = None
