"""
DeviceBridge — 按 device_id 路由「执行通道」。

云端 MasterAgent 要与某台设备的客户端交互时（ask_user 推送问题 / 等用户输入 /
浏览器人工配合：登录/验证码），通过 bridge 找到该设备当前活跃的 WS 执行器
（手机 App），发 send_cmd 指令并等待 result。

Device-as-Proxy（第 1 条）：bridge 同时承载「skill 执行通道」——
云端下发 skill_request 请求蓝图 → 手机直连平台 → 回传 skill_result，
云端不再直发平台请求。

每台设备的 WS 连接建立后注册：
  register(device_id, send_cmd, send_skill_request, send_push)
断线后 unregister。
（ask_user 交互统一走 master._answer_waiter + feed_answer，不占 bridge 的 wait_user_input 槽）

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

    def register(self, device_id: str, send_cmd: SendCmd,
                 send_skill_request: SendSkillRequest | None = None,
                 send_push: SendPush | None = None) -> None:
        """设备执行通道上线（WS 连接成功时）。"""
        if not device_id:
            return
        self._devices[device_id] = {
            "send_cmd": send_cmd,
            "send_skill_request": send_skill_request,
            "send_push": send_push,
        }
        logger.info("[bridge] 设备执行通道上线 device=%s 在线=%d", device_id, len(self._devices))

    def unregister(self, device_id: str) -> None:
        if device_id in self._devices:
            del self._devices[device_id]
            logger.info("[bridge] 设备执行通道下线 device=%s 在线=%d", device_id, len(self._devices))

    def has(self, device_id: str) -> bool:
        return device_id in self._devices

    def online_devices(self) -> list[str]:
        return list(self._devices.keys())

    async def send_push(self, device_id: str, cmd: str, params: dict | None = None) -> None:
        """向设备推送一条指令（只发不等回执），用于 task_update 等实时通知，不阻塞。"""
        entry = self._devices.get(device_id)
        if not entry:
            return
        fn = entry.get("send_push")
        if not fn:
            return
        try:
            await fn(cmd, params or {})
        except Exception as e:
            logger.warning("[bridge] send_push 失败 device=%s cmd=%s: %s", device_id, cmd, e)

    async def send_cmd(self, device_id: str, cmd: str, params: dict | None = None) -> dict:
        """向指定设备发指令并等 result。设备未在线 → 返回错误。"""
        entry = self._devices.get(device_id)
        if not entry:
            return {"error": f"设备 {device_id} 执行通道未在线（请确认客户端已连接）"}
        try:
            res = await entry["send_cmd"](cmd, params or {})
            return res if isinstance(res, dict) else {}
        except Exception as e:
            logger.warning("[bridge] send_cmd 失败 device=%s cmd=%s: %s", device_id, cmd, e)
            return {"error": str(e)}

    async def send_skill_request(self, device_id: str, payload: dict) -> dict:
        """向设备下发 skill_request 请求蓝图，等手机回 skill_result（第 1 条）。

        设备未在线 / 客户端未实现 skill 通道 → 返回 ok=False 的明确错误。
        """
        entry = self._devices.get(device_id)
        if not entry:
            return {"ok": False,
                    "error": f"设备 {device_id} 执行通道未在线（请确认客户端已连接）"}
        fn = entry.get("send_skill_request")
        if not fn:
            return {"ok": False,
                    "error": f"设备 {device_id} 客户端未实现 skill 执行通道（请升级 App）"}
        try:
            res = await fn(payload or {})
            return res if isinstance(res, dict) else {}
        except Exception as e:
            logger.warning("[bridge] send_skill_request 失败 device=%s: %s", device_id, e)
            return {"ok": False, "error": str(e)}


# 全局单例
bridge = DeviceBridge()
