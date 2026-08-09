"""
主 Agent 入口（个人助理5 · skill 消费版）。

串行后台任务：submit → Agent.handle（LLM + skill 工具循环）→ 结果。
会话（豆包式单用户多会话）：上下文按 (user_id, conversation_id) 隔离，
消息写入 conversations 存储，多轮记忆 = 该会话历史（不跨会话串扰）。
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
        self.conversation_id = ""   # 任务所属会话（前端按此隔离 reply，防止旧回复串会话）

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "reply": self.reply,
            "ask": self.ask,
            "error": self.error,
            "updated_at": self.updated_at,
            "conversation_id": self.conversation_id,
        }


class MasterAgent:
    def __init__(self) -> None:
        # 任务状态仍按 device_id（一台设备同时只跑一个任务）
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
        # 真正取消正在跑的 asyncio task（如卡在 ask_user 等用户输入时），
        # 让 _run 的 finally 释放 _busy，否则后续提交全部 busy（cancel 只改状态不释放）
        job = self._jobs.get(device_id)
        if job and not job.done():
            try:
                job.cancel()
            except Exception:
                pass

    # ── 会话工具（豆包式：会话历史即上下文，按会话隔离）──
    def _resolve_conv(self, user_id: str, conversation_id: str) -> str:
        """解析有效会话 ID（无效回退 default）。"""
        try:
            from ..store.conversations import conversations

            conv_id = conversation_id or "default"
            conv = (conversations.get_default(user_id)
                    if conv_id == "default" else conversations.get(conv_id))
            if not conv:
                conv = conversations.get_default(user_id)
            return conv.conversation_id if conv else (conv_id or "default")
        except Exception:
            return conversation_id or "default"

    def _append_conv(self, user_id: str, conversation_id: str, msg: dict) -> None:
        try:
            from ..store.conversations import conversations

            conversations.append_message(conversation_id, msg)
        except Exception:
            pass

    def _conv_history(self, user_id: str, conversation_id: str, limit: int = 8,
                      drop_last: int = 1) -> list[dict]:
        """从会话读上下文；drop_last 排除刚写入的当前用户消息，避免重复。"""
        try:
            from ..store.conversations import conversations

            conv = conversations.get(conversation_id)
            if not conv:
                conv = conversations.get_default(user_id)
            if not conv:
                return []
            msgs = conv.messages
            if drop_last and msgs:
                msgs = msgs[:-drop_last]
            hist = []
            for m in msgs:
                if not m.get("text"):
                    continue
                role = "assistant" if m.get("who") == "bot" else "user"
                hist.append({"role": role, "content": str(m.get("text"))})
            return hist[-limit:]
        except Exception:
            return []

    # ── 任务 ──
    def submit(self, device_id: str, message: str,
               user_id: str = "", conversation_id: str = "default") -> dict[str, Any]:
        raw_conv_id = conversation_id or "default"   # 前端传入的会话 id（如 'default' / uuid）
        conv_id = self._resolve_conv(user_id, conversation_id)
        # 用户消息写入会话（更新会话时间/标题）
        self._append_conv(user_id, conv_id, {"who": "user", "text": message, "at": time.time()})

        if device_id in self._busy:
            return {"status": "busy", "task": self.get_task(device_id)}
        self._busy.add(device_id)
        ts = TaskState()
        ts.status = "running"
        ts.summary = f"正在处理：{(message or '')[:40]}"
        ts.conversation_id = raw_conv_id   # 记录所属会话，前端按此隔离 reply
        self._tasks[device_id] = ts
        job = asyncio.create_task(self._run(device_id, user_id, conv_id, message))
        self._jobs[device_id] = job
        return {"status": "running", "task": ts.to_dict()}

    async def _run(self, device_id: str, user_id: str, conversation_id: str, message: str) -> None:
        ts = self._tasks.get(device_id)
        try:
            ask_fn = self._make_ask(device_id, user_id, conversation_id)
            agent = Agent(ask_user_fn=ask_fn, device_id=device_id)
            # 上下文 = 该会话历史（不含当前消息），按会话隔离
            history = self._conv_history(user_id, conversation_id)
            reply = await agent.handle(message, history=history)
            if reply:
                self._append_conv(user_id, conversation_id,
                                  {"who": "bot", "text": reply, "at": time.time()})
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

    def _make_ask(self, device_id: str, user_id: str, conversation_id: str):
        async def ask(question: str, image: str | None = None) -> str:
            ts = self._tasks.get(device_id)
            if ts:
                ts.status = "waiting_user"
                ts.ask = {"question": str(question)}
                ts.summary = "等待你回复…"
            # ask 提问记录到会话（bot 视角）
            self._append_conv(user_id, conversation_id,
                              {"who": "bot", "text": f"（向你提问）{question}", "at": time.time()})
            # 推送到 App 聊天（image 为验证码图片 base64，App 显示给用户看）
            params: dict = {"question": str(question), "kind": "user_input"}
            if image:
                params["image"] = image
                logger.info("[ask_user] 推送验证码图片 image长度=%d 前24=%s",
                            len(str(image)), str(image)[:24])
            else:
                logger.info("[ask_user] 无图片参数（image=None）")
            try:
                await bridge.send_cmd(device_id, "ask_user", params)
            except Exception:
                pass
            ans = await bridge.wait_user_input(device_id, timeout=600)
            if ans:
                # 用户回答记录到会话（user 视角）
                self._append_conv(user_id, conversation_id,
                                  {"who": "user", "text": str(ans).strip(), "at": time.time()})
            if ts:
                ts.status = "running"
                ts.ask = None
            return (ans or "").strip()

        return ask


# 全局单例
master = MasterAgent()
