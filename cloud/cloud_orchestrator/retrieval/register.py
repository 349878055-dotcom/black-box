"""
register — 从 registry.ADAPTERS 构建/重建向量索引（启动或热更新用）。

用法：
    from ..retrieval.index import get_index
    idx = get_index()          # 单例，首次自动 build
    # 或强制重建（skill 更新后）：
    from ..retrieval import register
    register.rebuild()
"""
from __future__ import annotations

import logging

logger = logging.getLogger("xiami.retrieval.register")


def rebuild() -> bool:
    """重建索引（skill 注册表变化后调用）。返回是否成功。"""
    from ..adapters.registry import ADAPTERS
    from .index import RetrievalIndex, _index

    idx = RetrievalIndex()
    ok = idx.build(ADAPTERS)
    if ok:
        globals()["_index"] = idx
    return ok
