"""客户原话 → 槽位（整句拆槽 / 改字段 / 点选第几个）。零 LLM。"""
from __future__ import annotations

import re

from ..date_utils import resolve_dates
from .skill_lock import detect_lock

# 常见城市（覆盖老百姓买票说法；未列入的仍可由当前问项整句写入）
_CITIES = (
    "北京", "上海", "广州", "深圳", "南京", "杭州", "苏州", "成都", "重庆", "武汉",
    "西安", "天津", "长沙", "郑州", "青岛", "大连", "厦门", "福州", "合肥", "南昌",
    "昆明", "贵阳", "南宁", "海口", "三亚", "哈尔滨", "长春", "沈阳", "太原", "石家庄",
    "济南", "宁波", "无锡", "常州", "温州", "金华", "嘉兴", "徐州", "扬州", "镇江",
    "南通", "盐城", "淮安", "连云港", "泰州", "宿迁", "芜湖", "蚌埠", "黄山", "洛阳",
    "开封", "珠海", "佛山", "东莞", "中山", "惠州", "桂林", "丽江", "拉萨", "乌鲁木齐",
    "银川", "西宁", "呼和浩特", "香港", "澳门", "台北",
)

_SEATS = ("商务座", "特等座", "一等座", "二等座", "硬卧", "软卧", "硬座", "无座", "一等", "二等")

_MODIFY_HINT = ("改成", "换成", "改到", "改成去", "改去", "不是", "别的", "改一下", "改成")

_PAY_DONE = ("付好了", "付好啦", "已支付", "付完了", "支付成功", "付了钱", "付过了", "我付了")

# 换事：必须落到另一件才艺，不能把「帮我」当换事
_SWITCH_VERBS = {
    "meituan_waimai": ("点外卖", "点个外卖", "叫外卖", "点餐", "点杯", "美团"),
    "glyy": ("挂号", "挂个号", "鼓楼"),
    "njpkzyy": ("浦口", "中医院"),
    "tuniu": ("买票", "订票", "火车票", "高铁票"),
}


def resolve_option(text: str, options: list | None) -> str | None:
    """「第二个 / 选2 / 2」→ 对应按钮文案。"""
    opts = [str(x).strip() for x in (options or []) if str(x).strip()]
    if not opts:
        return None
    t = (text or "").strip()
    if not t:
        return None
    for o in opts:
        if t == o or (len(t) >= 2 and t in o):
            return o
    cn = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    m = re.match(
        r"^(?:选|要)?(?:第)?([一二两三四五六七八九十\d]+)(?:个|项|条|号|班)?$",
        t,
    )
    if not m:
        m = re.match(r"^([一二两三四五六七八九十\d]+)$", t)
    if not m:
        return None
    raw = m.group(1)
    if raw.isdigit():
        idx = int(raw)
    else:
        idx = cn.get(raw, 0)
    if 1 <= idx <= len(opts):
        return opts[idx - 1]
    return None


