"""
会话管理 — WebSocket 会话的创建、查找、销毁

每个用户消息 → POST /plan → 创建 session → WebSocket 执行 → 销毁
"""
import time
import uuid
from typing import Any
from fastapi import WebSocket


class Session:
    """单个执行会话"""

    def __init__(self, session_id: str, websocket: WebSocket | None = None):
        self.session_id = session_id
        self.websocket = websocket
        self.created_at = time.time()
        self.last_active = time.time()
        # 会话上下文（由 pipeline 填充）
        self.context: dict[str, Any] = {}
        # 计划步骤
        self.plan: list[dict] = []
        # 是否在等待用户输入
        self.waiting_for_user = False

    def is_expired(self, max_age_sec: int = 300) -> bool:
        """检查会话是否过期（默认 5 分钟无活动）"""
        return (time.time() - self.last_active) > max_age_sec


class SessionManager:
    """全局会话管理器"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        # 任务级记忆（跨 WS 销毁仍保留一段时间，供 task_id 续聊）
        self._task_store: dict[str, dict] = {}

    def save_task(self, task_id: str, data: dict, *, max_keep: int = 200):
        """保存任务记忆。"""
        self._task_store[task_id] = {
            **data,
            "_saved_at": time.time(),
        }
        if len(self._task_store) > max_keep:
            # 丢掉最旧的
            oldest = sorted(self._task_store.items(), key=lambda kv: kv[1].get("_saved_at", 0))
            for tid, _ in oldest[: len(self._task_store) - max_keep]:
                self._task_store.pop(tid, None)

    def load_task(self, task_id: str, *, max_age_sec: int = 3600) -> dict | None:
        data = self._task_store.get(task_id)
        if not data:
            return None
        if time.time() - float(data.get("_saved_at", 0)) > max_age_sec:
            self._task_store.pop(task_id, None)
            return None
        return data

    def create(self, websocket: WebSocket | None = None) -> Session:
        """创建新会话（自动生成 ID）"""
        session_id = uuid.uuid4().hex[:12]
        return self.create_with_id(session_id, websocket)

    def create_with_id(self, session_id: str, websocket: WebSocket | None = None) -> Session:
        """创建指定 ID 的会话（由 orchestrator 预生成 ID 时使用）"""
        session = Session(session_id, websocket)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        """获取会话"""
        session = self._sessions.get(session_id)
        if session and session.is_expired():
            self.destroy(session_id)
            return None
        return session

    def get_by_ws(self, websocket: WebSocket) -> Session | None:
        """通过 WebSocket 连接查找会话"""
        for session in self._sessions.values():
            if session.websocket == websocket:
                return session
        return None

    def destroy(self, session_id: str):
        """销毁会话"""
        self._sessions.pop(session_id, None)

    def cleanup_expired(self):
        """清理过期会话"""
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            self.destroy(sid)
        return len(expired)


# 全局单例
_manager: SessionManager | None = None


def get_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
