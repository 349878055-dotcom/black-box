"""AnswerCheck：按契约 form 字段类型做确定性校验。"""
from __future__ import annotations

import re

from ..form_state import parse_schema
from ..date_utils import resolve_dates

# 答非所问：时间/天气类插话
_OFF_TOPIC_KW = ("几点", "几时", "几点了", "天气", "热不热", "冷不冷", "多少度", "温度")
# 放弃信号（短句高置信）
_ABANDON_KW = ("算了", "不买了", "不要了", "不搞了", "不用了", "取消吧", "别办了", "不办了")
# 新意图（≠放弃）：换一件事。不要把「帮我/改成」当换事（那是改字段或同一件事）。
_NEW_INTENT_KW = ("帮我把", "改办")
_NEW_INTENT_VERBS = ("取消订单", "退单", "挂号", "点外卖", "点个外卖", "叫外卖")


def check_answer(
    text: str,
    field: str,
    field_type: str,
    label: str = "",
) -> tuple[bool, str]:
    """返回 (通过, 失败原因)。"""
    t = (text or "").strip()
    if not t:
        return False, "回答为空"

    # 放弃类（在字段校验前先判）
    if any(k in t for k in _ABANDON_KW) and len(t) <= 20:
        if not any(k in t for k in _NEW_INTENT_KW):
            return False, "__abandon__"

    lbl = label or field

    # 出发/到达城市：拒绝时间/天气插话
    if field in ("departure", "arrival") or "城市" in lbl or "站" in lbl:
        if any(k in t for k in _OFF_TOPIC_KW):
            return False, "这不像城市名，请提供具体城市或车站"
        if re.search(r"\d{1,2}[:：点]\d{0,2}", t):
            return False, "您在问时间吗？请先告诉我城市"

    # 日期字段
    if field_type == "date" or "日期" in lbl:
        r = resolve_dates(t)
        if not r.get("found"):
            if any(k in t for k in _OFF_TOPIC_KW):
                return False, "请先提供出行日期"
            return False, "请提供具体日期（如明天、3月5日）"

    # 手机号
    if field in ("contact_tel", "phone", "mobile") or "手机" in lbl:
        digits = re.sub(r"\D", "", t)
        if len(digits) < 11:
            return False, "请提供11位手机号"

    return True, ""


def is_abandon(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 24:
        return False
    if any(k in t for k in _NEW_INTENT_KW) or any(k in t for k in _NEW_INTENT_VERBS):
        return False
    return any(k in t for k in _ABANDON_KW)


def is_off_topic_chat(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 30:
        return False
    if any(k in t for k in _OFF_TOPIC_KW):
        return True
    if t in ("谢谢", "多谢", "好的", "嗯", "哦", "知道了", "辛苦了"):
        return True
    return False


def load_schema_for_skill(skill: str, person_id: str) -> list[dict]:
    try:
        from ...adapters.registry import get_adapter
        cfg = get_adapter(skill, person_id) or {}
        form = cfg.get("form")
        if isinstance(form, dict):
            form = form.get("form")
        return parse_schema(form)
    except Exception:
        return []
