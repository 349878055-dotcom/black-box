"""
date_utils — 确定性时间解析工具（不依赖 LLM 猜）。

把用户话里的「相对/模糊时间」规则化解析成具体日期（YYYY-MM-DD）。
主代理（Agent.handle）处理消息前调用，把解析结果注入上下文，
LLM 直接用具体日期调 skill_run，不再反问"这两天是哪两天"。

支持（按优先级匹配）：
- 今天/今日、明天/明日、后天、大后天、昨天、前天
- 这两天 / 这三天 / 近几天 / 这几天
- 本周X/这周X/这个周X、下周X、下下周X、周末、本周、下周
- YYYY-MM-DD、X月X日/X月X号、N天后、X号（当月）
"""
from __future__ import annotations

import datetime
import re
from typing import Any

WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _fmt(d: datetime.date) -> str:
    return d.isoformat()


def _this_weekday(t: datetime.date, wd: int) -> datetime.date:
    """本周中星期 wd（0=周一）的日期（周一起始）。"""
    return t + datetime.timedelta(days=(wd - t.weekday()) % 7)


def resolve_dates(text: str, today: str | None = None) -> dict[str, Any]:
    """解析文本中的相对时间 → 具体日期列表。

    today: YYYY-MM-DD，默认取系统今天。
    返回 {"today": "YYYY-MM-DD", "dates": [...], "note": "说明", "matched": [...], "found": bool}
    """
    t = datetime.date.fromisoformat(today) if today else datetime.date.today()
    dates: list[str] = []
    note_parts: list[str] = []
    matched: list[str] = []

    def add(d: datetime.date, label: str) -> None:
        s = _fmt(d)
        if s not in dates:
            dates.append(s)
            note_parts.append(f"{label}={s}")

    if not text:
        return {"today": _fmt(t), "dates": [], "note": "", "matched": [], "found": False}

    # ── 1. 单日相对词（先长后短；"大后天"用负向后瞻避免被"后天"重复命中）──
    single = [
        (r"大后天", 3), (r"(?<!大)后天|(?<!大)後天", 2), (r"明天|明日|明儿", 1),
        (r"今天|今日", 0), (r"昨天|昨日", -1), (r"前天", -2),
    ]
    for pat, off in single:
        if re.search(pat, text):
            matched.append(pat)
            add(t + datetime.timedelta(days=off), "今天" if off == 0 else (pat if off > 0 else "昨天"))

    # ── 2. 区间/多日 ──
    multi = [
        (r"这两天", [0, 1]), (r"这三天|最近三天", [0, 1, 2]),
        (r"(近几天|这几天|最近几天)", [0, 1, 2]),
        (r"未来三天|后三天", [1, 2, 3]),
    ]
    for pat, offs in multi:
        if re.search(pat, text):
            matched.append(pat)
            for off in offs:
                add(t + datetime.timedelta(days=off), pat)

    # ── 3. 周几（本周/这周/这星期/下周/下星期/下下周）──
    for wd_name, wd in WEEKDAYS.items():
        # 本周X / 这周X / 这星期X / 这礼拜X
        if re.search(rf"(?:本周|这周|这个周|这星期|这个星期|这礼拜|这个礼拜)(?:{wd_name})", text):
            matched.append(f"本周{wd_name}")
            add(_this_weekday(t, wd), f"本周{wd_name}")
        # 下周X / 下个周X / 下星期X / 下礼拜X
        if re.search(rf"下(?:个?周|星期|礼拜)(?:{wd_name})", text):
            matched.append(f"下周{wd_name}")
            add(_this_weekday(t, wd) + datetime.timedelta(weeks=1), f"下周{wd_name}")
        # 下下周X / 下下星期X
        if re.search(rf"下下(?:周|星期|礼拜)(?:{wd_name})", text):
            matched.append(f"下下周{wd_name}")
            add(_this_weekday(t, wd) + datetime.timedelta(weeks=2), f"下下周{wd_name}")
    if re.search(r"周末", text):
        matched.append("周末")
        add(_this_weekday(t, 5), "周六")
        add(_this_weekday(t, 6), "周日")
    if re.search(r"(?:本周|这周)", text) and not dates:
        matched.append("本周")
        for i in range(7):
            add(t + datetime.timedelta(days=i), f"本周+{i}天")
    if re.search(r"下周", text) and not dates:
        matched.append("下周")
        for i in range(7):
            add(t + datetime.timedelta(days=7 + i), f"下周+{i}天")

    # ── 4. 明确日期 ──
    for m in re.finditer(r"(\d{4})-(\d{1,2})-(\d{1,2})", text):
        try:
            add(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "YYYY-MM-DD")
        except Exception:
            pass
    for m in re.finditer(r"(\d{1,2})月(\d{1,2})[号日]", text):
        try:
            d = datetime.date(t.year, int(m.group(1)), int(m.group(2)))
            add(d, f"{m.group(1)}月{m.group(2)}日")
        except Exception:
            pass
    m = re.search(r"(\d+)\s*天(?:后|之后)?", text)
    if m:
        matched.append("N天后")
        add(t + datetime.timedelta(days=int(m.group(1))), f"{m.group(1)}天后")
    for m in re.finditer(r"(?<![\d月])(\d{1,2})号", text):
        try:
            add(datetime.date(t.year, t.month, int(m.group(1))), f"{m.group(1)}号")
        except Exception:
            pass

    # 去重保序
    seen: set[str] = set()
    uniq = [x for x in dates if not (x in seen or seen.add(x))]
    note = "；".join(dict.fromkeys(note_parts))
    return {
        "today": _fmt(t),
        "dates": uniq,
        "note": note,
        "matched": matched,
        "found": bool(uniq),
    }


