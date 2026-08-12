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

from ..auth import create_tokens, refresh_access, revoke_refresh
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


class RefreshRequest(BaseModel):
    refresh_token: str


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""   # 会话 ID（选填，缺省用 default）


class MeUpdate(BaseModel):
    nickname: str = ""
    bio: str = ""
    avatar: str = ""
    profile: dict = {}


def _my_email(request: Request) -> str:
    return getattr(request.state, "user_email", "")


def _user_view(u) -> dict:
    return {
        "user_id": u.user_id,
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

    user = users.get(identity)
    if not user:
        return {"ok": False, "detail": "账号不存在，请先注册"}
    if user.status != "active":
        return {"ok": False, "detail": "账号已停用"}
    if not users.verify_password(identity, password):
        return {"ok": False, "detail": "邮箱或密码错误"}
    tokens = create_tokens(user.email, user.user_id)
    return {"ok": True, **tokens, "user": _user_view(user)}


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
    from ..store.users import users

    if users.get(email):
        return {"ok": False, "detail": "该邮箱已注册，请直接登录"}
    nickname = (body.nickname or "").strip() or email.split("@")[0]
    user = users.register(email, password, nickname)
    tokens = create_tokens(user.email, user.user_id)
    return {"ok": True, **tokens, "user": _user_view(user)}


@router.post("/api/v1/auth/refresh")
async def refresh(body: RefreshRequest):
    """用 Refresh Token 换新 Access（并轮换 Refresh）。"""
    out = refresh_access((body.refresh_token or "").strip())
    if not out:
        raise HTTPException(status_code=401, detail="刷新令牌无效或已过期")
    return {"ok": True, **out}


@router.post("/api/v1/auth/logout")
async def logout(body: RefreshRequest):
    """登出：吊销 refresh token（客户端本地再清 token）。"""
    revoke_refresh((body.refresh_token or "").strip())
    return {"ok": True}


# ═══════════════════ 对话 / 任务 ═══════════════════

@router.post("/api/v1/chat")
async def chat(request: Request, body: ChatRequest):
    """用户消息 → 主代理（skill 消费模式）→ 异步任务。"""
    msg = (body.message or "").strip()
    if not msg:
        return {"status": "ok", "reply": "", "task": None}
    from ..core.master import master

    device_id = _my_email(request) or "anon"
    user_id = getattr(request.state, "user_id", "") or device_id
    conv_id = (body.session_id or "").strip() or "default"
    out = master.submit(device_id, message=msg, user_id=user_id, conversation_id=conv_id)
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


# ═══════════════════ 会话管理（豆包式单用户多会话）═══════════════════

class ConvCreate(BaseModel):
    type: str = "chat"        # chat / skill
    persona: dict = {}


class ConvUpdate(BaseModel):
    title: str | None = None
    pinned: bool | None = None


def _me_ids(request: Request):
    email = _my_email(request)
    user_id = getattr(request.state, "user_id", "") or email
    return email, user_id


def _own_conv(request: Request, conv_id: str):
    """取归属当前用户的会话；default 自动创建。无权限抛 404。"""
    from ..store.conversations import conversations

    _, user_id = _me_ids(request)
    if conv_id == "default":
        conv = conversations.get_default(user_id)
    else:
        conv = conversations.get(conv_id)
    if not conv or conv.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


@router.get("/api/v1/conversations")
async def list_conversations(request: Request):
    from ..store.conversations import conversations

    _, user_id = _me_ids(request)
    conversations.get_default(user_id)  # 确保 default 存在
    lst = conversations.list_by_user(user_id)
    # 列表轻量返回（不含 messages）
    return {"ok": True, "conversations": [
        {k: v for k, v in c.to_dict().items() if k != "messages"} for c in lst
    ]}


@router.post("/api/v1/conversations")
async def create_conversation(request: Request, body: ConvCreate):
    from ..store.conversations import conversations

    _, user_id = _me_ids(request)
    conv = conversations.create(user_id, type=body.type or "chat", persona=body.persona or {})
    return {"ok": True, "conversation": conv.to_dict()}


@router.get("/api/v1/conversations/{conv_id}/messages")
async def get_conv_messages(request: Request, conv_id: str):
    conv = _own_conv(request, conv_id)
    return {"ok": True, "conversation": conv.to_dict()}


@router.put("/api/v1/conversations/{conv_id}")
async def update_conversation(request: Request, conv_id: str, body: ConvUpdate):
    from ..store.conversations import conversations

    _own_conv(request, conv_id)
    if body.title is not None:
        conversations.set_title(conv_id, body.title)
    if body.pinned is not None:
        conversations.set_pinned(conv_id, body.pinned)
    return {"ok": True}


@router.post("/api/v1/conversations/{conv_id}/clear")
async def clear_conversation(request: Request, conv_id: str):
    from ..store.conversations import conversations

    _own_conv(request, conv_id)
    conversations.clear_messages(conv_id)
    return {"ok": True}


@router.delete("/api/v1/conversations/{conv_id}")
async def delete_conversation(request: Request, conv_id: str):
    from ..store.conversations import conversations

    _own_conv(request, conv_id)
    if conv_id == "default":
        return {"ok": False, "detail": "默认会话不可删除"}
    conversations.delete(conv_id)
    return {"ok": True}


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


# ═══════════════════ Skill 消费 API（搜索 / 直调）═══════════════════
# 向量搜索：本地 BGE 两级检索（retrieval 模块，零网络零成本，从各 skill 的
# contract.json 自动构建）。skill 契约改动后重启云端即自动更新，无需手动重建索引；
# 旧的千问云端 skill_index.json 方案已废弃删除（避免每句话调云端 embedding）。

from ..adapters import registry as _skill_registry


def _skill_intent(pid: str) -> str:
    """App 搜索接口展示的一句话意图：优先拼 flow 流程标题（与旧 skill_index.json 的 meta.intent 对齐）。"""
    cfg = _skill_registry.ADAPTERS.get(pid) or {}
    flow = cfg.get("flow") or []
    if flow:
        return " → ".join(f.get("title", "") for f in flow)
    return cfg.get("capability_note") or ""


class SkillRunRequest(BaseModel):
    method: str
    params: dict = {}
    device_id: str = ""   # 传入则走手机通道（手机真实 IP 直连平台）；缺省云端直发


@router.get("/api/v1/skills")
async def api_list_skills():
    """skill 清单（手机 App 展示/搜索入口）。"""
    return {"skills": _skill_registry.list_skills()}


@router.get("/api/v1/skills/search")
async def api_search_skills(q: str = "", k: int = 3):
    """向量搜索 skill（本地 BGE 两级检索，用户一句话 → top-k 命中）。

    全程本地、零网络：索引从各 skill 的 contract.json 自动构建，
    skill 契约改动后重启即用新方法，无需手动重建索引。
    """
    if not q:
        return {"results": []}
    try:
        from ..retrieval.index import get_index
        idx = get_index()
        if idx is None:
            return {"results": [], "note": "本地向量模型不可用（需 pip install sentence-transformers 并加载 bge-small-zh-v1.5）"}
        plats = idx.search_platform(q, top_k=max(1, k))
    except Exception as e:
        return {"results": [], "note": f"向量检索异常：{e}"}
    return {"results": [
        {"skill": p["platform"], "score": round(p["score"], 4),
         "name": p["text"], "intent": _skill_intent(p["platform"])}
        for p in plats]}


@router.post("/api/v1/skills/{skill_id}/run")
async def api_run_skill(skill_id: str, body: SkillRunRequest):
    """直接消费 skill：POST /api/v1/skills/{id}/run {method, params, device_id}。
    device_id 传入 → 走手机通道（手机真实 IP 直连，登录态用手机凭据库）；缺省 → 云端直发。"""
    return await _skill_registry.run(skill_id, body.method, body.params or {},
                                     device_id=body.device_id)


@router.post("/api/v1/dev/browser")
async def dev_browser(body: dict):
    """调试：向手机内置浏览器下发指令并拿结果（read_frames/click/slider/navigate…）。
    POST /api/v1/dev/browser {device_id, cmd, params}。"""
    device_id = str(body.get("device_id", ""))
    cmd = str(body.get("cmd", ""))
    params = body.get("params") or {}
    if not device_id or not cmd:
        return {"ok": False, "error": "need device_id+cmd"}
    try:
        from ..channel.bridge import bridge
        res = await bridge.send_cmd(device_id, cmd, params)
        return {"ok": True, "res": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}
