"""pending_ask 回复 → Command（规则 + AnswerCheck）。客户原话先过引擎。"""
from __future__ import annotations

from .answer_check import (
    check_answer,
    is_abandon,
    is_off_topic_chat,
    load_schema_for_skill,
)
from .commands import Command, CommandKind
from .slots import (
    detect_modify,
    extract_slots,
    is_payment_return,
    is_switch_task,
    resolve_option,
)


def resolve_reply(
    text: str,
    pending: dict,
    *,
    person_id: str = "",
    locked_skill: str | None = None,
    allowed_skills: list[str] | None = None,
) -> Command:
    """纯函数：用户回答 → Command。"""
    t = (text or "").strip()
    field = str(pending.get("field") or "")
    label = str(pending.get("label") or field)
    ftype = str(pending.get("type") or "text")
    skill = str(pending.get("skill") or locked_skill or "")
    opts = pending.get("options") or []

    mapped = resolve_option(t, opts)
    if mapped:
        t = mapped

    if is_switch_task(t, skill or locked_skill, allowed_skills):
        return Command(kind=CommandKind.NEW_INTENT, reason="用户改口办另一件事", value=t)

    if is_abandon(t):
        return Command(kind=CommandKind.ABANDON, reason="用户放弃当前办事")

    if is_payment_return(t):
        return Command(kind=CommandKind.PAYMENT_RETURN, reason="客户表示已支付")

    schema = load_schema_for_skill(skill, person_id) if skill else []
    modified = detect_modify(t, schema, pending_field=field) if schema else {}
    extracted = extract_slots(t, schema) if schema else {}

    if is_off_topic_chat(t) and not extracted and not modified:
        return Command(
            kind=CommandKind.OFF_TOPIC_CHAT,
            slot_field=field,
            reason="办事中插话闲聊",
        )

    # 改口改的是别的字段（问出发地时说「改成后天」）
    if modified and field and field not in modified:
        items = list(modified.items())
        first_f, first_v = items[0]
        extra = {k: v for k, v in items[1:]}
        extra.update({k: v for k, v in extracted.items() if k != first_f})
        return Command(
            kind=CommandKind.SET_SLOT,
            slot_field=first_f,
            value=str(first_v),
            skill=skill,
            extra=extra,
            reason="客户改口字段",
        )

    ok, reason = (True, "") if not field else check_answer(t, field, ftype, label)
    if reason == "__abandon__":
        return Command(kind=CommandKind.ABANDON, reason="用户放弃当前办事")

    extra = {k: v for k, v in {**extracted, **modified}.items() if k != field}

    if field and ok:
        return Command(
            kind=CommandKind.SET_SLOT,
            slot_field=field,
            value=t,
            skill=skill,
            extra=extra,
        )

    # 当前问项没过，但整句抽出了槽（「明天北京到上海」）
    merged = {**extracted, **modified}
    if merged:
        if field and field in merged:
            val = merged.pop(field)
            return Command(
                kind=CommandKind.SET_SLOT,
                slot_field=field,
                value=str(val),
                skill=skill,
                extra=merged,
            )
        first_f, first_v = next(iter(merged.items()))
        rest = {k: v for k, v in merged.items() if k != first_f}
        return Command(
            kind=CommandKind.SET_SLOT,
            slot_field=first_f,
            value=str(first_v),
            skill=skill,
            extra=rest,
            reason="整句拆槽",
        )

    if field and not ok:
        return Command(kind=CommandKind.REASK, slot_field=field, reason=reason or "回答无效")

    return Command(kind=CommandKind.SET_SLOT, slot_field=field, value=t, skill=skill)

