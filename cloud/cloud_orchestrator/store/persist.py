"""
Agent 状态落盘目录：对话 / 台账 / 挂起请示 / 任务。
使用临时文件 + rename 原子替换，防止并发写入损坏数据。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# __file__ = .../cloud/cloud_orchestrator/agent/persist.py
# 状态数据放 cloud_orchestrator/data/（服务运行时数据，.gitignore 已忽略）
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _path(name: str) -> Path:
    return DATA_DIR / name


def load_json(name: str, default: Any) -> Any:
    p = _path(name)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(name: str, data: Any) -> None:
    p = _path(name)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(p)
