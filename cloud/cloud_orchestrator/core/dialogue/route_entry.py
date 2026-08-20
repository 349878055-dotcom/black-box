"""新消息入口路由：chat | task。"""
from __future__ import annotations

import re

from .skill_lock import detect_lock

# 明显办事意图（动词+宾语）
_TASK_VERBS = ("买", "订", "挂", "点", "办", "约", "购", "下单", "预约", "查")
_TASK_OBJS = ("票", "号", "餐", "外卖", "车票", "机票", "酒店", "订单", "菜", "医生", "专家")
# 纯闲聊 / 咨询特征（老百姓问「能不能」不是立刻填表）
_CHAT_KW = ("热不热", "冷不冷", "天气", "几度", "几点了", "你好", "在吗", "谢谢", "吃什么好")
_CONSULT_KW = ("能做哪些", "有哪些服务", "介绍下", "介绍一下", "你会什么", "能查哪些", "支持吗", "可以吗")


def looks_like_task(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    lock = detect_lock(t)
    asking = ("吗" in t or "能不能" in t) and not any(
        c in t for c in ("帮我", "我要", "给我", "请帮")
    )
    if lock:
        return not asking
    if asking:
        return False
    return any(v in t for v in _TASK_VERBS) and any(o in t for o in _TASK_OBJS)


def looks_like_chat(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if looks_like_task(t):
        return False
    if any(k in t for k in _CHAT_KW):
        return True
    if any(k in t for k in _CONSULT_KW):
        return True
    if "吗" in t and not looks_like_task(t) and len(t) <= 40:
        return True
    if re.match(r"^[嗯哦好啊谢谢]+[？?]?$", t):
        return True
    return False


def route_entry(
    text: str,
    dialogue: dict,
    *,
    hired: bool,
    allowed_skills: list[str] | None = None,
) -> str:
    """返回建议 phase：chat | task | idle。"""
    if not hired:
        return "chat"
    # 上轮 done/abandon 后新消息 → 重置
    if dialogue.get("phase") == "done" or dialogue.get("abandoned"):
        return "task" if looks_like_task(text) else "chat"
    if dialogue.get("locked_skill") and dialogue.get("phase") in ("task", "waiting_user"):
        return "task"
    if looks_like_chat(text):
        return "chat"
    if looks_like_task(text):
        return "task"
    # hired 会话默认：有 persona 且用户发话 → 倾向 task（办事员待命）
    return "task"