def summarize(text: str, today: str | None = None) -> str:
    """给主代理用的摘要：总是注入「今天」（云时间）作基准。

    匹配到相对/模糊时间 → 附具体日期，直接让 LLM 用；
    未匹配到 → 也返回「今天」基准，由 LLM 自行兜底推算（如"这两天/本周/下周三"），
    不再返回空串导致 LLM 猜错年份或反问用户日期。
    """
    r = resolve_dates(text, today)
    base = f"【时间解析】今天是{r['today']}（云端服务器日期）。"
    if not r["found"]:
        return (base + "你提到的日期若是相对表达（如这两天/这几天/本周/下周），"
                       "请按此基准自行换算成 YYYY-MM-DD 再执行，不要反问用户具体日期。")
    date_str = "、".join(r["dates"])
    return (f"【时间解析】今天是{r['today']}（云端服务器日期）；"
            f"你提到的相对时间已解析为具体日期：{date_str}。"
            f"请直接用这些日期执行，不要反问用户具体日期。")


# 命中这些词才注入「当前时刻」（按需，避免每轮带噪音/过时）
_CLOCK_KW = [
    "几点", "几点钟", "几点几分", "现在是", "此刻", "当前时间", "现在时间",
    "上午", "下午", "早上", "中午", "晚上", "凌晨", "清晨", "傍晚",
    "现在", "这会儿", "多久", "还有多久", "什么时候", "几点了", "几点啦",
]


def clock_note(text: str, now: datetime.datetime | None = None) -> str:
    """当前时刻注入（按需）：命中时间敏感词才返回「现在是 YYYY-MM-DD HH:MM（云时间）」，
    否则返回空串。避免每轮都带当前时刻造成噪音 / 工具循环中时刻过时。"""
    if not text:
        return ""
    if not any(k in text for k in _CLOCK_KW):
        return ""
    now = now or datetime.datetime.now()
    return (f"【当前时刻】现在是{now.strftime('%Y-%m-%d %H:%M')}（云端服务器时间）。"
            f"如需判断上午/下午、现在几点、距离某时刻多久，请以此为准。")


