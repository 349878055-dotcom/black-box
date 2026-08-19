"""
API 路由（个人助理5 · skill 消费版）。

HTTP: /health /api/v1/auth/login|register /api/v1/chat /api/v1/task /api/v1/cancel
      /api/v1/me (GET/PUT 客户资料区)
      /api/v1/cards (GET 才艺分区，上台卡)
WebSocket: /api/v1/ws（App 执行通道 + ask_user 交互）
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request, WebSocket
from pydantic import BaseModel, Field

from ..auth import create_tokens, refresh_access, revoke_refresh
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
    ask_id: str = ""       # ask_user 回答标识；带上时若匹配等待中的任务，则作为回答处理


class MeUpdate(BaseModel):
    nickname: str = ""
    bio: str = ""
    avatar: str = ""


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
    from ..store.archive_center.consumer_archive.users import users

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
    from ..store.archive_center.consumer_archive.users import users

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
        return {"ok": False, "detail": "刷新令牌无效或已过期"}
    return {"ok": True, **out}


@router.post("/api/v1/auth/logout")
async def logout(body: RefreshRequest):
    """登出：吊销 refresh token（客户端本地再清 token）。"""
    revoke_refresh((body.refresh_token or "").strip())
    return {"ok": True}


# ═══════════════════ 对话 / 任务 ═══════════════════

@router.post("/api/v1/chat")
async def chat(request: Request, body: ChatRequest):
    """用户消息 → 主代理（skill 消费模式）→ 异步任务。

    若带 ask_id：优先当作对 ask_user 的回答喂给等待中的任务（WS 断线兜底），
    匹配成功则不再开新任务。
    """
    msg = (body.message or "").strip()
    from ..core.master import master

    # 契约（问题13）：HTTP 侧 email = 登录 email；前端连 /api/v1/ws 时必须用同一 email
    # 作为 email 注册（session_ready），否则 bridge 找不到设备，skill_run / ask_user 推送会失败。
    email = _my_email(request) or "anon"
    ask_id = (body.ask_id or "").strip()
    if ask_id:
        from ..core.master import feed_answer
        # 铁律（2026-08-16）：回答路由不静默吞异常，暴露 ask_id 链路问题
        if feed_answer(email, ask_id, msg):
            return {"status": "ok", "reply": "", "task": None, "answered": True}
    if not msg:
        return {"status": "ok", "reply": "", "task": None}
    user_id = getattr(request.state, "user_id", "") or email
    conv_id = (body.session_id or "").strip() or "default"
    out = master.submit(email, message=msg, user_id=user_id, conversation_id=conv_id)
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

class PersonaRef(BaseModel):
    """会话人设 = 引用上台卡（只挂 id，不复制卡/证件）。
    只收 person_id / person_name / skills[] 三样；skills 里的元素 = 上台卡挂的 skill id（如 glyy）。"""
    person_id: str = ""
    person_name: str = ""
    skills: list[str] = []


class ConvCreate(BaseModel):
    type: str = "chat"        # chat / skill
    persona: PersonaRef = Field(default_factory=PersonaRef)


def _validate_persona(p: PersonaRef) -> dict | None:
    """persona 只收引用上台卡：person_id 必须在 cards.json 存在且 status=on 才允许落库。
    落库结构固定 {person_id, person_name, skills[]}，不复制整张卡、更不碰证件。
    卡不存在/未上场返回 None（调用方转 200+{ok:false}）。"""
    if not p:
        return {}
    pid = (p.person_id or "").strip()
    if not pid:
        return {}
    from ..store.archive_center.skill_archive.cards import cards

    card = cards.get(pid)
    if not card or card.get("status") != "on":
        return None
    return {
        "person_id": pid,
        "person_name": (p.person_name or "").strip() or (card.get("name") or ""),
        "skills": [s["id"] for s in (card.get("skills") or [])
                   if isinstance(s, dict) and s.get("id")],
    }


class ConvUpdate(BaseModel):
    title: str | None = None
    pinned: bool | None = None


def _me_ids(request: Request):
    email = _my_email(request)
    user_id = getattr(request.state, "user_id", "") or email
    return email, user_id


def _own_conv(request: Request, conv_id: str):
    """取归属当前用户的会话；default 自动创建。无权限返回 None（调用方转 200+{ok:false}）。"""
    from ..store.archive_center.consumer_archive.conversations import conversations

    _, user_id = _me_ids(request)
    if conv_id == "default":
        conv = conversations.get_default(user_id)
    else:
        conv = conversations.get(conv_id)
    if not conv or conv.user_id != user_id:
        return None
    return conv


@router.get("/api/v1/conversations")
async def list_conversations(request: Request):
    from ..store.archive_center.consumer_archive.conversations import conversations

    _, user_id = _me_ids(request)
    conversations.get_default(user_id)  # 确保 default 存在
    lst = conversations.list_by_user(user_id)
    # 列表轻量返回（不含 messages）
    return {"ok": True, "conversations": [
        {k: v for k, v in c.to_dict().items() if k != "messages"} for c in lst
    ]}


@router.post("/api/v1/conversations")
async def create_conversation(request: Request, body: ConvCreate):
    from ..store.archive_center.consumer_archive.conversations import conversations

    _, user_id = _me_ids(request)
    persona = _validate_persona(body.persona)
    if persona is None:
        return {"ok": False, "detail": "上台卡不存在或未上场"}
    conv = conversations.create(user_id, type=body.type or "chat", persona=persona)
    # 找人会话：标题用上台卡名字，避免首条消息把标题改成用户原话
    if persona.get("person_name"):
        conversations.set_title(conv.conversation_id, str(persona["person_name"])[:40])
        conv = conversations.get(conv.conversation_id) or conv
    return {"ok": True, "conversation": conv.to_dict()}


@router.get("/api/v1/conversations/{conv_id}/messages")
async def get_conv_messages(request: Request, conv_id: str):
    conv = _own_conv(request, conv_id)
    if not conv:
        return {"ok": False, "detail": "会话不存在"}
    return {"ok": True, "conversation": conv.to_dict()}


@router.put("/api/v1/conversations/{conv_id}")
async def update_conversation(request: Request, conv_id: str, body: ConvUpdate):
    from ..store.archive_center.consumer_archive.conversations import conversations

    if not _own_conv(request, conv_id):
        return {"ok": False, "detail": "会话不存在"}
    if body.title is not None:
        conversations.set_title(conv_id, body.title)
    if body.pinned is not None:
        conversations.set_pinned(conv_id, body.pinned)
    return {"ok": True}


@router.post("/api/v1/conversations/{conv_id}/clear")
async def clear_conversation(request: Request, conv_id: str):
    from ..store.archive_center.consumer_archive.conversations import conversations

    if not _own_conv(request, conv_id):
        return {"ok": False, "detail": "会话不存在"}
    conversations.clear_messages(conv_id)
    return {"ok": True}


@router.delete("/api/v1/conversations/{conv_id}")
async def delete_conversation(request: Request, conv_id: str):
    from ..store.archive_center.consumer_archive.conversations import conversations

    if not _own_conv(request, conv_id):
        return {"ok": False, "detail": "会话不存在"}
    if conv_id == "default":
        return {"ok": False, "detail": "默认会话不可删除"}
    conversations.delete(conv_id)
    return {"ok": True}


# ═══════════════════ 才艺分区（上台卡；与客户资料区隔离）═══════════════════

@router.get("/api/v1/cards")
async def api_list_cards(q: str = "", cat: str = "", sort: str = "score"):
    from ..store.archive_center.skill_archive.cards import cards

    return {"ok": True, "cards": cards.list(q=q, cat=cat, sort=sort)}


@router.get("/api/v1/cards/{card_id}")
async def api_get_card(card_id: str):
    from ..store.archive_center.skill_archive.cards import cards

    card = cards.get(card_id)
    if not card or card.get("status") != "on":
        return {"ok": False, "detail": "这张上台卡不在场"}
    return {"ok": True, "card": card}


# ═══════════════════ 客户资料区 ═══════════════════

@router.get("/api/v1/me")
async def me(request: Request):
    from ..store.archive_center.consumer_archive.users import users
    from ..adapters import registry as _reg

    email = _my_email(request)
    if not email:
        return {"ok": False, "detail": "未登录"}
    u = users.touch(email)
    # 「我的才艺」云端绑定、本地只显示：返回已注册且 AI 可见的 skill 清单。
    # 当前单主人（skill 均挂 owner=jintao）；未来多用户需按账号绑定 owner 过滤。
    skills = [
        {"id": s.get("skill"), "skill": s.get("skill"),
         "name": s.get("name"), "category": s.get("category") or "",
         "aliases": s.get("aliases") or [],
         "can_run": True, "status": "active"}
        for s in _reg.list_skills()
        if s.get("skill")
    ]
    return {"ok": True, "user": _user_view(u), "skills": skills}


@router.put("/api/v1/me")
async def update_me(request: Request, body: MeUpdate):
    from ..store.archive_center.consumer_archive.users import users

    email = _my_email(request)
    u = users.update(
        email,
        nickname=body.nickname,
        bio=body.bio,
        avatar=body.avatar,
    )
    if not u:
        return {"ok": False, "detail": "用户不存在"}
    return {"ok": True, "user": _user_view(u)}


# ═══════════════════ WebSocket 执行通道 ═══════════════════

@router.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str | None = None, email: str | None = None):
    from ..channel.ws import handle_websocket

    manager = get_manager()
    if session_id:
        session = manager.get(session_id)
        if session:
            session.websocket = websocket
    await handle_websocket(websocket, session_id, email)


# ═══════════════════ Skill 消费 API（搜索 / 直调）═══════════════════
# 向量搜索：本地 BGE 两级检索（retrieval 模块，零网络零成本，从各 skill 的
# contract.json 自动构建）。skill 契约改动后重启云端即自动更新，无需手动重建索引；
# 旧的千问云端 skill_index.json 方案已废弃删除（避免每句话调云端 embedding）。

from ..adapters import registry as _skill_registry


def _skill_intent(pid: str, owner_id: str = "") -> str:
    """App 搜索接口展示的一句话意图。"""
    cfg = _skill_registry.get_adapter(pid, owner_id) or {}
    return str(cfg.get("capability_note") or cfg.get("capability") or "")


class SkillRunRequest(BaseModel):
    method: str
    params: dict = {}
    email: str = ""   # 必传；空则 registry 直接报错（禁云端直发）
    owner_id: str = ""    # 人签名；缺省时仅当 skill id 全局唯一才可跑


@router.get("/api/v1/skills")
async def api_list_skills(owner_id: str = ""):
    """skill 清单；可传 owner_id 只看某人档案下挂的才艺。"""
    return {"skills": _skill_registry.list_skills(owner_id=owner_id)}


@router.get("/api/v1/skills/search")
async def api_search_skills(q: str = "", k: int = 3, owner_id: str = ""):
    """向量搜索 skill（本地 BGE）；可按 owner_id 收窄到某人。"""
    if not q:
        return {"results": []}
    try:
        from ..retrieval.index import get_index
        idx = get_index()
        if idx is None:
            return {"results": [], "note": "本地向量模型不可用（需 pip install sentence-transformers 并加载 bge-small-zh-v1.5）"}
        plats = idx.search_platform(q, top_k=max(1, k))
        oid = (owner_id or "").strip()
        if oid:
            plats = [p for p in plats if str(p.get("owner_id") or "") == oid]
    except Exception as e:
        return {"results": [], "note": f"向量检索异常：{e}"}
    return {"results": [
        {"skill": p["platform"], "owner_id": p.get("owner_id", ""),
         "score": round(p["score"], 4),
         "name": p["text"],
         "intent": _skill_intent(p["platform"], str(p.get("owner_id") or ""))}
        for p in plats]}


@router.post("/api/v1/dev/index/rebuild")
async def dev_rebuild_index():
    """手动重建向量索引（新增/修改 skill 后调用，无需重启服务；问题⑧）。

    正常情况 get_index 会自动检测磁盘变化并重建；本接口用于需要立即刷新的运维场景。
    """
    try:
        from ..retrieval import register as idx_register
        ok = idx_register.rebuild()
        return {"ok": ok, "msg": "索引已重建" if ok else "索引重建失败（向量模型不可用）"}
    except Exception as e:
        return {"ok": False, "error": f"索引重建异常：{e}"}


@router.post("/api/v1/skills/{skill_id}/run")
async def api_run_skill(skill_id: str, body: SkillRunRequest):
    """直接消费 skill。owner_id 建议必传（各人签名）。"""
    return await _skill_registry.run(
        skill_id, body.method, body.params or {},
        email=body.email, owner_id=body.owner_id or "",
    )


@router.post("/api/v1/dev/browser")
async def dev_browser(body: dict):
    """调试：向手机内置浏览器下发指令并拿结果（read_frames/click/slider/navigate…）。
    POST /api/v1/dev/browser {email, cmd, params}。"""
    email = str(body.get("email", ""))
    cmd = str(body.get("cmd", ""))
    params = body.get("params") or {}
    if not email or not cmd:
        return {"ok": False, "error": "need email+cmd"}
    try:
        from ..channel.bridge import bridge
        res = await bridge.send_cmd(email, cmd, params)
        return {"ok": True, "res": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}
