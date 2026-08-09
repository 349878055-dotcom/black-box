"""
Refresh Token 存储 — 服务端有状态，可吊销 / 轮换。

存储：cloud_orchestrator/data/refresh_tokens.json
  refresh_token -> {user_id, email, created_at, expires_at, revoked}
Refresh Token 为高熵随机串（secrets.token_urlsafe），只在服务端登记，客户端只持有明文。
"""
from __future__ import annotations

import secrets
import time
from typing import Any

from .persist import load_json, save_json

_FILE = "refresh_tokens.json"
DEFAULT_TTL = 30 * 86400  # 30 天


class RefreshTokenStore:
    def __init__(self) -> None:
        self._data: dict[str, dict] = load_json(_FILE, {})

    def _save(self) -> None:
        save_json(_FILE, self._data)

    def create(self, user_id: str, email: str, ttl: int = DEFAULT_TTL) -> str:
        """创建并登记一条 refresh token，返回 token 明文。"""
        token = secrets.token_urlsafe(48)
        now = time.time()
        self._data[token] = {
            "user_id": user_id,
            "email": email,
            "created_at": now,
            "expires_at": now + ttl,
            "revoked": False,
        }
        self._save()
        return token

    def get_valid(self, token: str) -> dict[str, Any] | None:
        """取有效（未吊销、未过期）的 refresh 记录；无效则清理并返回 None。"""
        rec = self._data.get(token)
        if not rec:
            return None
        if rec.get("revoked"):
            return None
        if time.time() > rec.get("expires_at", 0):
            self.revoke(token)
            return None
        return rec

    def revoke(self, token: str) -> None:
        """吊销一条 refresh token。"""
        if token in self._data:
            self._data[token]["revoked"] = True
            self._save()

    def revoke_all_for_email(self, email: str) -> None:
        """吊销某账号的全部 refresh token（登出/改密/被踢场景）。"""
        changed = False
        for token, rec in self._data.items():
            if rec.get("email") == email and not rec.get("revoked"):
                rec["revoked"] = True
                changed = True
        if changed:
            self._save()


# 全局单例
refresh_store = RefreshTokenStore()
