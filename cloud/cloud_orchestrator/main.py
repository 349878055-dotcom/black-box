"""
个人助理5 · 云端入口 — FastAPI 应用（API 优先，端口 19000）。

启动：
  cd 个人助理5 && PYTHONPATH=. python -m cloud.cloud_orchestrator.main
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get
from .api.routes import router as api_router
from .auth import auth_middleware

app = FastAPI(title="个人助理5 · API 优先云端", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(auth_middleware)

app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run(
        "cloud.cloud_orchestrator.main:app",
        host=get("host", "0.0.0.0"),
        port=int(get("port", 19000)),
        reload=False,
    )
