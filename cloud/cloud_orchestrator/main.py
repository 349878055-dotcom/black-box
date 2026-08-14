"""
个人助理5 · 云端入口 — FastAPI 应用（API 优先，端口 19000）。

启动：
  cd 个人助理5 && PYTHONPATH=. python -m cloud.cloud_orchestrator.main
"""
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get
from .api.routes import router as api_router
from .auth import auth_middleware

# 让 xiami.* 业务 logger（registry/executor/glyy/...）输出到 stderr（含 /tmp/cloud.log）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)

app = FastAPI(title="个人助理5 · API 优先云端", version="0.1.0")

# 认证中间件放内层，CORS 放最外层（后加的 add_middleware 在最外层）：
# 否则 auth 中间件对 401/403 直接短路返回，不带 CORS 头 → App 的 file:// 页面（origin=null）
# fetch 被 CORS 拦截抛错，拿不到 res.status=401 → 自动刷新 token 逻辑永不触发 →
# access 过期后手机 WS 永远连不上（表现为"手机接不上去了"）。
app.middleware("http")(auth_middleware)

app.add_middleware(
    CORSMiddleware,
    # 2026-08-11 修复：allow_credentials=True 与 allow_origins=["*"] 不兼容，
    # 手机 App（file:// origin=null）fetch /api/v1/* 被 CORS 拦截 → 任务轮询失败、UI 不同步。
    # 认证走 Bearer token（不依赖 cookie），故 allow_credentials=False。
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# 静态资源（测试壳子 phone_test_shell.html 等，浏览器直接访问 http://140.143.144.28/static/...）
from fastapi.staticfiles import StaticFiles
import os as _os

_STATIC_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "static")
_os.makedirs(_STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


if __name__ == "__main__":
    uvicorn.run(
        "cloud.cloud_orchestrator.main:app",
        host=get("host", "0.0.0.0"),
        port=int(get("port", 19000)),
        reload=False,
    )
