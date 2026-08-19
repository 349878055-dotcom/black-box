"""
SessionExecutor — WebSocket 执行通道（统一主脑后简化版）。

职责（v2 平台化 / Device-as-Proxy）：
  - WS 连接建立 → 按 email 注册到 DeviceBridge
  - MasterAgent 经 bridge 与客户端交互：ask_user 推送问题 + 等用户输入；
    浏览器指令仅剩登录用：navigate 打开登录页 / clear_cookies / export_cookies /
    export_token / check_ready（真人登录人工配合；主代理不驱动其他浏览器遥控；
    支付只回产物链接/scheme，由客户端系统浏览器打开）
  - skill 执行通道：云端下发「请求蓝图」skill_request → 手机直连平台 →
    回传原始响应 skill_result（第 1 条改造：WS 协议扩展）
  - 收 result → 喂 _pending_result；收 user_input → 喂 _pending_user_input
  - 断开 → 注销 bridge
"""
import asyncio
import json
import logging
import uuid

from fastapi import WebSocket

from .session import Session, get_manager

logger = logging.getLogger(__name__)


class SessionExecutor:
    """WS 执行通道 — 每个 WebSocket 连接对应一个 executor"""

    def __init__(self, session: Session, email: str | None = None):
        self.session = session
        self.ws = session.websocket
        self.email = email or None
        self._running = True
        # 等待客户端返回结果的 Future（指令回执）
        self._pending_result: asyncio.Future | None = None
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
            email = data.get("email") or self.email
            if email:
                from .bridge import bridge

                self.email = email
                bridge.register(email, self._send_and_wait,
                                self.send_skill_request, self.send_push)

        elif msg_type == "result":
            if self._pending_result and not self._pending_result.done():
                self._pending_result.set_result(data)

        elif msg_type == "user_input":
            value = str(data.get("value", "") or "")
            ask_id = str(data.get("ask_id") or msg.get("ask_id") or "")
            # 铁律（2026-08-16）：回答只走 feed_answer，不保留兜底旧逻辑——
            # 兜底会掩盖 ask_id 回答路由的问题。匹配失败/无等待 → 明确记录。
            from ..core.master import feed_answer
            if not feed_answer(self.email or "", ask_id, value):
                logger.warning("[executor] user_input 无匹配的等待任务（可能无 ask 或 ask_id 过期）"
                               " device=%s ask_id=%s value=%s",
                               self.email, ask_id, str(value)[:40])

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
            logger.debug("[executor] ping from device=%s", self.email)
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

    async def send_push(self, cmd: str, params: dict) -> None:
        """只发不等回执（task_update 等实时通知），供 DeviceBridge.send_push 调用。"""
        await self._send({"cmd": cmd, "params": params})

    async def _send_and_wait(self, cmd: str, params: dict) -> dict:
        """发送指令并等待客户端返回 result（供 DeviceBridge / 工具驱动使用）"""
        self._pending_result = asyncio.get_running_loop().create_future()
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
            },
            "store": {...},        # 登录成功后手机写入凭据库（必须透传）
            "auto_refresh": bool,  # token 静默续期（必须透传）
            "login": {...},
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
        # 登录回写 / 静默续期：整份透传，否则手机 SkillExecutor 存不上 token
        if payload.get("store") is not None:
            msg["store"] = payload.get("store")
        if "auto_refresh" in payload:
            msg["auto_refresh"] = bool(payload.get("auto_refresh"))
        # 续期接口配置随蓝图透传（skill 下发，App 只执行）
        if payload.get("refresh") is not None:
            msg["refresh"] = payload.get("refresh")
        # 响应裁剪 / 资料卡选卡：随蓝图透传（App 按配置裁剪响应、选资料卡）
        if payload.get("response") is not None:
            msg["response"] = payload.get("response")
        if payload.get("profile_card"):
            msg["profile_card"] = str(payload.get("profile_card"))
        logger.info("[executor] 下发 skill_request req=%s skill=%s url=%s",
                    req_id, msg["skill"],
                    str(msg["request"].get("url", ""))[:80])
        fut = asyncio.get_running_loop().create_future()
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

    def _cleanup(self):
        """清理资源：注销设备通道、销毁会话"""
        self._running = False
        if self.email:
            try:
                from .bridge import bridge

                bridge.unregister(self.email)
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
    email: str | None = None,
):
    """
    WebSocket 入口 — 接受连接并启动执行通道
    email 可经 URL 查询参数传入（设备标识，供 MasterAgent 驱动）
    """
    await websocket.accept()

    manager = get_manager()

    session = manager.get(session_id) if session_id else None
    if not session:
        session = manager.create(websocket)
    else:
        session.websocket = websocket

    executor = SessionExecutor(session, email=email)
    await executor.start()