def is_payment_return(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 24:
        return False
    return any(k in t for k in _PAY_DONE)


def is_switch_task(text: str, current_skill: str | None,
                   allowed_skills: list[str] | None = None) -> bool:
    """办事提问中途换成另一件事（点外卖 / 挂号），不是改日期。"""
    t = (text or "").strip()
    if not t:
        return False
    cur = str(current_skill or "").strip()
    lock = detect_lock(t, allowed_skills)
    if lock and cur and lock[0] != cur:
        return True
    if lock and not cur:
        return False
    for skill, verbs in _SWITCH_VERBS.items():
        if any(v in t for v in verbs):
            if cur and skill != cur:
                return True
            if not cur and skill:
                # 等待中但还没 lock：买票中途说挂号也算换事
                if any(v in t for v in verbs) and len(t) <= 40:
                    if "改成" in t or "换成" in t or "算了" in t or "不买" in t:
                        return True
                    if skill != "tuniu" and any(v in t for v in ("挂号", "点外卖", "点个外卖", "叫外卖")):
                        return True
    return False


def extract_slots(text: str, schema: list[dict] | None = None) -> dict[str, str]:
    """从一句口语里抽出能确定的字段。"""
    t = (text or "").strip()
    if not t:
        return {}
    out: dict[str, str] = {}
    fields = {str(it.get("field") or "") for it in (schema or [])}

    dep, arr = _route_cities(t)
    if dep and (not fields or "departure" in fields):
        out["departure"] = dep
    if arr and (not fields or "arrival" in fields):
        out["arrival"] = arr

    dates = resolve_dates(t)
    asking_clock = any(k in t for k in ("几点", "几时", "几点了", "天气", "几度", "热不热"))
    if dates.get("found") and dates.get("dates") and not asking_clock:
        d0 = str(dates["dates"][0])
        if not fields or "date" in fields:
            out["date"] = d0
        if not fields or "appointment_time" in fields:
            if "挂号" in t or "科室" in t or "医生" in t or "appointment_time" in fields:
                out.setdefault("appointment_time", d0)

    for seat in _SEATS:
        if seat in t and (not fields or "seat_name" in fields):
            out["seat_name"] = "一等座" if seat == "一等" else ("二等座" if seat == "二等" else seat)
            break

    m_train = re.search(r"([GDCZKT]\d{1,5})", t, re.I)
    if m_train and (not fields or "train_num" in fields):
        out["train_num"] = m_train.group(1).upper()

    m_phone = re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", t)
    if m_phone and (not fields or "contact_tel" in fields or "phone" in fields):
        if "contact_tel" in fields or not fields:
            out["contact_tel"] = m_phone.group(1)
        if "phone" in fields:
            out["phone"] = m_phone.group(1)

    return out


def detect_modify(text: str, schema: list[dict], pending_field: str = "") -> dict[str, str]:
    """「改成后天 / 目的地改杭州 / 不是上海是杭州」→ 要改的字段。"""
    t = (text or "").strip()
    if not t:
        return {}
    if not any(h in t for h in _MODIFY_HINT) and "改" not in t:
        # 无改口词时，整句抽槽仍可能发生（由 extract 处理）
        return {}
    extracted = extract_slots(t, schema)
    if not extracted:
        return {}
    # 改口时不要把当前问项整句误当成城市
    if pending_field in ("departure", "arrival") and pending_field in extracted:
        if extracted[pending_field] == t:
            extracted.pop(pending_field, None)
    return extracted


def entry_items(schema: list[dict]) -> list[dict]:
    """先问「入口信息」（出发/到达/日期），查完再问车次乘客。"""
    cust = [it for it in (schema or []) if it.get("source") == "customer"]
    marked = [it for it in cust if it.get("collect") == "entry"]
    if marked:
        return marked
    return cust[:3]


def missing_entry(schema: list[dict], values: dict) -> list[dict]:
    vals = values or {}
    out = []
    for it in entry_items(schema):
        v = vals.get(it["field"])
        if v in (None, "", [], {}):
            out.append(it)
    return out


def filled_hint(schema: list[dict], values: dict, *, next_ask: bool = True) -> str:
    vals = values or {}
    parts = []
    for it in (schema or []):
        if it.get("source") != "customer":
            continue
        f = it["field"]
        if vals.get(f) not in (None, "", [], {}):
            parts.append(f"{it.get('label') or f}={vals[f]}")
    miss = missing_entry(schema, vals)
    lines = []
    if parts:
        lines.append("【已记下】" + "；".join(parts))
    if next_ask and miss:
        nxt = miss[0]
        lines.append(f"【还缺】{nxt.get('label') or nxt['field']}。请用 ask_user 一次只问这一项，不要重复问已记下的。")
    elif next_ask:
        lines.append("【入口信息已齐】请 skill_run 查询推进，不要再问已记下的项。")
    return "\n".join(lines)


def _route_cities(text: str) -> tuple[str, str]:
    t = text.replace(" ", "")
    m = re.search(r"(?:从)?([^到去至]{2,8}?)(?:到|去|至)([^的票高铁火车，,。]{2,8})", t)
    if m:
        a, b = m.group(1), m.group(2)
        da, db = _city_in(a), _city_in(b)
        if da and db:
            return da, db
        if da and len(b) <= 6:
            return da, _strip_city_tail(b)
        if db and len(a) <= 6:
            return _strip_city_tail(a), db
    found = []
    for c in _CITIES:
        i = t.find(c)
        if i >= 0:
            found.append((i, c))
    found.sort()
    if len(found) >= 2:
        return found[0][1], found[1][1]
    if len(found) == 1 and re.search(r"(到|去|至)", t):
        # 「去上海」只有到达
        if t.find(found[0][1]) > t.find("到") or t.find("去") >= 0:
            if re.match(r"^(去|到|至)", t) or "到" in t[: t.find(found[0][1]) + 1]:
                return "", found[0][1]
    return ("", "")


def _city_in(chunk: str) -> str:
    for c in _CITIES:
        if c in chunk:
            return c
    return ""


def _strip_city_tail(chunk: str) -> str:
    s = re.sub(r"(站|市|高铁站|火车站)$", "", chunk.strip())
    return s[:8]
