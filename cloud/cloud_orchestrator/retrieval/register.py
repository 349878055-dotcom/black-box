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
    """重建索引（skill 注册表变化后调用）。返回是否成功。

    问题⑧：先刷新磁盘 ADAPTERS（reload_skills），再重建索引，并正确替换
    index 模块的单例 _index。旧实现 `from .index import _index` + `globals()["_index"]=...`
    只改了本模块命名空间，get_index() 拿不到新索引，导致重建无效。
    """
    from ..adapters import registry as reg
    from . import index as index_mod

    reg.reload_skills()
    idx = index_mod.RetrievalIndex()
    ok = idx.build(reg.ADAPTERS)
    if ok:
        index_mod._index = idx
        index_mod._INDEX_FP = reg.skills_fingerprint()  # 同步指纹，避免 get_index 误判重复重建
    return ok
