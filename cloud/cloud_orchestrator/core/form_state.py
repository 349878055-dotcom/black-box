"""契约 form 字段表：通用表单状态（填一个存一个；资料卡字段不上云）。"""
from __future__ import annotations

from typing import Any


def parse_schema(form) -> list[dict]:
    """契约 form 数组 → 规范化字段表。非法 source 当 customer。"""
    out: list[dict] = []
    for item in form or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        if not field:
            continue
        source = str(item.get("source") or "customer").strip() or "customer"
        if source not in ("customer", "auto", "profile"):
            source = "customer"
        out.append({
            "field": field,
            "label": str(item.get("label") or field),
            "type": str(item.get("type") or "text"),
            "source": source,
            "from": str(item.get("from") or ""),
        })
    return out


def filled(v: Any) -> bool:
    return v not in (None, "", [], {})


def merge_into_params(schema: list[dict], values: dict, params: dict) -> dict:
    """已填表单值补进方法参数（不覆盖已有；profile 由手机填，不从云端灌）。"""
    params = dict(params or {})
    values = values or {}
    for item in schema:
        if item["source"] == "profile":
            continue
        f = item["field"]
        if not filled(params.get(f)) and filled(values.get(f)):
            params[f] = values[f]
    return params


def collect_from_params(schema: list[dict], values: dict, params: dict) -> dict:
    """方法参数里出现的表单字段写回状态。profile 不上云。"""
    values = dict(values or {})
    for item in schema:
        if item["source"] == "profile":
            continue
        f = item["field"]
        if filled((params or {}).get(f)):
            values[f] = params[f]
    return values


def match_answer(schema: list[dict], values: dict, question: str,
                 answer: str) -> tuple[str, str] | None:
    """把 ask_user 的回答记到还没填的 customer 字段（按问题里的 label 对上；只缺一项就记那一项）。"""
    if not (answer or "").strip():
        return None
    missing = [it for it in schema
               if it["source"] == "customer" and not filled((values or {}).get(it["field"]))]
    if not missing:
        return None
    q = question or ""
    hits = [it for it in missing if it["label"] and it["label"] in q]
    if len(hits) == 1:
        return hits[0]["field"], answer.strip()
    if len(missing) == 1:
        return missing[0]["field"], answer.strip()
    return None


def render_for_ai(schema: list[dict], values: dict) -> str:
    """给 read_skill：已填 / 还缺；每轮只强调没填的。"""
    if not schema:
        return ""
    values = values or {}
    lines = ["【表单字段】填一个存一个；只问还没填的 customer 项；auto 由代码补；profile 由手机资料卡填、不必问。"]
    missing: list[str] = []
    for it in schema:
        f, label, src = it["field"], it["label"], it["source"]
        if src == "profile":
            lines.append(f"- {label}（{f}）：资料卡自动填，不必问客户")
            continue
        val = values.get(f)
        if filled(val):
            shown = val if not isinstance(val, (dict, list)) else "(已填)"
            lines.append(f"- {label}（{f}）：已填 {shown}")
        elif src == "auto":
            src_m = it.get("from") or "?"
            lines.append(f"- {label}（{f}）：自动补（来自 {src_m}），不必问客户")
            missing.append(f"{label}（自动，来自 {src_m}）")
        else:
            lines.append(f"- {label}（{f}）：未填，请 ask_user 问")
            missing.append(label)
    if missing:
        lines.append("当前还缺：" + "、".join(missing))
    else:
        lines.append("当前还缺：无")
    return "\n".join(lines)
