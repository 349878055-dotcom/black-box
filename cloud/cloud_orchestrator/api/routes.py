"""
API 路由（个人助理5 · skill 消费版）。

HTTP: /health /api/v1/auth/login|register /api/v1/chat /api/v1/task /api/v1/cancel
      /api/v1/me (GET/PUT 个人资料中心)
WebSocket: /api/v1/ws（App 执行通道 + ask_user 交互）
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel

from ..auth import create_token
from ..channel.ws import handle_websocket
from ..channel.session import get_manager

router = APIRouter()


class AuthRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    password_confirm: str
    nickname: str = ""


class ChatRequest(BaseModel):
    message: str


class MeUpdate(BaseModel):
    nickname: str = ""
    bio: str = ""
    avatar: str = ""
    profile: dict = {}


def _my_email(request: Request) -> str:
    return getattr(request.state, "user_email", "")


def _user_view(u) -> dict:
    return {
        "email": u.email,
        "nickname": u.nickname or u.email.split("@")[0],
        "bio": u.bio,
        "avatar": u.avatar,
        "created_at": u.created_at,
    }


# ═══════════════════ 健康检查 ═══════════════════

@router.get("/health")
async def health():
    return {"status": "ok", "service": "personal_assistant5", "timestamp": time.time()}


# ═══════════════════ 认证 ═══════════════════

@router.post("/api/v1/auth/login")
async def login(body: AuthRequest):
    identity = body.email.strip()
    password = body.password.strip()
    if not identity or not password:
        return {"ok": False, "detail": "请填写用户名/邮箱和密码"}
    from ..store.users import users

    user = users.touch(identity)
    token = create_token(identity)
    return {"access_token": token, "user_id": identity, "user": _user_view(user)}


@router.post("/api/v1/auth/register")
async def register(body: RegisterRequest):
    email = body.email.strip()
    password = body.password.strip()
    if not email or "@" not in email:
        return {"ok": False, "detail": "注册请填写有效邮箱"}
    if len(password) < 6:
        return {"ok": False, "detail": "密码至少 6 位"}
    if password != body.password_confirm.strip():
        return {"ok": False, "detail": "两次输入的密码不一致"}
    from ..store.users import User, users

    nickname = (body.nickname or "").strip() or email.split("@")[0]
    user = users.upsert(User(email=email, nickname=nickname))
    token = create_token(email)
    return {"access_token": token, "user_id": email, "user": _user_view(user)}


# ═══════════════════ 对话 / 任务 ═══════════════════

@router.post("/api/v1/chat")
async def chat(request: Request, body: ChatRequest):
    """用户消息 → 主代理（skill 消费模式）→ 异步任务。"""
    msg = (body.message or "").strip()
    if not msg:
        return {"status": "ok", "reply": "", "task": None}
    from ..core.master import master

    device_id = _my_email(request) or "anon"
    out = master.submit(device_id, msg)
    return {"status": "ok", "task": out.get("task")}


@router.get("/api/v1/task")
async def get_task(request: Request):
    from ..core.master import master

    return {"status": "ok", "task": master.get_task(_my_email(request))}


@router.post("/api/v1/cancel")
async def cancel_task(request: Request):
    from ..core.master import master

    master.cancel(_my_email(request))
    return {"status": "ok", "message": "已请求取消"}


# ═══════════════════ 个人资料中心 ═══════════════════

@router.get("/api/v1/me")
async def me(request: Request):
    from ..store.users import users

    email = _my_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="未登录")
    u = users.touch(email)
    return {"ok": True, "user": _user_view(u), "profile": dict(u.profile or {})}


@router.put("/api/v1/me")
async def update_me(request: Request, body: MeUpdate):
    from ..store.users import users

    email = _my_email(request)
    u = users.update(
        email,
        nickname=body.nickname,
        bio=body.bio,
        avatar=body.avatar,
        profile=body.profile,
    )
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"ok": True, "user": _user_view(u)}


# ═══════════════════ WebSocket 执行通道 ═══════════════════

@router.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str | None = None, device_id: str | None = None):
    from ..channel.ws import handle_websocket

    manager = get_manager()
    if session_id:
        session = manager.get(session_id)
        if session:
            session.websocket = websocket
    await handle_websocket(websocket, session_id, device_id)
