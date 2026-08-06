"""
DeviceBridge — 按 device_id 路由「执行通道」。

云端 MasterAgent 要与某台设备的客户端交互时（ask_user 推送问题 / 等用户输入 /
浏览器人工配合：登录/验证码），通过 bridge 找到该设备当前活跃的 WS 执行器
（手机 App），发 send_cmd 指令并等待 result。

每台设备的 WS 连接建立后注册：
  register(device_id, send_cmd, wait_user_input)
断线后 unregister。

单例：from .bridge import bridge
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("xiami.device_bridge")

SendCmd = Callable[[str, dict], Awaitable[dict]]
WaitUser = Callable[[float], Awaitable[str | None]]


class DeviceBridge:
    def __init__(self) -> None:
        self._devices: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def register(self, device_id: str, send_cmd: SendCmd, wait_user_input: WaitUser) -> None:
        """设备执行通道上线（WS 连接成功时）。"""
        if not device_id:
            return
        self._devices[device_id] = {
            "send_cmd": send_cmd,
            "wait_user_input": wait_user_input,
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

    async def wait_user_input(self, device_id: str, timeout: float = 600) -> str | None:
        """等待设备用户输入（登录/验证码等）。设备未在线 → 返回 None。"""
        entry = self._devices.get(device_id)
        if not entry:
            return None
        try:
            return await entry["wait_user_input"](timeout)
        except Exception as e:
            logger.warning("[bridge] wait_user_input 异常 device=%s: %s", device_id, e)
            return None


# 全局单例
bridge = DeviceBridge()
