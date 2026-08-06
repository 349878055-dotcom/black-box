"""
Embedder — 本地 BGE 中文向量模型封装（云端本机跑，零网络）。

- 懒加载：首次 encode 才加载模型（避免拖慢云端启动）
- 离线可用：模型已下载到 cloud/models/bge-small-zh-v1.5
- 模型：BAAI/bge-small-zh-v1.5（512 维，中文效果好、体积小 ~100MB）
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("xiami.retrieval.embedder")

# 模型目录（相对本文件：cloud/cloud_orchestrator/retrieval/embedder.py → ../../models）
_HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "models", "bge-small-zh-v1.5"))

_model = None


def _load():
    """懒加载 SentenceTransformer 模型（进程内单例）。"""
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning("sentence-transformers 未安装，向量检索不可用（pip install --user --break-system-packages sentence-transformers）")
        return None
    try:
        _model = SentenceTransformer(MODEL_DIR)
        logger.info("BGE 向量模型加载完成（%s）", MODEL_DIR)
    except Exception as e:
        logger.warning("BGE 模型加载失败：%s（向量检索降级为不可用）", e)
        _model = None
    return _model


def embed(texts: list[str]) -> list[list[float]] | None:
    """把一批文本转成向量。模型不可用时返回 None（调用方降级）。"""
    model = _load()
    if model is None:
        return None
    if not texts:
        return []
    try:
        vecs = model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]
    except Exception as e:
        logger.warning("向量编码失败：%s", e)
        return None
