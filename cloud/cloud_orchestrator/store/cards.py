"""
才艺分区 — 上台卡。

仓库仍是 cloud_orchestrator/data/，这是里面的才艺分区（cards.json）。
客户资料区（users.json / conversations.json）不进这里。

字段：id / owner_id / status / 展示文案 / skills[]（只挂 skill id，代码在 adapters/skills/）。
owner_id 指向账号的 user_id；空字符串 = 未绑号的样品上台卡。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .persist import load_json, save_json

_FILE = "cards.json"
_SEED = Path(__file__).resolve().parent / "seed" / "cards.json"

_LIST_DROP = {"greeting", "experience", "comments", "sample"}


def _known_skill_ids() -> set[str]:
    try:
        from ..adapters.registry import ADAPTERS
        return set(ADAPTERS.keys())
    except Exception:
        return set()


def _clean_skills(raw: Any) -> list[dict]:
    known = _known_skill_ids()
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        if not sid or (known and sid not in known):
            continue
        out.append({
            "id": sid,
            "label": str(item.get("label") or sid),
            "how": str(item.get("how") or ""),
            "intents": [str(x) for x in (item.get("intents") or []) if x],
        })
    return out


def _normalize(raw: dict) -> dict:
    cid = str(raw.get("id") or "").strip()
    skills = _clean_skills(raw.get("skills"))
    comments = raw.get("comments") if isinstance(raw.get("comments"), list) else []
    return {
        "id": cid,
        "owner_id": str(raw.get("owner_id") or ""),
        "status": str(raw.get("status") or "off"),
        "sample": bool(raw.get("sample")),
        "name": str(raw.get("name") or cid),
        "initial": str(raw.get("initial") or (raw.get("name") or "?")[:1]),
        "color": str(raw.get("color") or "linear-gradient(145deg,#c9d4ff,#6b8cff)"),
        "tagline": str(raw.get("tagline") or ""),
        "city": str(raw.get("city") or ""),
        "tags": [str(t) for t in (raw.get("tags") or []) if t],
        "rating": float(raw.get("rating") or 0),
        "jobs": int(raw.get("jobs") or 0),
        "week": int(raw.get("week") or 0),
        "greeting": str(raw.get("greeting") or ""),
        "skills": skills,
        "experience": raw.get("experience") if isinstance(raw.get("experience"), list) else [],
        "comments": comments,
    }


class CardStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        raw = load_json(_FILE, None)
        if not isinstance(raw, dict) or not raw:
            raw = self._load_seed()
            if raw:
                save_json(_FILE, raw)
        self._data = {}
        for key, item in (raw or {}).items():
            if not isinstance(item, dict):
                continue
            card = _normalize(item)
            cid = card["id"] or str(key)
            card["id"] = cid
            if cid:
                self._data[cid] = card

    def _load_seed(self) -> dict:
        if not _SEED.is_file():
            return {}
        try:
            data = json.loads(_SEED.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def get(self, card_id: str) -> dict | None:
        card = self._data.get(str(card_id or "").strip())
        if not card:
            return None
        return dict(card)

    def list(self, q: str = "", cat: str = "", sort: str = "score") -> list[dict]:
        rows = [dict(c) for c in self._data.values() if c.get("status") == "on"]
        cat = (cat or "").strip()
        if cat and cat != "全部":
            rows = [c for c in rows if _in_cat(c, cat)]
        q = (q or "").strip().lower()
        if q:
            rows = [c for c in rows if _match(c, q)]
        rows.sort(key=lambda c: _sort_key(c, sort), reverse=True)
        return [_list_view(c) for c in rows]


def _in_cat(card: dict, cat: str) -> bool:
    if cat in (card.get("tags") or []):
        return True
    for sk in card.get("skills") or []:
        if cat in (sk.get("label") or "") or cat in (sk.get("intents") or []):
            return True
    return False


def _match(card: dict, q: str) -> bool:
    bits = [
        card.get("name"),
        card.get("tagline"),
        card.get("city"),
        * (card.get("tags") or []),
    ]
    for sk in card.get("skills") or []:
        bits.append(sk.get("label"))
        bits.extend(sk.get("intents") or [])
    hay = " ".join(str(x) for x in bits if x).lower()
    if q in hay:
        return True
    return any(q in str(i).lower() or str(i).lower() in q for sk in (card.get("skills") or []) for i in (sk.get("intents") or []))


def _sort_key(card: dict, sort: str) -> tuple:
    rating = float(card.get("rating") or 0)
    jobs = int(card.get("jobs") or 0)
    week = int(card.get("week") or 0)
    if sort == "week":
        return (week, rating)
    if sort == "rating":
        return (rating, jobs)
    return (jobs * rating, jobs)


def _list_view(card: dict) -> dict:
    out = {k: v for k, v in card.items() if k not in _LIST_DROP}
    out["skills"] = [{"id": s["id"], "label": s["label"]} for s in (card.get("skills") or [])]
    out["comments_n"] = len(card.get("comments") or [])
    return out


cards = CardStore()
