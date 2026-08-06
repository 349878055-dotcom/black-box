"""
对话信息流落盘 — 手机/电脑背后完整链路，出问题可全面检查。

写入: cloud_orchestrator/data/flows/<device_id>.jsonl  （每行一条事件）
以及: cloud_orchestrator/data/flows/_all.jsonl         （全局最近事件）
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .persist import DATA_DIR

FLOWS_DIR = DATA_DIR / "flows"
FLOWS_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_ALL_MAX_BYTES = 8 * 1024 * 1024  # 全局日志约 8MB 后截断旧内容


def _ts() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _clip(val: Any, limit: int = 4000) -> Any:
    if val is None:
        return None
    if isinstance(val, str):
        return val if len(val) <= limit else val[:limit] + f"…(+{len(val) - limit})"
    if isinstance(val, dict):
        return {k: _clip(v, limit) for k, v in val.items()}
    if isinstance(val, list):
        if len(val) > 40:
            return [_clip(x, limit) for x in val[:40]] + [f"…(+{len(val) - 40} items)"]
        return [_clip(x, limit) for x in val]
    return val


def log_flow(device_id: str, kind: str, **payload: Any) -> None:
    """追加一条信息流事件。"""
    entry = {
        "ts": _ts(),
        "device_id": device_id or "unknown",
        "kind": kind,
        **{k: _clip(v) for k, v in payload.items()},
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _lock:
        try:
            (FLOWS_DIR / f"{device_id or 'unknown'}.jsonl").open("a", encoding="utf-8").write(line)
            all_path = FLOWS_DIR / "_all.jsonl"
            all_path.open("a", encoding="utf-8").write(line)
            if all_path.stat().st_size > _ALL_MAX_BYTES:
                data = all_path.read_bytes()
                all_path.write_bytes(data[len(data) // 2:])
        except Exception:
            pass


def read_flow(device_id: str | None = None, limit: int = 200) -> list[dict]:
    """读最近 limit 条；device_id 为空则读全局。"""
    path = FLOWS_DIR / (f"{device_id}.jsonl" if device_id else "_all.jsonl")
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
