"""
DeviceBridge — 按 email 路由「执行通道」。

云端 MasterAgent 要与某台设备的客户端交互时（ask_user 推送问题 / 等用户输入 /
浏览器人工配合：登录/验证码），通过 bridge 找到该设备当前活跃的 WS 执行器
（手机 App），发 send_cmd 指令并等待 result。

Device-as-Proxy（第 1 条）：bridge 同时承载「skill 执行通道」——
云端下发 skill_request 请求蓝图 → 手机直连平台 → 回传 skill_result，
云端不再直发平台请求。

每台设备的 WS 连接建立后注册：
  register(email, send_cmd, send_skill_request, send_push)
断线后 unregister。
（ask_user 交互统一走 LangGraph interrupt + feed_graph_resume，不占 bridge 的 wait_user_input 槽）

单例：from .bridge import bridge
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("xiami.device_bridge")

SendCmd = Callable[[str, dict], Awaitable[dict]]
SendSkillRequest = Callable[[dict], Awaitable[dict]]
SendPush = Callable[[str, dict], Awaitable[Any]]


class DeviceBridge:
    def __init__(self) -> None:
        self._devices: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def register(self, email: str, send_cmd: SendCmd,
                 send_skill_request: SendSkillRequest | None = None,
                 send_push: SendPush | None = None) -> None:
        """设备执行通道上线（WS 连接成功时）。"""
        if not email:
            return
        self._devices[email] = {
            "send_cmd": send_cmd,
            "send_skill_request": send_skill_request,
            "send_push": send_push,
        }
        logger.info("[bridge] 设备执行通道上线 device=%s 在线=%d", email, len(self._devices))

    def unregister(self, email: str) -> None:
        if email in self._devices:
            del self._devices[email]
            logger.info("[bridge] 设备执行通道下线 device=%s 在线=%d", email, len(self._devices))

    def has(self, email: str) -> bool:
        return email in self._devices

    def online_devices(self) -> list[str]:
        return list(self._devices.keys())

    async def send_push(self, email: str, cmd: str, params: dict | None = None) -> bool:
        """向设备推送一条指令（只发不等回执），用于 task_update 等实时通知，不阻塞。

        返回 bool 表示是否真正发出（设备未注册 / 无推送通道 → False）。
        铁律（2026-08-19）：设备未注册绝不静默——先尝试从活跃 WS 会话自动恢复注册，
        恢复失败再记 warning 日志暴露 WS 链路问题，否则 task_update 推不回手机时无从排查。
        """
        entry = self._devices.get(email)
        if not entry:
            # 根治（2026-08-19）：注册状态可能因服务长时间运行/WS 重连而意外丢失。
            # 尝试从活跃会话按 email 找回并重新注册，避免 task_update 静默丢失。
            if self._try_recover(email):
                entry = self._devices.get(email)
                logger.info(
                    "[bridge] send_push 自动恢复注册成功 device=%s cmd=%s", email, cmd
                )
            else:
                logger.warning(
                    "[bridge] send_push 设备未注册且无活跃会话可恢复（执行通道不在线）"
                    "device=%s cmd=%s 在线设备=%s —— 推送无法送达，请检查手机 WS 是否已 session_ready 注册",
                    email, cmd, list(self._devices.keys()),
                )
                return False
        fn = entry.get("send_push")
        if not fn:
            logger.warning(
                "[bridge] send_push 设备已注册但无推送通道 device=%s cmd=%s", email, cmd
            )
            return False
        try:
            await fn(cmd, params or {})
            return True
        except Exception as e:
            logger.warning("[bridge] send_push 失败 device=%s cmd=%s: %s", email, cmd, e)
            return False

    def _try_recover(self, email: str) -> bool:
        """注册状态丢失时，从活跃 WS 会话按 email 找回并重新注册。

        返回是否恢复成功。会话里记录了 email（ws.py session_ready 时写入），
        且该会话的 WS 仍活跃（executor 未清理）时才能恢复。
        """
        try:
            from .session import get_manager
            from .ws import SessionExecutor

            session = get_manager().get_by_email(email)
            if not session or not session.websocket:
                return False
            # 用该会话重建一个 executor 的推送能力（send_push 只发不等回执）
            executor = SessionExecutor(session, email=email)
            self.register(email, executor._send_and_wait,
                          executor.send_skill_request, executor.send_push)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[bridge] send_push 自动恢复注册异常 device=%s: %s", email, e)
            return False

    async def send_cmd(self, email: str, cmd: str, params: dict | None = None) -> dict:
        """向指定设备发指令并等 result。设备未在线 → 返回错误。"""
        entry = self._devices.get(email)
        if not entry:
            return {"error": f"设备 {email} 执行通道未在线（请确认客户端已连接）"}
        try:
            res = await entry["send_cmd"](cmd, params or {})
            return res if isinstance(res, dict) else {}
        except Exception as e:
            logger.warning("[bridge] send_cmd 失败 device=%s cmd=%s: %s", email, cmd, e)
            return {"error": str(e)}

    async def send_skill_request(self, email: str, payload: dict) -> dict:
        """向设备下发 skill_request 请求蓝图，等手机回 skill_result（第 1 条）。

        设备未在线 / 客户端未实现 skill 通道 → 返回 ok=False 的明确错误。
        """
        entry = self._devices.get(email)
        if not entry:
            return {"ok": False,
                    "error": f"设备 {email} 执行通道未在线（请确认客户端已连接）"}
        fn = entry.get("send_skill_request")
        if not fn:
            return {"ok": False,
                    "error": f"设备 {email} 客户端未实现 skill 执行通道（请升级 App）"}
        try:
            res = await fn(payload or {})
            return res if isinstance(res, dict) else {}
        except Exception as e:
            logger.warning("[bridge] send_skill_request 失败 device=%s: %s", email, e)
            return {"ok": False, "error": str(e)}


# 全局单例
bridge = DeviceBridge()
