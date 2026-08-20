"""LangGraph 原生 AgentState —— 对话相位 / 表单 / SkillLock 全在图状态里。"""
from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired

from langgraph.graph import MessagesState


def _replace(left: Any, right: Any) -> Any:
    """后者覆盖前者。允许用空串清空 locked_skill。"""
    return right


def _merge_dict(left: dict | None, right: dict | None) -> dict:
    base = dict(left or {})
    if right:
        base.update(right)
    return base


def _replace_list(left: list | None, right: list | None) -> list:
    if right is None:
        return list(left or [])
    return list(right)


class AgentState(MessagesState):
    """LangGraph 图状态（checkpointer 持久化，thread_id = conversation_id）。"""

    corrections: Annotated[int, operator.add]
    phase: Annotated[str, _replace]                    # idle|chat|task|waiting_user|done
    locked_skill: Annotated[str | None, _replace]
    lock_reason: Annotated[str, _replace]
    lock_entity: Annotated[dict, _replace]
    pending_ask: Annotated[dict | None, _replace]
    forms: Annotated[dict, _merge_dict]                 # {skill: {field: value}}
    steps: Annotated[list, _replace_list]               # [{step,title,status}]
    user_text: Annotated[str, _replace]
    hired: Annotated[bool, _replace]
    done_reply: Annotated[str | None, _replace]
    allowed_skills: NotRequired[list[str]]
    person_id: NotRequired[str]
