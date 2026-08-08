"""
认证中间件 — JWT Bearer Token 验证

使用 config.json 中的 auth.api_key 作为共享密钥。
客户端在登录时从 /api/v1/auth/login 获取 JWT token。
"""
import time
import hashlib
import hmac
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from .config import get


def _secret() -> str:
    return get("jwt_secret", "") or "xiamiaban-default-secret"


def create_token(email: str) -> str:
    """生成简单 JWT（非标准 JWT，仅用于内部认证）"""
    payload = f"email={email}&ts={int(time.time())}&exp={int(time.time()) + 86400 * 7}"
    sig = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}&sig={sig}"


def verify_token(token: str) -> str | None:
    """验证 token，返回 email 或 None"""
    try:
        parts = token.split("&sig=")
        if len(parts) != 2:
            return None
        payload, sig = parts
        expected = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
        if sig != expected:
            return None
        # 解析 payload
        params = {}
        for kv in payload.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k] = v
        # 检查过期
        exp = int(params.get("exp", 0))
        if time.time() > exp:
            return None
        return params.get("email", "")
    except Exception:
        return None


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
    ]
    if request.url.path in public_paths:
        return await call_next(request)

    # 静态资源（测试壳子 phone_test_shell.html 等）无需认证
    if request.url.path.startswith("/static"):
        return await call_next(request)

    if not get("auth_enabled", True):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "未提供认证令牌"})

    token = auth_header[7:]
    email = verify_token(token)
    if not email:
        return JSONResponse(status_code=401, content={"detail": "认证令牌无效或已过期"})

    # 将用户信息注入请求
    request.state.user_email = email
    return await call_next(request)
