"""LangGraph 原生调度：StateGraph + interrupt + Command(resume) + Checkpointer。"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ..store.persist import DATA_DIR
from .graph_state import AgentState
from .dialogue.resolve_reply import resolve_reply
from .dialogue.route_entry import route_entry
from .dialogue.skill_lock import detect_lock, reinforce_lock
from .dialogue.answer_check import load_schema_for_skill
from .dialogue.slots import extract_slots, filled_hint, is_payment_return, missing_entry

logger = logging.getLogger("xiami.graph_engine")

_CHECKPOINTER = None
_COMPILED = None

MAX_ASK_ATTEMPTS = 3
MAX_CORRECTIONS = 2


def _make_checkpointer():
    """LangGraph checkpointer（thread_id = conversation_id）。

    当前用 InMemorySaver：async 兼容、能跑通 interrupt/resume 验收。
    注意：SqliteSaver（同步版）不支持 ainvoke（实测报
    "SqliteSaver does not support async methods"）；AsyncSqliteSaver 需要
    aiosqlite 连接且必须在事件循环内初始化（from_conn_string 是 async context
    manager，不适合全局单例）。落盘版列为后续改进，不影响本次功能验证。
    """
    global _CHECKPOINTER
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER
    from langgraph.checkpoint.memory import InMemorySaver
    _CHECKPOINTER = InMemorySaver()
    logger.info("Checkpointer: InMemorySaver（落盘版 Sqlite 后续再接）")
    return _CHECKPOINTER


def _sync_runtime_state(runtime, state: dict) -> None:
    runtime._graph_forms = dict(state.get("forms") or {})
    runtime._graph_steps = list(state.get("steps") or [])
    runtime._graph_forms_dirty = False
    runtime._graph_steps_dirty = False


def _collect_runtime_state_updates(runtime) -> dict:
    updates: dict = {}
    if getattr(runtime, "_graph_forms_dirty", False):
        updates["forms"] = dict(getattr(runtime, "_graph_forms", {}) or {})
        runtime._graph_forms_dirty = False
    if getattr(runtime, "_graph_steps_dirty", False):
        updates["steps"] = list(getattr(runtime, "_graph_steps", []) or [])
        runtime._graph_steps_dirty = False
    return updates


def _chat_model():
    from langchain_openai import ChatOpenAI
    from ..config import get

    api_key = get("llm_api_key") or ""
    base_url = (get("llm_base_url") or "https://api.deepseek.com/v1").rstrip("/")
    model = get("llm_model") or "deepseek-chat"
    if not api_key:
        raise RuntimeError("LLM API Key 未配置")
    return ChatOpenAI(
        api_key=api_key, base_url=base_url, model=model,
        temperature=0.2, max_tokens=4096, parallel_tool_calls=False,
    )


def _clip_text(text: str, limit: int = 20000) -> str:
    if not text or len(text) <= limit:
        return text
    head = text[:limit]
    idx = max(head.rfind("。"), head.rfind("！"), head.rfind("？"), head.rfind("\n"))
    if idx > limit * 0.5:
        head = head[: idx + 1]
    return head + "…（已截断）"


def _extract_ai_text(msg) -> str:
    if not isinstance(msg, AIMessage):
        return ""
    content = msg.content
    if isinstance(content, str):
        return content.strip()
    parts = []
    for p in content or []:
        if isinstance(p, dict) and p.get("type") == "text":
            parts.append(str(p.get("text") or ""))
        elif isinstance(p, str):
            parts.append(p)
    return "".join(parts).strip()


def _apply_slot(state: dict, skill: str, field: str, value: str, person_id: str) -> dict:
    return _apply_slots(state, skill, {field: value}, person_id)


def _apply_slots(state: dict, skill: str, kv: dict, person_id: str) -> dict:
    forms = dict(state.get("forms") or {})
    if not skill or not kv:
        return forms
    schema = load_schema_for_skill(skill, person_id)
    allowed = {it["field"] for it in schema if it.get("source") == "customer"}
    blob = dict(forms.get(skill) or {})
    for field, value in (kv or {}).items():
        if not field or value in (None, ""):
            continue
        if allowed and field not in allowed:
            continue
        blob[str(field)] = str(value).strip()
    forms[skill] = blob
    return forms


def _slot_feed(state: dict, skill: str, person_id: str, forms: dict) -> str:
    schema = load_schema_for_skill(skill, person_id) if skill else []
    values = (forms or {}).get(skill) or {}
    return filled_hint(schema, values) or "【已记下客户信息】"


def _process_reply(raw: str, pending: dict, state: dict) -> tuple[str, dict]:
    """resolve_reply → 更新 state 片段 + 喂给 ToolMessage 的文本。"""
    from .dialogue.commands import CommandKind

    person_id = str(state.get("person_id") or "")
    cmd = resolve_reply(
        raw, pending, person_id=person_id,
        locked_skill=state.get("locked_skill"),
        allowed_skills=list(state.get("allowed_skills") or []),
    )
    label = str(pending.get("label") or pending.get("field") or "")
    updates: dict = {}

    if cmd.kind == CommandKind.ABANDON:
        updates["phase"] = "done"
        updates["pending_ask"] = None
        return "【用户放弃】客户表示不办了，请 done 收尾。不要再追问字段。", updates

    if cmd.kind == CommandKind.NEW_INTENT:
        updates["pending_ask"] = None
        updates["phase"] = "task"
        updates["locked_skill"] = ""
        updates["lock_reason"] = ""
        updates["lock_entity"] = {}
        updates["user_text"] = str(cmd.value or raw)
        updates["_reopen"] = True
        return str(cmd.value or raw), updates

    if cmd.kind == CommandKind.PAYMENT_RETURN:
        updates["pending_ask"] = None
        updates["phase"] = "task"
        return "【客户表示已经付好了】请查订单/支付结果，不要重新收集信息。", updates

    if cmd.kind == CommandKind.OFF_TOPIC_CHAT:
        from .date_utils import clock_note
        side = clock_note(raw) or "好的。"
        return f"{side}\n【继续办事】请提供{label}。", updates

    if cmd.kind == CommandKind.REASK:
        attempt = int(pending.get("attempt") or 0) + 1
        if attempt >= int(pending.get("max_attempts") or MAX_ASK_ATTEMPTS):
            updates["phase"] = "done"
            updates["pending_ask"] = None
            return "【多次无效回答】请 done 收尾。", updates
        pending = dict(pending)
        pending["attempt"] = attempt
        updates["pending_ask"] = pending
        reason = cmd.reason or "回答无效"
        return f"【无效回答：{reason}】请重新提供{label}。", updates

    if cmd.kind == CommandKind.SET_SLOT:
        skill = str(pending.get("skill") or state.get("locked_skill") or cmd.skill or "")
        kv = dict(cmd.extra or {})
        field = str(cmd.slot_field or pending.get("field") or "")
        val = cmd.value or raw
        if field and val:
            kv[field] = val
        if skill and kv:
            updates["forms"] = _apply_slots(state, skill, kv, person_id)
        updates["pending_ask"] = None
        updates["phase"] = "task"
        feed = _slot_feed(state, skill, person_id, updates.get("forms") or state.get("forms") or {})
        if cmd.reason == "客户改口字段" and field:
            still = str(pending.get("label") or pending.get("field") or "")
            if still:
                feed += f"\n【原问题还没答】请继续用 ask_user 问{still}。"
        return feed, updates

    return raw, updates


from .graph_tools import build_tools, _dump


def _infer_pending_field(pending: dict, schema: list[dict], question: str) -> dict:
    """从问句对上契约字段。"""
    pending = dict(pending)
    for it in schema:
        if it.get("source") != "customer":
            continue
        lbl = str(it.get("label") or "")
        if lbl and lbl in question:
            pending["field"] = it["field"]
            pending["label"] = lbl
            pending["type"] = str(it.get("type") or "text")
            return pending
    miss = missing_entry(schema, {})
    if not pending.get("field") and len([it for it in schema if it.get("source") == "customer"]) == 1:
        it = next(it for it in schema if it.get("source") == "customer")
        pending["field"] = it["field"]
        pending["label"] = str(it.get("label") or it["field"])
        pending["type"] = str(it.get("type") or "text")
    elif not pending.get("field") and miss:
        it = miss[0]
        pending["field"] = it["field"]
        pending["label"] = str(it.get("label") or it["field"])
        pending["type"] = str(it.get("type") or "text")
    return pending


def _slot_already_filled(state: dict, skill: str, field: str) -> str:
    if not skill or not field:
        return ""
    val = ((state.get("forms") or {}).get(skill) or {}).get(field)
    if val in (None, "", [], {}):
        return ""
    return str(val)


def _node_route(state: AgentState, config) -> dict:
    """入口：chat/task 路由 + SkillLock + 整句拆槽。"""
    runtime = config["configurable"]["runtime"]
    _sync_runtime_state(runtime, state)
    text = str(state.get("user_text") or "")
    hired = bool(state.get("hired"))
    allowed = list(state.get("allowed_skills") or [])
    person_id = str(state.get("person_id") or "")

    phase = route_entry(text, state, hired=hired, allowed_skills=allowed)
    updates: dict = {"phase": phase}

    lock = detect_lock(text, allowed) if phase != "chat" else None
    if lock:
        skill, reason, entity = lock
        updates["locked_skill"] = skill
        updates["lock_reason"] = reason
        updates["lock_entity"] = entity
        updates["phase"] = "task"

    if reinforce_lock(text, state.get("locked_skill") or updates.get("locked_skill")):
        updates["lock_reason"] = str(state.get("lock_reason") or "") + "+reinforced"

    skill = str(updates.get("locked_skill") or state.get("locked_skill") or "")
    if updates.get("locked_skill"):
        runtime.current_skill = updates["locked_skill"]

    extracted_any = extract_slots(text, None) if text else {}
    if hired and not skill and (extracted_any.get("departure") or extracted_any.get("arrival")):
        if not allowed or "tuniu" in allowed:
            skill = "tuniu"
            updates["locked_skill"] = skill
            updates["lock_reason"] = "said_cities"
            updates["phase"] = "task"
            runtime.current_skill = skill

    if hired and is_payment_return(text):
        updates["phase"] = "task"
        updates["messages"] = [HumanMessage(content="【客户表示已经付好了】请查订单/支付结果，不要重新收集信息。")]
        return updates

    if skill and text:
        schema = load_schema_for_skill(skill, person_id)
        extracted = extract_slots(text, schema)
        if extracted:
            merged_state = {**state, "forms": dict(state.get("forms") or {})}
            updates["forms"] = _apply_slots(merged_state, skill, extracted, person_id)
            runtime._graph_forms = dict(updates["forms"])
            hint = filled_hint(schema, (updates["forms"] or {}).get(skill) or {})
            if hint:
                updates["messages"] = [HumanMessage(content=hint)]
            updates["phase"] = "task"

    return updates


def _node_model(state: AgentState, config) -> dict:
    runtime = config["configurable"]["runtime"]
    _sync_runtime_state(runtime, state)
    hired = bool(state.get("hired"))
    phase = str(state.get("phase") or "task")
    runtime.dialogue_phase = phase
    if state.get("locked_skill"):
        runtime.current_skill = str(state["locked_skill"])

    tools = build_tools(runtime, hired=hired)
    model = _chat_model().bind_tools(tools)
    system = config["configurable"].get("system") or ""
    msgs = list(state.get("messages") or [])
    if system and (not msgs or not isinstance(msgs[0], SystemMessage)):
        msgs = [SystemMessage(content=system)] + msgs
    skill = str(state.get("locked_skill") or "")
    blob = (state.get("forms") or {}).get(skill) or {}
    if skill and blob:
        schema = load_schema_for_skill(skill, str(state.get("person_id") or ""))
        hint = filled_hint(schema, blob)
        if hint and (not msgs or getattr(msgs[-1], "content", None) != hint):
            msgs = msgs + [HumanMessage(content=hint)]
    runtime._graph_messages = msgs
    resp = model.invoke(msgs)
    return {"messages": [resp]}


async def _node_tools(state: AgentState, config) -> dict | Command:
    """执行工具；ask_user → interrupt；confirm/登录等同理走 runtime._ask。"""
    runtime = config["configurable"]["runtime"]
    _sync_runtime_state(runtime, state)
    hooks = config["configurable"].get("hooks") or {}
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return {}

    tc = last.tool_calls[0]
    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
    args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
    tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")

    if name == "ask_user":
        question = str((args or {}).get("question") or "")
        opts = (args or {}).get("options") or []
        ask_id = uuid.uuid4().hex[:8]
        skill = str(state.get("locked_skill") or runtime.current_skill or "")
        pending = {
            "ask_id": ask_id,
            "tool_call_id": tid,
            "question": question,
            "options": [str(x) for x in opts if str(x).strip()],
            "skill": skill,
            "field": "",
            "label": "",
            "type": "text",
            "attempt": 0,
            "max_attempts": MAX_ASK_ATTEMPTS,
        }
        schema = load_schema_for_skill(skill, str(state.get("person_id") or ""))
        pending = _infer_pending_field(pending, schema, question)
        filled = _slot_already_filled(state, skill, str(pending.get("field") or ""))
        if filled:
            blob = (state.get("forms") or {}).get(skill) or {}
            hint = filled_hint(schema, blob)
            return {"messages": [ToolMessage(
                content=(f"【不必再问】{pending.get('label') or pending.get('field')}已记下={filled}。"
                         f"{hint} 请 skill_run 推进，禁止重复提问。"),
                tool_call_id=tid, name="ask_user")]}
        push = hooks.get("push_ask")
        if push:
            await push(question, ask_id, pending["options"], None)
        register_active_ask(runtime.email, ask_id)
        return Command(
            update={"pending_ask": pending, "phase": "waiting_user"},
            goto="wait_ask",
        )

    result = await runtime._run_tool(name, args or {})
    if name == "done" and isinstance(result, dict) and result.get("ok"):
        runtime._done_reply = str((args or {}).get("reply") or "")
    out = {"messages": [ToolMessage(content=_dump(result), tool_call_id=tid, name=name)]}
    out.update(_collect_runtime_state_updates(runtime))
    return out


def _node_wait_ask(state: AgentState, config) -> dict | Command:
    """LangGraph interrupt：等人回答 → resolve_reply（零 LLM）。"""
    runtime = config["configurable"]["runtime"]
    _sync_runtime_state(runtime, state)
    pending = state.get("pending_ask") or {}
    payload = {
        "ask_id": pending.get("ask_id"),
        "question": pending.get("question"),
        "options": pending.get("options") or [],
    }
    register_active_ask(runtime.email, str(pending.get("ask_id") or ""))
    raw = interrupt(payload)
    feed, updates = _process_reply(str(raw or ""), pending, state)
    tid = str(pending.get("tool_call_id") or "")
    reopen = bool(updates.pop("_reopen", False))
    if "forms" in updates:
        runtime._graph_forms = dict(updates["forms"])
    if reopen:
        new_text = str(updates.get("user_text") or raw)
        return Command(
            update={
                **updates,
                "messages": [
                    ToolMessage(content="【客户改口，当前提问已结束】", tool_call_id=tid, name="ask_user"),
                    HumanMessage(content=new_text),
                ],
            },
            goto="route",
        )
    return {
        "messages": [ToolMessage(content=feed or raw, tool_call_id=tid, name="ask_user")],
        **updates,
    }


async def _node_force_ask(state: AgentState, config) -> dict | Command:
    """模型死活用文字问 → 引擎自己挂 ask_user，客户回答才能落盘。"""
    runtime = config["configurable"]["runtime"]
    _sync_runtime_state(runtime, state)
    hooks = config["configurable"].get("hooks") or {}
    last = state["messages"][-1]
    question = _extract_ai_text(last) if isinstance(last, AIMessage) else "请补充办理所需信息"
    question = question.strip() or "请补充办理所需信息"
    skill = str(state.get("locked_skill") or getattr(runtime, "current_skill", "") or "")
    schema = load_schema_for_skill(skill, str(state.get("person_id") or ""))
    blob = (state.get("forms") or {}).get(skill) or {}
    miss = missing_entry(schema, blob)
    pending = {
        "ask_id": uuid.uuid4().hex[:8],
        "tool_call_id": "force_ask",
        "question": question[:200],
        "options": [],
        "skill": skill,
        "field": "",
        "label": "",
        "type": "text",
        "attempt": 0,
        "max_attempts": MAX_ASK_ATTEMPTS,
    }
    if miss:
        it = miss[0]
        pending["field"] = it["field"]
        pending["label"] = str(it.get("label") or it["field"])
        pending["type"] = str(it.get("type") or "text")
        pending["question"] = f"请提供{pending['label']}"
    else:
        pending = _infer_pending_field(pending, schema, question)
        filled = _slot_already_filled(state, skill, str(pending.get("field") or ""))
        if filled or not pending.get("field"):
            hint = filled_hint(schema, blob) if schema else ""
            return {"messages": [HumanMessage(content=(
                "【系统】不要用文字向客户提问。入口信息已齐则 skill_run；"
                f"{hint}"
            ))]}
    push = hooks.get("push_ask")
    if push:
        await push(pending["question"], pending["ask_id"], [], None)
    register_active_ask(runtime.email, str(pending.get("ask_id") or ""))
    return Command(
        update={"pending_ask": pending, "phase": "waiting_user"},
        goto="wait_ask",
    )


def _node_correction(state: AgentState, config) -> dict:
    runtime = config["configurable"]["runtime"]
    _sync_runtime_state(runtime, state)
    if getattr(runtime, "current_skill", None) or state.get("locked_skill"):
        hint = ("你刚才用纯文字向客户索要信息（文字反问），违反铁律——"
                "请改用 ask_user 工具（一次一个问题）。")
    else:
        hint = ("若要办事：先 search/read_skill；缺信息用 ask_user。不要纯文字代替工具。")
    return {"messages": [HumanMessage(content=f"【系统提醒】{hint}")], "corrections": 1}


def _after_model(state: AgentState, config) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    text = _extract_ai_text(last)
    if not text:
        return END
    runtime = config["configurable"]["runtime"]
    hired = bool(state.get("hired"))
    user_text = str(state.get("user_text") or "")
    solicit = hired and runtime._needs_ask_user(text)
    zero_tool_task = (
        hired and not (state.get("locked_skill") or runtime.current_skill)
        and user_text and runtime._looks_like_task(user_text)
    )
    if solicit or zero_tool_task:
        if int(state.get("corrections") or 0) >= MAX_CORRECTIONS:
            return "force_ask" if solicit else END
        return "correction"
    return END


def get_compiled_graph():
    global _COMPILED
    if _COMPILED is not None:
        return _COMPILED

    g = StateGraph(AgentState)
    g.add_node("route", _node_route)
    g.add_node("model", _node_model)
    g.add_node("tools", _node_tools)
    g.add_node("wait_ask", _node_wait_ask)
    g.add_node("correction", _node_correction)
    g.add_node("force_ask", _node_force_ask)

    g.add_edge(START, "route")
    g.add_edge("route", "model")
    g.add_conditional_edges("model", _after_model,
                            {"tools": "tools", "correction": "correction",
                             "force_ask": "force_ask", END: END})
    g.add_edge("tools", "model")
    g.add_edge("wait_ask", "model")
    g.add_edge("correction", "model")
    g.add_edge("force_ask", "model")

    _COMPILED = g.compile(checkpointer=_make_checkpointer())
    return _COMPILED


# 唯一 resume 通道：feed_answer → Command(resume=...)
_resume_waiters: dict[str, asyncio.Future] = {}
_active_ask_ids: dict[str, str] = {}


def register_active_ask(email: str, ask_id: str) -> None:
    """当前正在等人的 ask_id（对号入座）。"""
    if email and ask_id:
        _active_ask_ids[email] = str(ask_id)


def feed_graph_resume(email: str, value: str, ask_id: str = "") -> bool:
    fut = _resume_waiters.get(email)
    if not fut or fut.done():
        return False
    current = _active_ask_ids.get(email) or ""
    incoming = str(ask_id or "").strip()
    if incoming and current and incoming != current:
        logger.warning("ask_id 对不上 current=%s got=%s device=%s", current, incoming, email)
        return False
    fut.set_result(str(value or ""))
    return True


async def run_agent_graph(
    *,
    runtime,
    system: str,
    user_content: str,
    history: list[dict] | None,
    hired: bool,
    conversation_id: str,
    allowed_skills: list[str] | None = None,
    person_id: str = "",
    hooks: dict | None = None,
    max_steps: int = 50,
) -> str:
    """LangGraph 原生：同 thread 续跑 + interrupt/resume 唯一等人机制。"""
    app = get_compiled_graph()
    thread_id = conversation_id or "default"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "runtime": runtime,
            "system": system,
            "hooks": hooks or {},
        },
        "recursion_limit": max(4, max_steps * 2),
    }

    user_text = user_content.split("【用户原话】")[-1] if "【用户原话】" in user_content else user_content

    snap = app.get_state(config)
    prev = (snap.values if snap else {}) or {}
    has_thread = bool(prev.get("messages"))

    runtime._done_reply = None
    runtime._graph_forms = dict(prev.get("forms") or {})
    runtime._graph_steps = list(prev.get("steps") or [])
    runtime._graph_forms_dirty = False
    runtime._graph_steps_dirty = False
    _resume_waiters[runtime.email] = asyncio.get_running_loop().create_future()

    common_update = {
        "user_text": user_text,
        "corrections": 0,
        "pending_ask": None,
        "hired": hired,
        "allowed_skills": allowed_skills or [],
        "person_id": person_id,
    }

    if has_thread:
        inp: Any = Command(update={
            **common_update,
            "messages": [HumanMessage(content=user_content)],
        })
    else:
        messages: list = []
        for h in (history or [])[-8:]:
            role, content = h.get("role"), str(h.get("content") or "")[:2000]
            if not content:
                continue
            messages.append(HumanMessage(content=content) if role == "user"
                             else AIMessage(content=content))
        messages.append(HumanMessage(content=user_content))
        inp = {
            "messages": messages,
            **common_update,
            "phase": prev.get("phase") or ("task" if hired else "chat"),
            "locked_skill": prev.get("locked_skill"),
            "lock_reason": prev.get("lock_reason") or "",
            "lock_entity": dict(prev.get("lock_entity") or {}),
            "forms": dict(prev.get("forms") or {}),
            "steps": list(prev.get("steps") or []),
            "done_reply": None,
        }

    try:
        result = await app.ainvoke(inp, config)

        while result.get("__interrupt__"):
            intr = result["__interrupt__"][0].value
            on_wait = (hooks or {}).get("on_waiting")
            if on_wait:
                await on_wait(intr)
            try:
                answer = await asyncio.wait_for(_resume_waiters[runtime.email], timeout=600)
            except asyncio.TimeoutError:
                on_timeout = (hooks or {}).get("on_timeout")
                if on_timeout:
                    await on_timeout()
                return "等您回复等太久了，这次就先到这儿。需要继续时再说一声。"
            on_answer = (hooks or {}).get("on_answer")
            if on_answer:
                await on_answer(answer)
            _resume_waiters[runtime.email] = asyncio.get_running_loop().create_future()
            on_run = (hooks or {}).get("on_running")
            if on_run:
                await on_run()
            result = await app.ainvoke(Command(resume=answer), config)

        if getattr(runtime, "_done_reply", None):
            return str(runtime._done_reply)

        on_steps = (hooks or {}).get("on_steps")
        final_steps = result.get("steps")
        if on_steps and isinstance(final_steps, list) and final_steps:
            await on_steps(final_steps)

        for msg in reversed(result.get("messages") or []):
            if isinstance(msg, AIMessage):
                text = _extract_ai_text(msg)
                if not text:
                    continue
                if hired and runtime._needs_ask_user(text):
                    continue
                return text
        return "（无回复）"
    finally:
        _resume_waiters.pop(runtime.email, None)
        _active_ask_ids.pop(runtime.email, None)