"""
skill 注册表（平台逆向 API）— 主代理 skill_list / skill_run 的依据。

本仓库只「消费 skill」：每个 skill = 一个平台逆向 API（*_api.py 类，
requests 直调 HTTP 接口，返回结构化 dict/list，AI 可直接读）。
skill 的「制作」由专门项目负责，这里只注册 + 执行。
适配器实例全局保持（session 登录态不丢）。
"""
from __future__ import annotations

from .nj12320_api import Nj12320API
from .tuniu_api import TuniuAPI

# ── skill（平台逆向 API）→ 能力配置 ──
# methods: 方法名 → {desc 描述, need_login 是否需登录, params 参数说明}
# flow: 分层业务流程索引（给 AI 看的"地图"，按步骤顺着调用，不会乱）
ADAPTERS: dict[str, dict] = {
    "nj12320": {
        "name": "南京12320预约挂号",
        "class": Nj12320API,
        "flow": [
            {"step": 1, "title": "① 找医院", "methods": ["search_hospital"]},
            {"step": 2, "title": "② 找科室", "methods": ["list_departments"]},
            {"step": 3, "title": "③ 找医生（用 find_doctor 直接定位，或 list_doctors 按科室列）", "methods": ["find_doctor", "list_doctors"]},
            {"step": 4, "title": "④ 查排班（哪天有号，科室或医生）", "methods": ["get_schedule", "get_doctor_schedule"]},
            {"step": 5, "title": "⑤ 查具体时段（几点可约）", "methods": ["get_time_slots"]},
            {"step": 6, "title": "⑥ 登录（预约/提交前需要）", "methods": ["check_login", "login_auto", "login"]},
            {"step": 7, "title": "⑦ 预约提交（真挂号须确认）", "methods": ["check_res_rule", "get_confirm_page", "reserve", "book"]},
            {"step": 8, "title": "⑧ 其它（改密码）", "methods": ["change_password"]},
        ],
        "methods": {
            "search_hospital": {
                "desc": "按医院名搜医院 → [{name, hoscode}]",
                "need_login": False,
                "params": {"hosname": "医院名，如 南京鼓楼医院"},
            },
            "list_departments": {
                "desc": "医院科室列表 → [{name, depid}]",
                "need_login": False,
                "params": {"hoscode": "医院代码（search_hospital 得到）"},
            },
            "get_schedule": {
                "desc": "科室排班（可约格子，含 schcode/日期/上午下午/挂号费）",
                "need_login": False,
                "params": {"depid": "科室代码", "hoscode": "医院代码"},
            },
            "list_doctors": {
                "desc": "科室医生列表 → [{name, docid}]（专家号科室有）",
                "need_login": False,
                "params": {"depid": "科室代码", "hoscode": "医院代码"},
            },
            "find_doctor": {
                "desc": "按 医院名+医生名 直接找医生（自动遍历全科室定位，不用用户提供科室）→ {hospital, dep, doctor}",
                "need_login": False,
                "params": {"hosname": "医院名，如 南京鼓楼医院", "docname": "医生名，如 陈玲"},
            },
            "get_doctor_schedule": {
                "desc": "医生排班（可约格子，含 schcode/日期/上午下午/挂号费）",
                "need_login": False,
                "params": {"docid": "医生代码（list_doctors 得到）", "hoscode": "医院代码"},
            },
            "get_time_slots": {
                "desc": "某排班格子的可约时段 → [{code,startHour,endHour,state,takeTime}]",
                "need_login": False,
                "params": {"hoscode": "医院代码", "schcode": "排班代码", "ampm": "am 或 pm"},
            },
            "check_login": {
                "desc": "预约系统登录状态 → 用户名 或 空(未登录)",
                "need_login": False,
                "params": {},
            },
            "login": {
                "desc": "预约系统登录（需图形验证码，验证码由用户看图片输入）",
                "need_login": False,
                "params": {"username": "12320账号", "password": "密码", "verify_code": "图形验证码"},
            },
            "login_auto": {
                "desc": "全自动登录（本地 OCR 识别验证码，免人工看图；失败自动重试）",
                "need_login": False,
                "params": {"username": "12320账号", "password": "密码"},
            },
            "change_password": {
                "desc": "修改密码（⚠️改后旧密码失效；12320 弱口令账号会被强制要求改密）",
                "need_login": True,
                "params": {"new_password": "新密码（8~16位，含大写/小写/数字/特殊至少3种）"},
            },
            "check_res_rule": {
                "desc": "预约规则检查 → noLogin/noPhone/success",
                "need_login": True,
                "params": {"schcode": "排班代码"},
            },
            "get_confirm_page": {
                "desc": "预约确认页检查 → {login_required, url}（未登录需先 login）",
                "need_login": True,
                "params": {"schcode": "排班代码", "hoscode": "医院代码（可空）"},
            },
            "book": {
                "desc": "一键预约（高封装）：给医院名+医生名+日期(可选)，内部自动查/选/登录/提交。⚠️真挂号须用户确认",
                "need_login": True,
                "params": {"hosname": "医院名，如 南京鼓楼医院", "docname": "医生名，如 陈玲",
                           "date": "日期 MM-DD（可空=最近可约）", "ampm": "am或pm",
                           "username": "12320账号（未登录时用）", "password": "密码"},
            },
            "reserve": {
                "desc": "提交预约申请（⚠️ 真挂号有副作用，须用户确认；2026-08-05 实测成功）",
                "need_login": True,
                "params": {"schcode": "排班代码", "hoscode": "医院代码",
                           "hos_cfg_code": "时段代码（如 segTime1，必填）",
                           "res_time": "预约时间（可空）",
                           "iccardno": "市民卡号（可空）", "pay_way": "支付方式（默认0现场支付）"},
            },
        },
    },
    "tuniu": {
        "name": "途牛（机票/火车/酒店/门票）",
        "class": TuniuAPI,
        "flow": [
            {"step": 1, "title": "① 查火车票（出发/到达/日期）", "methods": ["search_train", "train_detail"]},
            {"step": 2, "title": "② 查机票（低价）", "methods": ["search_flight"]},
            {"step": 3, "title": "③ 查酒店（城市+日期）", "methods": ["search_hotel"]},
            {"step": 4, "title": "④ 查门票", "methods": ["search_ticket"]},
            {"step": 5, "title": "⑤ 订票/下单（⚠️ 支付走途牛，须用户确认）", "methods": ["book_train", "create_flight_order", "cancel_order"]},
            {"step": 6, "title": "⑥ 其它（列工具）", "methods": ["list_tools"]},
        ],
        "methods": {
            "search_train": {
                "desc": "火车票搜索 → 车次列表（含票价/余票，免费）",
                "need_login": False,
                "params": {"departure": "出发城市，如 南京", "arrival": "到达城市，如 北京",
                           "date": "出发日期 yyyy-MM-dd，如 2026-08-08"},
            },
            "train_detail": {
                "desc": "车次详情（站点/时刻）",
                "need_login": False,
                "params": {"train_num": "车次号，如 1462", "date": "日期 yyyy-MM-dd"},
            },
            "search_flight": {
                "desc": "机票搜索（低价航班列表，免费）",
                "need_login": False,
                "params": {"departure": "出发城市", "arrival": "到达城市", "date": "日期 yyyy-MM-dd"},
            },
            "search_hotel": {
                "desc": "酒店搜索（城市+入住/离店日期）",
                "need_login": False,
                "params": {"city": "城市，如 南京", "check_in": "入住日期 yyyy-MM-dd", "check_out": "离店日期 yyyy-MM-dd"},
            },
            "search_ticket": {
                "desc": "景点门票查询",
                "need_login": False,
                "params": {"scenic_name": "景点名"},
            },
            "book_train": {
                "desc": "预订火车票（⚠️ 真购买，支付走途牛，须用户明确确认）",
                "need_login": False,
                "params": {"departureCityName": "出发城市", "arrivalCityName": "到达城市",
                           "departureDate": "日期", "trainNum": "车次号", "seatType": "席别"},
            },
            "create_flight_order": {
                "desc": "创建机票订单（⚠️ 真购买，支付走途牛，须用户明确确认）",
                "need_login": False,
                "params": {"departureCityName": "出发城市", "arrivalCityName": "到达城市",
                           "departureDate": "日期", "flightNo": "航班号"},
            },
            "cancel_order": {
                "desc": "取消未支付订单",
                "need_login": False,
                "params": {"category": "业务分类 train/flight（默认train）", "orderId": "订单号"},
            },
            "list_tools": {
                "desc": "列出途牛某分类可用工具",
                "need_login": False,
                "params": {"category": "train/flight/hotel/ticket/cruise/holiday"},
            },
        },
    },
}

