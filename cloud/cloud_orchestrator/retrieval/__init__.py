"""
retrieval — 向量检索（两级：平台级 + 功能级）。

给主代理用的「小纸条」机制：
- 客户一句话 → 平台级检索选 top-1 平台 → 功能级检索选当前功能方法
- AI 只看到「当前平台 + 当前功能的方法」，不会被全部 skill 淹没。
"""
from .index import RetrievalIndex, get_index

__all__ = ["RetrievalIndex", "get_index"]
