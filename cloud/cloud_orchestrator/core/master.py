"""
主 Agent 入口 — LangGraph 原生：interrupt/resume + checkpointer。

submit → Agent.handle → run_agent_graph
feed_answer → feed_graph_resume（唯一等人通道）
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .agent import Agent
from .graph_native import feed_graph_resume
from ..channel.bridge import bridge

logger = logging.getLogger("xiami.master")


def feed_answer(email: str, ask_id: str, value: str,
                conversation_id: str = "") -> bool:
    """用户回答 → 对上当前 ask_id 才 resume。空 ask_id = 当前正在等人时的改口。"""
    if not email:
        return False
    return feed_graph_resume(email, str(value or ""), ask_id=str(ask_id or ""))


class TaskState:
    """App 任务卡片视图（镜像 LangGraph 执行态，非第二套状态机）。"""

    def __init__(self) -> None:
        self.status = "idle"
        self.summary = ""
        self.reply = ""
        self.ask: dict | None = None
        self.error = ""
        self.updated_at = time.time()
        self.conversation_id = ""
        self.steps: list[dict] = []
        self.finished_by_timeout = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "reply": self.reply,
            "ask": self.ask,
            "error": self.error,
            "updated_at": self.updated_at,
            "conversation_id": self.conversation_id,
            "steps": self.steps or [],
        }


class MasterAgent:
    def __init__(self) -> None:
        self._busy: set[str] = set()
        self._jobs: dict[str, asyncio.Task] = {}
        self._tasks: dict[str, TaskState] = {}

    def get_task(self, email: str) -> dict[str, Any]:
        ts = self._tasks.get(email)
        return ts.to_dict() if ts else {
            "status": "idle", "summary": "", "reply": "", "ask": None, "steps": [],
        }

    def is_busy(self, email: str) -> bool:
        return email in self._busy

    def cancel(self, email: str) -> None:
        ts = self._tasks.get(email)
        if ts:
            ts.status = "cancelled"
            ts.summary = "已取消"
        job = self._jobs.get(email)
        if job and not job.done():
            try:
                job.cancel()
            except Exception:
                pass

    def _resolve_conv(self, user_id: str, conversation_id: str) -> str:
        try:
            from ..store.archive_center.consumer_archive.conversations import conversations
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
            from ..store.archive_center.consumer_archive.conversations import conversations
            conversations.append_message(conversation_id, msg)
        except Exception:
            pass

    def _conv_history(self, user_id: str, conversation_id: str, limit: int = 8,
                      drop_last: int = 1) -> list[dict]:
        """仅用于首条 thread 冷启动；有 checkpoint 后以 LangGraph messages 为准。"""
        try:
            from ..store.archive_center.consumer_archive.conversations import conversations
            conv = conversations.get(conversation_id) or conversations.get_default(user_id)
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

    def _conv_persona(self, user_id: str, conversation_id: str) -> dict:
        try:
            from ..store.archive_center.consumer_archive.conversations import conversations
            conv = conversations.get(conversation_id) or conversations.get_default(user_id)
            if not conv:
                return {}
            p = conv.persona if isinstance(conv.persona, dict) else {}
            return dict(p) if p else {}
        except Exception:
            return {}

    def submit(self, email: str, message: str,
               user_id: str = "", conversation_id: str = "default") -> dict[str, Any]:
        raw_conv_id = conversation_id or "default"
        conv_id = self._resolve_conv(user_id, conversation_id)
        self._append_conv(user_id, conv_id, {"who": "user", "text": message, "at": time.time()})

        if email in self._busy:
            return {"status": "busy", "task": self.get_task(email)}
        self._busy.add(email)
        ts = TaskState()
        ts.status = "running"
        ts.summary = f"正在处理：{(message or '')[:40]}"
        ts.conversation_id = raw_conv_id
        self._tasks[email] = ts
        job = asyncio.create_task(self._run(email, user_id, conv_id, message))
        self._jobs[email] = job
        return {"status": "running", "task": ts.to_dict()}

    async def _run(self, email: str, user_id: str, conversation_id: str, message: str) -> None:
        ts = self._tasks.get(email)
        try:
            agent = Agent(email=email, conversation_id=conversation_id)
            history = self._conv_history(user_id, conversation_id)
            persona = self._conv_persona(user_id, conversation_id)
            hooks = self._make_graph_hooks(email, user_id, conversation_id)

            reply = await agent.handle(
                message, history=history, persona=persona, graph_hooks=hooks,
            )
            if reply:
                self._append_conv(user_id, conversation_id,
                                  {"who": "bot", "text": reply, "at": time.time()})
            if ts:
                ts.status = "done"
                ts.reply = reply
                ts.summary = "已完成"
                ts.ask = None
                self._push_task(email)
        except asyncio.CancelledError:
            if ts and ts.finished_by_timeout:
                return
            if ts:
                ts.status = "cancelled"
                ts.summary = "已取消"
                self._push_task(email)
        except Exception as e:
            if ts and ts.finished_by_timeout:
                return
            logger.exception("job 异常 device=%s", email)
            if ts:
                ts.status = "failed"
                ts.error = str(e)
                ts.summary = "处理失败"
                self._push_task(email)
        finally:
            self._busy.discard(email)

    def _make_graph_hooks(self, email: str, user_id: str, conversation_id: str) -> dict:
        """LangGraph interrupt 与 App/WS 桥接（唯一 ask/resume 通道）。"""
        ts = self._tasks.get(email)

        async def push_ask(question: str, ask_id: str, options: list, image: str | None):
            opts = [str(x) for x in (options or []) if str(x).strip()]
            if ts:
                ts.status = "waiting_user"
                ts.ask = {"question": str(question), "ask_id": ask_id, "options": opts}
                ts.summary = "等待你回复…"
                self._push_task(email)
            self._append_conv(user_id, conversation_id,
                              {"who": "bot", "text": f"（向你提问）{question}", "at": time.time()})
            params: dict = {"question": str(question), "kind": "user_input",
                            "ask_id": ask_id, "options": opts}
            if image:
                params["image"] = image
            await bridge.send_cmd(email, "ask_user", params)

        async def on_waiting(intr: dict):
            if ts and not ts.ask:
                ts.status = "waiting_user"
                ts.ask = {
                    "question": str(intr.get("question") or ""),
                    "ask_id": str(intr.get("ask_id") or ""),
                    "options": intr.get("options") or [],
                }
                self._push_task(email)

        async def on_running():
            if ts:
                ts.status = "running"
                ts.ask = None
                self._push_task(email)

        async def on_timeout():
            if ts:
                ts.status = "done"
                ts.summary = "等待超时，已自动结束"
                ts.reply = "等您回复等太久了，这次就先到这儿。需要继续办理时，再发消息说一声就行。"
                ts.ask = None
                ts.finished_by_timeout = True
                self._push_task(email)
            raise asyncio.CancelledError("ask_user 等待超时")

        async def on_answer(text: str):
            self._append_conv(user_id, conversation_id,
                              {"who": "user", "text": str(text).strip(), "at": time.time()})
            try:
                await bridge.send_push(email, "ask_done", {})
            except Exception:
                pass

        async def on_steps(steps: list):
            if ts:
                ts.steps = list(steps)
                self._push_task(email)

        return {
            "push_ask": push_ask,
            "on_waiting": on_waiting,
            "on_running": on_running,
            "on_timeout": on_timeout,
            "on_answer": on_answer,
            "on_steps": on_steps,
        }

    def _push_task(self, email: str) -> None:
        ts = self._tasks.get(email)
        if not ts:
            return
        from ..channel.bridge import bridge as _bridge

        async def _push_safe():
            try:
                ok = await _bridge.send_push(email, "task_update", ts.to_dict())
                if not ok:
                    logger.warning("task_update 未送达 device=%s", email)
            except Exception as e:
                logger.warning("task_update 推送失败 device=%s: %s", email, e)

        asyncio.create_task(_push_safe())


master = MasterAgent()