_instances: dict[str, object] = {}


def _get_instance(platform: str):
    if platform not in _instances:
        _instances[platform] = ADAPTERS[platform]["class"]()
    return _instances[platform]


def list_skills() -> list[dict]:
    """skill_list：所有 skill（平台逆向 API）及其能力（含分层 flow 索引）。"""
    out = []
    for platform, cfg in ADAPTERS.items():
        out.append({
            "skill": platform,
            "name": cfg["name"],
            "flow": cfg.get("flow", []),   # 分层业务地图（先看这个，按步骤走）
            "methods": [
                {"name": m, **info}
                for m, info in cfg["methods"].items()
            ],
        })
    return out


def run(skill: str, method: str, params: dict | None = None) -> dict:
    """skill_run：执行 skill（调平台逆向 API 方法），返回统一 dict {ok, data/error}。"""
    cfg = ADAPTERS.get(skill or "")
    if not cfg:
        return {"ok": False, "error": f"skill 不存在：{skill or '空'}"}
    if method not in cfg["methods"]:
        return {"ok": False, "error": f"skill {skill} 无方法：{method}"}
    try:
        inst = _get_instance(skill)
        fn = getattr(inst, method)
        data = fn(**(params or {}))
        return {"ok": True, "skill": skill, "method": method, "data": data}
    except Exception as e:
        return {"ok": False, "error": f"{skill}.{method} 异常：{e}"}
