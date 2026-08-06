"""
SessionExecutor — WebSocket 执行通道（统一主脑后简化版）。

职责（v2 平台化）：
  - WS 连接建立 → 按 device_id 注册到 DeviceBridge
  - MasterAgent 经 bridge 与客户端交互：ask_user 推送问题 + 等用户输入；
    浏览器指令（navigate/click/fill/read/...）为 App 内置浏览器预留
    （登录/验证码/看页面时人工配合用，主代理不主动驱动）
  - 收 result → 喂 _pending_result；收 user_input → 喂 _pending_user_input
  - 断开 → 注销 bridge
"""
import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from .session import Session, get_manager

logger = logging.getLogger(__name__)


class SessionExecutor:
    """WS 执行通道 — 每个 WebSocket 连接对应一个 executor"""

    def __init__(self, session: Session, device_id: str | None = None):
        self.session = session
        self.ws = session.websocket
        self.device_id = device_id or None
        self._running = True
        # 等待客户端返回结果的 Future（指令回执）
        self._pending_result: asyncio.Future | None = None
        # 等待用户文字输入的 Future（ask_user 暂停-恢复）
        self._pending_user_input: asyncio.Future | None = None

    async def start(self):
        """执行循环：收消息 → 处理"""
        try:
            while self._running:
                raw = await self.ws.receive_text()
                msg = json.loads(raw)
                await self._handle_message(msg)
        except Exception as e:
            logger.info("[executor] 会话结束: %s", e)
        finally:
            self._cleanup()

    async def _handle_message(self, msg: dict):
        """处理单条客户端消息"""
        msg_type = msg.get("type", "")
        data = msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}

        self.session.last_active = __import__("time").time()

        if msg_type == "session_ready":
            # 注册设备执行通道（供 MasterAgent 经 DeviceBridge 驱动本客户端）
            device_id = data.get("device_id") or self.device_id
            if device_id:
                from .bridge import bridge

                self.device_id = device_id
                bridge.register(device_id, self._send_and_wait, self._wait_user_input)

        elif msg_type == "result":
            if self._pending_result and not self._pending_result.done():
                self._pending_result.set_result(data)

        elif msg_type == "user_input":
            if self._pending_user_input and not self._pending_user_input.done():
                self._pending_user_input.set_result(data.get("value", ""))

        elif msg_type == "user_action":
            self.session.context["last_user_action"] = data

        elif msg_type == "ping":
            await self._send({"cmd": "pong", "params": {}})

        else:
            logger.warning("[executor] 未知消息类型: %s", msg_type)

    async def _send(self, msg: dict):
        """向客户端发送指令"""
        if self.ws and self._running:
            try:
                await self.ws.send_text(json.dumps(msg))
            except Exception:
                self._running = False

    async def _send_and_wait(self, cmd: str, params: dict) -> dict:
        """发送指令并等待客户端返回 result（供 DeviceBridge / 工具驱动使用）"""
        self._pending_result = asyncio.get_event_loop().create_future()
        await self._send({"cmd": cmd, "params": params})
        try:
            result = await asyncio.wait_for(self._pending_result, timeout=120)
            return result if isinstance(result, dict) else {}
        except asyncio.TimeoutError:
            return {"error": "客户端执行超时"}
        finally:
            self._pending_result = None

    async def _wait_user_input(self, timeout: float = 600) -> str | None:
        """阻塞等待用户在客户端输入文字（ask_user 暂停-恢复）。"""
        self._pending_user_input = asyncio.get_event_loop().create_future()
        try:
            return await asyncio.wait_for(self._pending_user_input, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending_user_input = None

    def _cleanup(self):
        """清理资源：注销设备通道、销毁会话"""
        self._running = False
        if self.device_id:
            try:
                from .bridge import bridge

                bridge.unregister(self.device_id)
            except Exception:
                pass
        if self._pending_result and not self._pending_result.done():
            self._pending_result.cancel()
        try:
            get_manager().destroy(self.session.session_id)
        except Exception:
            pass


async def handle_websocket(
    websocket: WebSocket,
    session_id: str | None = None,
    device_id: str | None = None,
):
    """
    WebSocket 入口 — 接受连接并启动执行通道
    device_id 可经 URL 查询参数传入（设备标识，供 MasterAgent 驱动）
    """
    await websocket.accept()

    manager = get_manager()

    session = manager.get(session_id) if session_id else None
    if not session:
        session = manager.create(websocket)
    else:
        session.websocket = websocket

    executor = SessionExecutor(session, device_id=device_id)
    await executor.start()
