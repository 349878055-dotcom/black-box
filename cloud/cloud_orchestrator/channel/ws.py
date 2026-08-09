"""
SessionExecutor — WebSocket 执行通道（统一主脑后简化版）。

职责（v2 平台化 / Device-as-Proxy）：
  - WS 连接建立 → 按 device_id 注册到 DeviceBridge
  - MasterAgent 经 bridge 与客户端交互：ask_user 推送问题 + 等用户输入；
    浏览器指令（navigate/click/fill/read/...）为 App 内置浏览器预留
    （登录/验证码/看页面时人工配合用，主代理不主动驱动）
  - skill 执行通道：云端下发「请求蓝图」skill_request → 手机直连平台 →
    回传原始响应 skill_result（第 1 条改造：WS 协议扩展）
  - 收 result → 喂 _pending_result；收 user_input → 喂 _pending_user_input
  - 断开 → 注销 bridge
"""
import asyncio
import json
import logging
import uuid
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
        # skill 执行通道：req_id → Future（可并发多个 skill_request）
        self._pending_skill: dict[str, asyncio.Future] = {}

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
                bridge.register(device_id, self._send_and_wait, self._wait_user_input,
                                self.send_skill_request)

        elif msg_type == "result":
            if self._pending_result and not self._pending_result.done():
                self._pending_result.set_result(data)

        elif msg_type == "user_input":
            if self._pending_user_input and not self._pending_user_input.done():
                self._pending_user_input.set_result(data.get("value", ""))

        elif msg_type == "user_action":
            self.session.context["last_user_action"] = data

        elif msg_type == "skill_result":
            # 手机回传的 skill 执行结果（第 1 条：skill_request / skill_result 协议）
            # 字段按方案文档放消息顶层：req_id / ok / status / headers / body / error
            req_id = str(msg.get("req_id") or data.get("req_id") or "")
            logger.info("[executor] 收到 skill_result req=%s ok=%s status=%s err=%s",
                        req_id, msg.get("ok", data.get("ok")),
                        msg.get("status", data.get("status")),
                        str(msg.get("error") or data.get("error") or "")[:80])
            fut = self._pending_skill.pop(req_id, None)
            if fut and not fut.done():
                fut.set_result({
                    "req_id": req_id,
                    "ok": bool(msg.get("ok", data.get("ok", True))),
                    "status": msg.get("status", data.get("status")),
                    "headers": msg.get("headers") or data.get("headers") or {},
                    "body": msg.get("body", data.get("body", "")),
                    "error": str(msg.get("error") or data.get("error") or ""),
                })
            else:
                logger.warning("[executor] skill_result 无匹配 req_id=%s", req_id)

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

    async def send_skill_request(self, payload: dict) -> dict:
        """下发 skill_request 请求蓝图给手机，阻塞等 skill_result 回传（第 1 条）。

        payload（云端→手机，字段放顶层）：
          {
            "skill": "glyy",    # skill 标识（平台）
            "request": {        # 请求蓝图
              "method", "url", "headers", "body", "sign_type"
            },
            "credential": {     # 本地凭据提示
              "kind": "bearer|cookie", "target": "glyy|tuniu"
            }
          }
        手机执行后回 skill_result：{req_id, ok, status, headers, body, error}
        """
        req_id = str(uuid.uuid4())[:12]
        msg = {
            "type": "skill_request",
            "req_id": req_id,
            "skill": str(payload.get("skill") or ""),
            "request": payload.get("request") or {},
            "credential": payload.get("credential") or {},
            # 方案②：登录配置随蓝图下发（手机端 LoginCoordinator 据此检测登录信号并接管登录）
            "login": payload.get("login") or {},
        }
        logger.info("[executor] 下发 skill_request req=%s skill=%s url=%s",
                    req_id, msg["skill"],
                    str(msg["request"].get("url", ""))[:80])
        fut = asyncio.get_event_loop().create_future()
        self._pending_skill[req_id] = fut
        await self._send(msg)
        try:
            result = await asyncio.wait_for(fut, timeout=120)
            return result if isinstance(result, dict) else {}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "手机执行 skill 超时（请确认 App 在线）",
                    "req_id": req_id}
        finally:
            self._pending_skill.pop(req_id, None)

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
        for req_id, fut in list(self._pending_skill.items()):
            if not fut.done():
                fut.cancel()
        self._pending_skill.clear()
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
