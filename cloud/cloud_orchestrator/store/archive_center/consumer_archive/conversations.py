"""
会话存储 — 消费者多会话（豆包式）。

归属：store/archive_center/consumer_archive（客户档案中心 · 消费者档案）。
会话归属 user_id；persona 只引用贡献者上台卡（person_id/person_name/skills）。
存储：cloud_orchestrator/data/conversations.json
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from ...persist import load_json, save_json

_FILE = "conversations.json"

_PERSONA_KEYS = {"person_id", "person_name", "skills"}


def _clean_persona(raw: Any) -> dict:
    """persona 只收「引用上台卡」的三样字段（person_id/person_name/skills），
    其余一律丢弃——不复制整张卡，更不把证件等资料带进会话。"""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in _PERSONA_KEYS}


@dataclass
class Conversation:
    conversation_id: str
    user_id: str
    title: str = "新对话"
    type: str = "chat"              # chat / skill
    persona: dict[str, Any] = field(default_factory=dict)  # 会话人设 = 引用上台卡 {person_id, person_name, skills[]}（只挂 id）
    messages: list[dict[str, Any]] = field(default_factory=list)  # [{who,text,img,at}]
    pinned: bool = False
    deleted: bool = False           # 软删标记（当前流程硬删，保留字段备用）
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        d = dict(d or {})
        return cls(
            conversation_id=str(d.get("conversation_id") or ""),
            user_id=str(d.get("user_id") or ""),
            title=str(d.get("title") or "新对话"),
            type=str(d.get("type") or "chat"),
            persona=d.get("persona") if isinstance(d.get("persona"), dict) else {},
            messages=d.get("messages") if isinstance(d.get("messages"), list) else [],
            pinned=bool(d.get("pinned")),
            deleted=bool(d.get("deleted")),
            created_at=float(d.get("created_at") or 0),
            updated_at=float(d.get("updated_at") or 0),
        )


class ConversationStore:
    def __init__(self) -> None:
        raw = load_json(_FILE, {})
        self._data: dict[str, dict] = raw if isinstance(raw, dict) else {}

    def _save(self) -> None:
        save_json(_FILE, self._data)

    def get_default(self, user_id: str) -> Conversation:
        """每个用户独立的 default 会话（key=default__<user_id>，避免多用户串）。
        default 会话不自动改名（保持「虾米」）。"""
        key = "default__" + (user_id or "")
        d = self._data.get(key)
        if d and d.get("user_id") == user_id:
            return Conversation.from_dict(d)
        now = time.time()
        conv = Conversation(
            conversation_id=key,
            user_id=user_id,
            title="虾米",
            type="chat",
            created_at=now,
            updated_at=now,
        )
        dd = conv.to_dict()
        dd["_titled"] = True   # default 会话不自动改名
        self._data[key] = dd
        self._save()
        return conv

    def create(self, user_id: str, type: str = "chat", persona: dict | None = None) -> Conversation:
        """新建会话，返回会话对象。persona 只保留引用上台卡的字段。"""
        now = time.time()
        conv = Conversation(
            conversation_id=uuid.uuid4().hex,
            user_id=user_id,
            title="新对话",
            type=type or "chat",
            persona=_clean_persona(persona),
            messages=[],
            created_at=now,
            updated_at=now,
        )
        self._data[conv.conversation_id] = conv.to_dict()
        self._save()
        return conv

    def get(self, conversation_id: str) -> Conversation | None:
        d = self._data.get(conversation_id)
        if not d:
            return None
        conv = Conversation.from_dict(d)
        if conv.deleted:
            return None
        return conv

    def list_by_user(self, user_id: str, include_deleted: bool = False) -> list[Conversation]:
        """按用户列出会话（不含已删除），按最近更新倒序。"""
        out = []
        for d in self._data.values():
            if d.get("user_id") != user_id:
                continue
            if not include_deleted and d.get("deleted"):
                continue
            out.append(Conversation.from_dict(d))
        out.sort(key=lambda c: (c.pinned, c.updated_at), reverse=True)
        return out

    def append_message(self, conversation_id: str, msg: dict) -> bool:
        d = self._data.get(conversation_id)
        if not d or d.get("deleted"):
            return False
        d.setdefault("messages", []).append(msg)
        d["updated_at"] = time.time()
        # 标题自动命名：第一条用户消息作为标题（首条 12 字，豆包轻量版）
        if not d.get("_titled") and msg.get("who") == "user":
            t = str(msg.get("text") or "").replace("\n", " ").strip()
            if t:
                d["title"] = t[:12]
                d["_titled"] = True
        self._save()
        return True

    def set_title(self, conversation_id: str, title: str) -> bool:
        d = self._data.get(conversation_id)
        if not d:
            return False
        d["title"] = (title or "").strip()[:40] or "新对话"
        d["_titled"] = True   # 手动改名后不再被首条消息自动覆盖
        d["updated_at"] = time.time()
        self._save()
        return True

    def set_pinned(self, conversation_id: str, pinned: bool) -> bool:
        d = self._data.get(conversation_id)
        if not d:
            return False
        d["pinned"] = bool(pinned)
        d["updated_at"] = time.time()
        self._save()
        return True

    def clear_messages(self, conversation_id: str) -> bool:
        d = self._data.get(conversation_id)
        if not d:
            return False
        d["messages"] = []
        d["updated_at"] = time.time()
        self._save()
        return True

    def delete(self, conversation_id: str) -> bool:
        """硬删会话（豆包式：不进回收站）。"""
        if conversation_id in self._data:
            del self._data[conversation_id]
            self._save()
            return True
        return False


# 全局单例
conversations = ConversationStore()
