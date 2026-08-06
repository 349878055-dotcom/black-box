"""
主 Agent 入口（个人助理5 · skill 消费版）。

串行后台任务：submit → Agent.handle（LLM + skill 工具循环）→ 结果。
ask_user 通过 WS 通道（bridge.send_cmd 推送 + wait_user_input 等回复）与用户交互。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .agent import Agent
from ..channel.bridge import bridge

logger = logging.getLogger("xiami.master")


class TaskState:
    def __init__(self) -> None:
        self.status = "idle"      # idle/running/waiting_user/done/failed/cancelled
        self.summary = ""
        self.reply = ""
        self.ask: dict | None = None
        self.error = ""
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "reply": self.reply,
            "ask": self.ask,
            "error": self.error,
            "updated_at": self.updated_at,
        }


class MasterAgent:
    def __init__(self) -> None:
        self._busy: set[str] = set()
        self._jobs: dict[str, asyncio.Task] = {}
        self._tasks: dict[str, TaskState] = {}

    def get_task(self, device_id: str) -> dict[str, Any]:
        ts = self._tasks.get(device_id)
        return ts.to_dict() if ts else {"status": "idle", "summary": "", "reply": "", "ask": None}

    def is_busy(self, device_id: str) -> bool:
        return device_id in self._busy

    def cancel(self, device_id: str) -> None:
        ts = self._tasks.get(device_id)
        if ts:
            ts.status = "cancelled"
            ts.summary = "已取消"

    def submit(self, device_id: str, message: str) -> dict[str, Any]:
        if device_id in self._busy:
            return {"status": "busy", "task": self.get_task(device_id)}
        self._busy.add(device_id)
        ts = TaskState()
        ts.status = "running"
        ts.summary = f"正在处理：{(message or '')[:40]}"
        self._tasks[device_id] = ts
        job = asyncio.create_task(self._run(device_id, message))
        self._jobs[device_id] = job
        return {"status": "running", "task": ts.to_dict()}

    async def _run(self, device_id: str, message: str) -> None:
        ts = self._tasks.get(device_id)
        try:
            ask_fn = self._make_ask(device_id)
            agent = Agent(ask_user_fn=ask_fn, device_id=device_id)
            reply = await agent.handle(message)
            if ts:
                ts.status = "done"
                ts.reply = reply
                ts.summary = "已完成"
        except asyncio.CancelledError:
            if ts:
                ts.status = "cancelled"
                ts.summary = "已取消"
        except Exception as e:
            logger.exception("job 异常 device=%s", device_id)
            if ts:
                ts.status = "failed"
                ts.error = str(e)
                ts.summary = "处理失败"
        finally:
            self._busy.discard(device_id)

    def _make_ask(self, device_id: str):
        async def ask(question: str, image: str | None = None) -> str:
            ts = self._tasks.get(device_id)
            if ts:
                ts.status = "waiting_user"
                ts.ask = {"question": str(question)}
                ts.summary = "等待你回复…"
            # 推送到 App 聊天（image 为验证码图片 base64，App 显示给用户看）
            params: dict = {"question": str(question), "kind": "user_input"}
            if image:
                params["image"] = image
            try:
                await bridge.send_cmd(device_id, "ask_user", params)
            except Exception:
                pass
            ans = await bridge.wait_user_input(device_id, timeout=600)
            if ts:
                ts.status = "running"
                ts.ask = None
            return (ans or "").strip()

        return ask


# 全局单例
master = MasterAgent()
