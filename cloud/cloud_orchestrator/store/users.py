"""
User 存储 — 平台账号（v4：真账号 + 真密码 + user_id 主键）。

身份：user_id（UUID，唯一且不变）为主键；email 仅作登录标识（可绑定，唯一）。
字段：user_id / email / password_hash(pbkdf2) / status / nickname / bio / avatar / profile。
存储：cloud_orchestrator/data/users.json
密码哈希：标准库 hashlib.pbkdf2_hmac（sha256, 20万次迭代），零第三方依赖。
"""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .persist import load_json, save_json

_FILE = "users.json"

# ── 密码哈希（标准库 pbkdf2，抗 GPU 爆破）──
_ITER = 200_000


def hash_password(password: str) -> str:
    """生成 pbkdf2 密码哈希：pbkdf2$<iter>$<salt_hex>$<hash_hex>"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER)
    return f"pbkdf2${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码；stored 为空/格式错误一律返回 False。"""
    if not stored:
        return False
    try:
        _, it, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(it)
        )
        return secrets.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


@dataclass
class User:
    user_id: str = ""
    email: str = ""
    password_hash: str = ""  # 只存哈希，绝不存明文
    status: str = "active"   # active / disabled
    nickname: str = ""
    bio: str = ""
    avatar: str = ""  # 预留（URL），不强制
    profile: dict[str, Any] = field(default_factory=dict)  # 颗粒资料（自动预填）
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "User":
        d = dict(d or {})
        # 兼容旧数据：老用户无 user_id → 自动补一个（一次性迁移）
        uid = str(d.get("user_id") or "") or uuid.uuid4().hex
        return cls(
            user_id=uid,
            email=str(d.get("email") or ""),
            password_hash=str(d.get("password_hash") or ""),
            status=str(d.get("status") or "active"),
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
        # 兼容：为老数据补 user_id 并落盘一次
        need_save = False
        for email, data in self._by_email.items():
            if not (data or {}).get("user_id"):
                data["user_id"] = uuid.uuid4().hex
                need_save = True
        if need_save:
            self._save()

    def _save(self) -> None:
        save_json(_FILE, self._by_email)

    # ── 查询 ──
    def get(self, email: str) -> User | None:
        """按 email（登录标识）取用户。"""
        data = self._by_email.get((email or "").strip().lower())
        if not data:
            return None
        return User.from_dict(data)

    def get_by_id(self, user_id: str) -> User | None:
        for data in self._by_email.values():
            if (data or {}).get("user_id") == user_id:
                return User.from_dict(data)
        return None

    def _exists(self, email: str) -> bool:
        return (email or "").strip().lower() in self._by_email

    # ── 注册 / 登录 ──
    def register(self, email: str, password: str, nickname: str = "") -> User:
        """注册新账号：生成 user_id + 密码哈希。调用方需先确认邮箱未占用。"""
        email = (email or "").strip().lower()
        user = User(
            user_id=uuid.uuid4().hex,
            email=email,
            password_hash=hash_password(password),
            status="active",
            nickname=nickname or email.split("@")[0] or "用户",
            created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._by_email[email] = asdict(user)
        self._save()
        return user

    def set_password(self, email: str, password: str) -> User | None:
        u = self.get(email)
        if u is None:
            return None
        u.password_hash = hash_password(password)
        return self.upsert(u)

    def verify_password(self, email: str, password: str) -> bool:
        u = self.get(email)
        if u is None:
            return False
        return verify_password(password, u.password_hash)

    # ── 兼容旧接口（touch/upsert/update，供既有业务使用）──
    def upsert(self, user: User) -> User:
        user.email = user.email.strip().lower()
        if not user.user_id:
            user.user_id = uuid.uuid4().hex
        if not user.nickname:
            user.nickname = user.email.split("@")[0] or "用户"
        if not user.created_at:
            user.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self._by_email[user.email] = asdict(user)
        self._save()
        return user

    def touch(self, email: str) -> User:
        """登录时取用户；不存在则自动创建（邮箱即身份，注册/登录统一）。
        注意：仅兼容遗留流程；新注册/登录应走 register/verify_password。"""
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
