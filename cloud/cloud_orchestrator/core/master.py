"""
主 Agent 入口（个人助理5 · skill 消费版）。

串行后台任务：submit → Agent.handle
  → 业务在 agent.py；调度循环由 LangGraph（graph_engine）执行。
会话按 (user_id, conversation_id) 隔离；ask_user 走 WS bridge。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from .agent import Agent
from ..channel.bridge import bridge

logger = logging.getLogger("xiami.master")

# ── ask_user 回答喂入注册表 ──
# device_id -> {ask_id: asyncio.Future}（同一设备可同时挂多个 ask，按 ask_id 精确路由；
# 不再单槽覆盖，避免先发的 ask 丢失；未带 ask_id 时仅当唯一等待才喂，兼容旧客户端）
# WS user_input 与 HTTP 回答都经 feed_answer 喂给等待中的任务，
# 让「回答」无论走哪条通道都能对上等待中的任务（问题①根治）。
_answer_waiter: dict[str, dict[str, asyncio.Future]] = {}


def feed_answer(device_id: str, ask_id: str, value: str) -> bool:
    """喂回答给等待中的 ask_user 任务。匹配成功返回 True（调用方不要再当新消息处理）。"""
    if not device_id:
        return False
    waiters = _answer_waiter.get(device_id)
    if not waiters:
        return False
    # 期待 ask_id 且调用方给了 ask_id → 按 ask_id 精确匹配
    if ask_id:
        fut = waiters.pop(ask_id, None)
        if fut is None or fut.done():
            return False
        fut.set_result(str(value or ""))
        if not waiters:
            _answer_waiter.pop(device_id, None)
        return True
    # 未带 ask_id：仅当该设备只有一个等待任务时才喂（避免答错对象）
    if len(waiters) == 1:
        aid, fut = next(iter(waiters.items()))
        if fut and not fut.done():
            waiters.pop(aid, None)
            if not waiters:
                _answer_waiter.pop(device_id, None)
            fut.set_result(str(value or ""))
            return True
    return False


class TaskState:
    def __init__(self) -> None:
        self.status = "idle"      # idle/running/waiting_user/done/failed/cancelled
        self.summary = ""
        self.reply = ""
        self.ask: dict | None = None
        self.error = ""
        self.updated_at = time.time()
        self.conversation_id = ""   # 任务所属会话（前端按此隔离 reply，防止旧回复串会话）
        self.steps: list[dict] = []  # 执行进度锚点（update_todo_list 轻量版）：[{step,title,status}]

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
        # 任务状态仍按 device_id（一台设备同时只跑一个任务）
        self._busy: set[str] = set()
        self._jobs: dict[str, asyncio.Task] = {}
        self._tasks: dict[str, TaskState] = {}

    def get_task(self, device_id: str) -> dict[str, Any]:
        ts = self._tasks.get(device_id)
        return ts.to_dict() if ts else {
            "status": "idle", "summary": "", "reply": "", "ask": None, "steps": [],
        }

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
        """从会话读上下文；drop_last 排除刚写入的当前用户消息，避免重复。"""
        try:
            from ..store.archive_center.consumer_archive.conversations import conversations

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

    def _conv_persona(self, user_id: str, conversation_id: str) -> dict:
        """读会话绑定的上台卡引用；无则 {}（闲聊模式）。"""
        try:
            from ..store.archive_center.consumer_archive.conversations import conversations

            conv = conversations.get(conversation_id)
            if not conv:
                conv = conversations.get_default(user_id)
            if not conv:
                return {}
            p = conv.persona if isinstance(conv.persona, dict) else {}
            return dict(p) if p else {}
        except Exception:
            return {}

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
        # 跨轮续办记忆（问题①根治）：新任务卡片从会话级恢复上一轮的执行进度，
        # 让虾米下一轮开局（run_react 注入【当前执行进度】）仍能看到查到哪一步。
        try:
            from ..store.archive_center.consumer_archive.conversations import conversations as conv_store
            prev_steps = conv_store.get_steps(conv_id)
            if prev_steps:
                ts.steps = list(prev_steps)
        except Exception:
            pass
        self._tasks[device_id] = ts
        job = asyncio.create_task(self._run(device_id, user_id, conv_id, message))
        self._jobs[device_id] = job
        return {"status": "running", "task": ts.to_dict()}

    async def _run(self, device_id: str, user_id: str, conversation_id: str, message: str) -> None:
        ts = self._tasks.get(device_id)
        try:
            ask_fn = self._make_ask(device_id, user_id, conversation_id)
            steps_fn = self._make_steps(device_id, conversation_id)
            form_fn = self._make_forms(conversation_id)
            agent = Agent(ask_user_fn=ask_fn, device_id=device_id,
                          steps_fn=steps_fn, form_fn=form_fn)
            # 上下文 = 该会话历史（不含当前消息），按会话隔离
            history = self._conv_history(user_id, conversation_id)
            # 会话 persona：客户手动「找 TA」写入；空 = 闲聊+博查，有 person_id = 人设+才艺
            persona = self._conv_persona(user_id, conversation_id)
            reply = await agent.handle(message, history=history, persona=persona)
            if reply:
                self._append_conv(user_id, conversation_id,
                                  {"who": "bot", "text": reply, "at": time.time()})
            if ts:
                ts.status = "done"
                ts.reply = reply
                ts.summary = "已完成"
                self._push_task(device_id)   # WS 推 task_update（done）
        except asyncio.CancelledError:
            if ts:
                ts.status = "cancelled"
                ts.summary = "已取消"
                self._push_task(device_id)   # WS 推 task_update（cancelled）
        except Exception as e:
            logger.exception("job 异常 device=%s", device_id)
            if ts:
                ts.status = "failed"
                ts.error = str(e)
                ts.summary = "处理失败"
                self._push_task(device_id)   # WS 推 task_update（failed）
        finally:
            self._busy.discard(device_id)

    def _make_ask(self, device_id: str, user_id: str, conversation_id: str):
        async def ask(question: str, image: str | None = None,
                      options: list[str] | None = None) -> str:
            ts = self._tasks.get(device_id)
            opts = [str(x) for x in (options or []) if str(x).strip()]
            # 生成提问编号 ask_id：回答带它，无论走 WS 还是 HTTP 都能喂回等待中的任务
            ask_id = uuid.uuid4().hex[:8]
            fut = asyncio.get_running_loop().create_future()
            _answer_waiter.setdefault(device_id, {})[ask_id] = fut
            if ts:
                ts.status = "waiting_user"
                ts.ask = {"question": str(question), "ask_id": ask_id, "options": opts}
                ts.summary = "等待你回复…"
                self._push_task(device_id)   # WS 推 task_update（waiting_user）
            # ask 提问记录到会话（bot 视角）
            self._append_conv(user_id, conversation_id,
                              {"who": "bot", "text": f"（向你提问）{question}", "at": time.time()})
            # 推送到 App 聊天（image 为验证码图片 base64，App 显示给用户看）
            params: dict = {"question": str(question), "kind": "user_input",
                            "ask_id": ask_id, "options": opts}
            if image:
                params["image"] = image
                logger.info("[ask_user] 推送验证码图片 image长度=%d 前24=%s",
                            len(str(image)), str(image)[:24])
            else:
                logger.info("[ask_user] 无图片参数（image=None）")
            try:
                await bridge.send_cmd(device_id, "ask_user", params)
            except Exception as e:
                # 铁律（2026-08-16）：推送 ask_user 失败不静默，记录日志暴露 WS 链路问题
                logger.exception("ask_user 推送失败 device=%s ask_id=%s: %s", device_id, ask_id, e)
                raise
            # 等回答：feed_answer（WS user_input / HTTP 回答）喂进来；600s 超时
            ans: str | None = None
            try:
                ans = await asyncio.wait_for(fut, timeout=600)
            except asyncio.TimeoutError:
                ans = None
            finally:
                waiters = _answer_waiter.get(device_id)
                if waiters:
                    waiters.pop(ask_id, None)
                    if not waiters:
                        _answer_waiter.pop(device_id, None)
            # ask 结束（成功/超时/取消）→ 通知客户端退出「等回答」态，
            # 避免 S.waitingAsk 残留导致客户之后的消息被误当「回答」送走而丢失
            try:
                await bridge.send_push(device_id, "ask_done", {"ask_id": ask_id})
            except Exception:
                pass
            if ans:
                # 用户回答记录到会话（user 视角）
                self._append_conv(user_id, conversation_id,
                                  {"who": "user", "text": str(ans).strip(), "at": time.time()})
            if ts:
                ts.status = "running"
                ts.ask = None
                self._push_task(device_id)   # WS 推 task_update（回到 running）
            return (ans or "").strip()

        return ask

    def _make_steps(self, device_id: str, conversation_id: str = ""):
        """提供执行进度（steps）的读写回调，给 Agent 的 update_todo_list 轻量版用。

        跨轮续办记忆（问题①）：进度以「会话级」为准——set 同时写 TaskState（推 App 展示）
        与会话（落库，供同会话下一轮恢复）；get 优先读会话（权威），会话为空再兜底任务卡片。
        """
        def _conv_store():
            from ..store.archive_center.consumer_archive.conversations import conversations as conv_store
            return conv_store

        def get_steps() -> list[dict]:
            # 优先读会话级（跨轮续办记忆的权威来源）
            try:
                steps = _conv_store().get_steps(conversation_id)
                if steps:
                    return list(steps)
            except Exception:
                pass
            ts = self._tasks.get(device_id)
            return list((ts.steps or [])) if ts else []

        def set_steps(steps: list[dict]) -> bool:
            """覆盖写执行进度；返回会话是否落库成功（供 agent 如实告知，问题③）。"""
            ts = self._tasks.get(device_id)
            # 状态值白名单（问题②）：展示端只认 pending/doing/done，
            # 不在白名单的（含大小写变体/中文如"进行中"）一律归一化为 pending。
            _STATUS_ALLOW = {"pending", "doing", "done"}
            clean = []
            for s in (steps or []):
                if not isinstance(s, dict):
                    continue
                raw_status = str(s.get("status") or "pending").strip().lower()
                status = raw_status if raw_status in _STATUS_ALLOW else "pending"
                item = {
                    # 问题⑥：序号后端统一按列表顺序从 1 递增（忽略传入的 step），
                    # 覆盖式写入时序号永远稳定连续，不因传 0/漏传/乱序而跳号。
                    # 配合问题④回读真实值，虾米拿到的序号即实际生效的序号。
                    "step": len(clean) + 1,
                    "title": str(s.get("title") or "")[:80],
                    "status": status,
                }
                if item["title"]:
                    clean.append(item)
            # 问题⑦（全量覆盖防倒退）：update_step 是覆盖式写入，虾米可能漏带已完成的步骤。
            # 合并保护——旧清单里已 done、本次又没带上的步骤，追加保留（进度不能倒退消失）；
            # 未完成项（doing/pending）没带上则丢弃（允许虾米重新规划）。
            try:
                prev = _conv_store().get_steps(conversation_id)
            except Exception:
                prev = []
            if prev:
                prev_titles = {str(s.get("title") or "") for s in clean}
                for s in prev:
                    if (s.get("status") == "done"
                            and str(s.get("title") or "") not in prev_titles):
                        clean.append({
                            "step": len(clean) + 1,
                            "title": str(s.get("title") or "")[:80],
                            "status": "done",
                        })
            if ts:
                ts.steps = clean
            # 落库到会话（跨轮续办记忆）；返回真实落库结果，失败不静默、记日志
            saved = False
            try:
                saved = bool(_conv_store().set_steps(conversation_id, clean))
            except Exception:
                logger.exception("会话进度落库失败 conv=%s device=%s", conversation_id, device_id)
                saved = False
            if ts:
                self._push_task(device_id)   # WS 推 task_update（带 steps 给 App 展示进度）
            return saved

        return {"get": get_steps, "set": set_steps}

    def _make_forms(self, conversation_id: str = ""):
        """会话级 form 字段表状态（填一个存一个）。"""
        def _store():
            from ..store.archive_center.consumer_archive.conversations import conversations as conv_store
            return conv_store

        def get_forms() -> dict:
            try:
                return dict(_store().get_forms(conversation_id) or {})
            except Exception:
                return {}

        def set_forms(forms: dict) -> bool:
            try:
                return bool(_store().set_forms(conversation_id, forms or {}))
            except Exception:
                logger.exception("会话表单落库失败 conv=%s", conversation_id)
                return False

        return {"get": get_forms, "set": set_forms}

    def _push_task(self, device_id: str) -> None:
        """任务状态变化 → 通过 WS 主动推 task_update 给 App（只发不等，不阻塞）。

        铁律（2026-08-16）：推送失败绝不静默吞掉——直接记日志暴露，
        否则 WS 链路断了也看不出来问题在哪。
        """
        ts = self._tasks.get(device_id)
        if not ts:
            return
        from ..channel.bridge import bridge as _bridge

        async def _push_safe():
            # 后台推送任务要回收异常，避免 "Task exception was never retrieved"
            try:
                await _bridge.send_push(device_id, "task_update", ts.to_dict())
            except Exception as e:  # noqa: BLE001
                logger.warning("task_update 推送失败 device=%s: %s", device_id, e)

        asyncio.create_task(_push_safe())


# 全局单例
master = MasterAgent()
