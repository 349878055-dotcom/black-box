"""
User 存储 — 平台账号（v3 本轮最小版）。

身份 = email（即 device_id / skill 作者）。
字段：昵称 / 简介 / 头像 / 颗粒资料(profile，ask_user 自动预填用)。
存储：cloud_orchestrator/data/users.json
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .persist import load_json, save_json

_FILE = "users.json"


@dataclass
class User:
    email: str
    nickname: str = ""
    bio: str = ""
    avatar: str = ""  # 本轮预留（URL），不强制
    profile: dict[str, Any] = field(default_factory=dict)  # 颗粒资料（自动预填）
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "User":
        d = dict(d or {})
        return cls(
            email=str(d.get("email") or ""),
            nickname=str(d.get("nickname") or ""),
            bio=str(d.get("bio") or ""),
            avatar=str(d.get("avatar") or ""),
            profile=d.get("profile") if isinstance(d.get("profile"), dict) else {},
            created_at=str(d.get("created_at") or ""),
        )


class UserStore:
    def __init__(self) -> None:
        raw = load_json(_FILE, {})
        self._by_email: dict[str, dict] = raw if isinstance(raw, dict) else {}

    def _save(self) -> None:
        save_json(_FILE, self._by_email)

    def get(self, email: str) -> User | None:
        data = self._by_email.get((email or "").strip().lower())
        if not data:
            return None
        return User.from_dict(data)

    def upsert(self, user: User) -> User:
        user.email = user.email.strip().lower()
        if not user.nickname:
            user.nickname = user.email.split("@")[0] or "用户"
        if not user.created_at:
            user.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self._by_email[user.email] = asdict(user)
        self._save()
        return user

    def touch(self, email: str) -> User:
        """登录时取用户；不存在则自动创建（邮箱即身份，注册/登录统一）。"""
        u = self.get(email)
        if u is None:
            u = self.upsert(User(email=email))
        return u

    def update(
        self,
        email: str,
        *,
        nickname: str | None = None,
        bio: str | None = None,
        avatar: str | None = None,
        profile: dict | None = None,
    ) -> User | None:
        u = self.get(email)
        if u is None:
            return None
        if nickname is not None:
            u.nickname = str(nickname)[:40]
        if bio is not None:
            u.bio = str(bio)[:200]
        if avatar is not None:
            u.avatar = str(avatar)[:500]
        if profile is not None and isinstance(profile, dict):
            u.profile = {str(k)[:40]: str(v)[:500] for k, v in profile.items()}
        return self.upsert(u)


# 全局单例
users = UserStore()
