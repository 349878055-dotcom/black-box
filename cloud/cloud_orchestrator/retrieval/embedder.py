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
    """懒加载 SentenceTransformer 模型（进程内单例）。

    铁律（2026-08-16）：加载失败直接抛错暴露，绝不返回 None 降级——
    否则向量检索不可用会被静默掩盖。
    优先本地目录（cloud/models/bge-small-zh-v1.5）；不存在则从 HuggingFace 自动下载。
    """
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError(
            "sentence-transformers 未安装，向量检索不可用"
            "（pip install sentence-transformers，且需 torch）"
        )
    if os.path.isdir(MODEL_DIR):
        _model = SentenceTransformer(MODEL_DIR)
        logger.info("BGE 向量模型加载完成（本地 %s）", MODEL_DIR)
    else:
        # 服务器无本地模型 → 从 HuggingFace 下载（用镜像可加速）
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        _model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
        logger.info("BGE 向量模型从 HuggingFace 下载加载完成")
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """把一批文本转成向量。失败直接抛错，不降级返回 None。"""
    model = _load()
    if not texts:
        return []
    vecs = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vecs]
