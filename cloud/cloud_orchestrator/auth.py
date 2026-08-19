"""
认证中间件 — 双 Token（Access 短期 JWT 式 + Refresh 长期可吊销）

- Access Token（约 2h）：自研 HMAC 签名，无状态，携带 email+user_id；
- Refresh Token（约 30 天）：高熵随机串，服务端登记（refresh_tokens.json），可吊销/轮换。

客户端登录后拿到 access + refresh；access 过期用 refresh 换新（refresh 会轮换）；
登出/改密可吊销 refresh，强制重新登录。
"""
import hashlib
import hmac
import logging
import time
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import get
from .store.refresh_tokens import refresh_store

logger = logging.getLogger("xiami.auth")

ACCESS_TTL = 2 * 3600          # Access 有效期 2 小时
REFRESH_TTL = 30 * 86400       # Refresh 有效期 30 天

# 内置默认密钥：仅限开发环境；已配置真实密钥时置空。生产必须配置 cloud/config.json 的 auth.api_key
_DEFAULT_SECRET = "xiamiaban-default-secret"
_warned_default_secret = False


def _secret() -> str:
    global _warned_default_secret
    s = get("jwt_secret", "") or _DEFAULT_SECRET
    if s == _DEFAULT_SECRET and not _warned_default_secret:
        _warned_default_secret = True
        logger.warning(
            "jwt_secret 未配置，正在使用内置默认密钥（不安全）——"
            "生产环境必须配置 cloud/config.json 的 auth.api_key，否则 Access Token 可被伪造"
        )
    return s


def _sign(payload: str) -> str:
    # 完整 SHA-256 摘要（64 hex = 256 bit），不再截断到 16 hex（64 bit 碰撞空间太小）
    return hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_access_token(email: str, user_id: str = "") -> str:
    """生成 Access Token（HMAC 签名，无状态）。

    email/uid 用 URL 编码放入 payload，避免 email 含 & 或 = 时破坏 & 分隔的字段解析。
    """
    payload = (
        f"email={quote(str(email), safe='')}&uid={quote(str(user_id), safe='')}"
        f"&ts={int(time.time())}&exp={int(time.time()) + ACCESS_TTL}"
    )
    return f"{payload}&sig={_sign(payload)}"


def verify_token(token: str) -> dict | None:
    """验证 Access Token，返回 {email, user_id}；无效/过期返回 None。"""
    try:
        parts = token.split("&sig=")
        if len(parts) != 2:
            return None
        payload, sig = parts
        if _sign(payload) != sig:
            return None
        params = {}
        for kv in payload.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k] = v
        exp = int(params.get("exp", 0))
        if time.time() > exp:
            return None
        return {
            "email": unquote(params.get("email", "")),
            "user_id": unquote(params.get("uid", "")),
        }
    except Exception:
        return None


def create_tokens(email: str, user_id: str = "") -> dict:
    """登录/注册成功后签发双 token。user_id 缺失时回退 email。"""
    uid = user_id or email
    access = create_access_token(email, uid)
    refresh = refresh_store.create(uid, email, ttl=REFRESH_TTL)
    return {"access_token": access, "refresh_token": refresh, "user_id": uid}


def refresh_access(refresh_token: str) -> dict | None:
    """用 Refresh Token 换新 Access（并轮换 Refresh）。
    无效/过期/已吊销返回 None。"""
    rec = refresh_store.get_valid(refresh_token)
    if not rec:
        return None
    email = rec.get("email", "")
    uid = rec.get("user_id", "") or email
    # 轮换：吊销旧 refresh，签发新的一对
    refresh_store.revoke(refresh_token)
    return create_tokens(email, uid)


def revoke_refresh(refresh_token: str) -> None:
    """吊销单条 refresh token（登出）。"""
    refresh_store.revoke(refresh_token)


def revoke_all_for_email(email: str) -> None:
    """吊销某账号全部 refresh token（改密/被踢）。"""
    refresh_store.revoke_all_for_email(email)


async def auth_middleware(request: Request, call_next):
    """FastAPI 中间件：验证 Authorization Header"""
    # CORS 预检请求（OPTIONS）直接放行，交给 CORSMiddleware 处理
    if request.method == "OPTIONS":
        return await call_next(request)

    # 公开端点不需要认证
    public_paths = [
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
    ]
    if request.url.path in public_paths:
        return await call_next(request)
    # 才艺分区只读：未登录也能逛上台卡
    if request.method == "GET" and (
        request.url.path == "/api/v1/cards"
        or request.url.path.startswith("/api/v1/cards/")
    ):
        return await call_next(request)

    if not get("auth_enabled", True):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "未提供认证令牌"})

    token = auth_header[7:]
    info = verify_token(token)
    if not info:
        return JSONResponse(status_code=401, content={"detail": "认证令牌无效或已过期"})

    # 将用户信息注入请求：user_email（兼容既有业务隔离键）+ user_id（新主键）
    request.state.user_email = info.get("email", "")
    request.state.user_id = info.get("user_id", "") or info.get("email", "")
    return await call_next(request)
