"""
skill 注册表（平台逆向 API）— 主代理 skill_list / skill_run 的依据。

本仓库只「消费 skill」：每个 skill = 一个平台逆向 API（*_api.py 类，
requests 直调 HTTP 接口，返回结构化 dict/list，AI 可直接读）。
skill 的「制作」由专门项目（Skill工作台）负责，这里只注册 + 执行。
适配器实例全局保持（session 登录态不丢）。

2026-08-06 更新：
- 新增 glyy（南京鼓楼医院互联网医院，26 方法）
- tuniu 增加官网版 web_* 方法（TuniuWebAPI：查车次/下单/订单/取消）
"""
from __future__ import annotations

from .tuniu_api import TuniuAPI, TuniuWebAPI
from .glyy_api import GlyyAPI

# ── skill（平台逆向 API）→ 能力配置 ──
# methods: 方法名 → {desc 描述, need_login 是否需登录, params 参数说明}
# flow: 分层业务流程索引（给 AI 看的"地图"，按步骤顺着调用，不会乱）
# web_class / web_methods: 同一平台第二套实现（如途牛官网），方法名 web_* 前缀
# aliases: 平台别名（向量检索用，客户常说的名字）
# methods 里可带 keywords: 方法检索关键词（用户常见说法）
ADAPTERS: dict[str, dict] = {
    "glyy": {
        "name": "南京鼓楼医院互联网医院（微信小程序）",
        "aliases": ["鼓楼医院", "南京鼓楼医院", "鼓楼", "鼓楼医院互联网医院", "鼓楼医院小程序"],
        "class": GlyyAPI,
        "flow": [
            {"step": 1, "title": "① 查科室", "methods": ["list_depts"]},
            {"step": 2, "title": "② 查科室医生", "methods": ["list_doctors"]},
            {"step": 3, "title": "③ 可约日期", "methods": ["get_available_dates"]},
            {"step": 4, "title": "④ 查排班（含时段明细）", "methods": ["get_schedule"]},
            {"step": 5, "title": "⑤ 患者信息", "methods": ["get_patient"]},
            {"step": 6, "title": "⑥ 登录（图形验证码+短信真人配合）", "methods": ["get_graphical_captcha", "send_sms", "login"]},
            {"step": 7, "title": "⑦ 提交挂号（⚠️真挂号，须确认）", "methods": ["register", "book"]},
            {"step": 8, "title": "⑧ 订单/取消", "methods": ["list_orders", "cancel_reservation"]},
        ],
        "methods": {
            "list_depts": {"desc": "科室列表（533个）→ [{dept_code, dept_name, branch_code}]", "keywords": ["科室", "看什么科", "科室列表"], "need_login": False, "params": {}},
            "list_doctors": {"desc": "科室医生 → [{doctor_code, doctor_name, title, intro}]", "keywords": ["医生", "有哪些医生", "专家医生"], "need_login": False, "params": {"dept_code": "科室代码"}},
            "get_available_dates": {"desc": "可预约日期列表", "keywords": ["可约日期", "哪天能挂", "放号日期"], "need_login": False, "params": {"dept_code": "科室代码", "begin": "YYYY-MM-DD可空", "end": "YYYY-MM-DD可空", "business_type": "1普通/2专家"}},
            "get_schedule": {"desc": "排班 → {normal, expert}，每条含 schedule_id + detail(时段)", "keywords": ["排班", "号源", "出诊", "门诊时间", "可约时间"], "need_login": False, "params": {"dept_code": "科室代码", "date": "YYYY-MM-DD", "business_type": "1/2", "schedule_type": "1/2", "type_": "0/1"}},
            "get_patient": {"desc": "患者信息 → {name, id_card(可能脱敏), phone}", "keywords": ["我的信息", "就诊人", "患者", "身份证"], "need_login": True, "params": {}},
            "get_graphical_captcha": {"desc": "步骤1：抓图形验证码 → /tmp/glyy_captcha.png（用户看图）", "keywords": ["验证码", "图形验证码"], "need_login": False, "params": {"phone": "手机号"}},
            "send_sms": {"desc": "步骤2：发短信验证码", "keywords": ["发短信", "短信验证码"], "need_login": False, "params": {"phone": "手机号", "gcode": "图形验证码"}},
            "login": {"desc": "步骤3：手机号+短信验证码登录 → 保存 token", "keywords": ["登录", "验证码登录"], "need_login": False, "params": {"phone": "手机号", "code": "短信验证码"}},
            "register": {"desc": "提交挂号 ⚠️真挂号须确认", "keywords": ["挂号", "预约", "挂个号", "提交挂号"], "need_login": True, "params": {"dept_code": "科室", "doctor_code": "医生", "appointment_time": "日期", "schedule_id": "排班ID", "schedule_num_id": "时段ID", "start_hour": "时段", "reg_fee": "元", "business_type": "1/2", "patient": "患者dict"}},
            "book": {"desc": "一键挂号（自动查排班选时段提交）⚠️真挂号须确认", "keywords": ["挂号", "预约", "挂某某的号", "帮挂号", "看病", "就诊", "挂个号"], "need_login": True, "params": {"dept_code": "科室代码可空", "dept_name": "科室名", "doctor_code": "医生可空", "date": "日期可空", "business_type": "2专家/1普通", "id_card": "身份证", "open_id": "微信openid可空"}},
            "list_orders": {"desc": "我的预约/订单列表", "keywords": ["我的预约", "我的挂号", "订单", "已约的号"], "need_login": True, "params": {"page": "0", "size": "10"}},
            "cancel_reservation": {"desc": "取消预约（⚠️7天退约次数限制）", "keywords": ["取消预约", "退号", "取消挂号", "退约"], "need_login": True, "params": {"schedule_id": "排班ID"}},
            "list_reports": {"desc": "查报告（check检查/examine检验，需日期范围）", "keywords": ["报告", "检查报告", "检验报告", "化验单", "报告单", "结果"], "need_login": True, "params": {"start_date": "YYYY-MM-DD可空", "end_date": "YYYY-MM-DD可空", "kind": "check/examine"}},
            "clinic_no_paid": {"desc": "门诊待缴费列表", "keywords": ["缴费", "待缴费", "费用", "欠费", "付钱"], "need_login": True, "params": {}},
            "visit_records": {"desc": "就诊记录（POST）", "keywords": ["就诊记录", "看过什么病", "历史就诊"], "need_login": True, "params": {}},
            "get_recipe": {"desc": "按就诊查处方列表", "keywords": ["处方", "药方", "开药", "药品"], "need_login": True, "params": {"visit_id": "就诊ID可空"}},
            "get_recipe_detail": {"desc": "处方详情（药品清单）", "keywords": ["处方详情", "药品清单", "吃什么药"], "need_login": True, "params": {"recipe_id": "处方ID"}},
            "clinic_no_paid_detail": {"desc": "门诊待缴费详情", "keywords": ["缴费详情", "费用明细"], "need_login": True, "params": {"register_id": "挂号ID可空"}},
            "visit_patient_record": {"desc": "就诊病历记录", "keywords": ["病历", "病历记录", "看诊记录"], "need_login": True, "params": {"visit_id": "就诊ID"}},
            "re_clinic_schedule": {"desc": "复诊排班", "keywords": ["复诊", "复查", "复诊排班"], "need_login": True, "params": {"doctor_code": "医生代码可空"}},
            "medical_pay": {"desc": "医疗支付信息", "keywords": ["医疗支付", "支付信息", "付费"], "need_login": True, "params": {}},
            "online_depts": {"desc": "互联网科室列表（在线咨询入口）", "keywords": ["在线咨询", "互联网医院", "网上问诊", "在线问诊"], "need_login": True, "params": {}},
            "expert_cloud_depts": {"desc": "专家云诊室科室+时段", "keywords": ["专家云诊室", "云诊室", "线上专家"], "need_login": True, "params": {}},
            "online_search": {"desc": "在线搜索（医生/科室）", "keywords": ["在线搜索", "搜医生", "搜科室"], "need_login": True, "params": {"key": "关键词"}},
            "judge_revisit": {"desc": "复诊判断（凭身份证）", "keywords": ["复诊判断", "能不能复诊", "是否复诊"], "need_login": True, "params": {"id_card": "身份证号"}},
            "online_doctor_schedule": {"desc": "在线医生排班", "keywords": ["在线医生", "网上排班", "在线出诊"], "need_login": True, "params": {"doctor_code": "医生代码可空"}},
        },
    },

    "tuniu": {
        "name": "途牛（官方 MCP + 官网）",
        "aliases": ["途牛", "途牛旅游", "途牛火车票", "途牛机票", "途牛酒店", "途牛门票", "买票", "订票", "购票"],
        "class": TuniuAPI,
        "flow": [
            {"step": 1, "title": "① 查票（火车/机票/酒店/门票）", "methods": ["search_train", "search_flight", "search_hotel", "search_ticket"]},
            {"step": 2, "title": "② 车次详情（下单前取 resId）", "methods": ["train_detail"]},
            {"step": 3, "title": "③ 列可用工具", "methods": ["list_tools"]},
            {"step": 4, "title": "④ 下单（⚠️真购买须确认）", "methods": ["book_train", "book_train_auto", "create_flight_order", "cancel_order"]},
        ],
        "methods": {
            "list_tools": {"desc": "列出某分类可用工具（flight/train/hotel/ticket/cruise/holiday）", "keywords": ["工具", "可用功能"], "need_login": False, "params": {"category": "分类，默认 train"}},
            "search_train": {"desc": "火车票搜索（南京→北京 日期 → 车次+票价+余票）", "keywords": ["火车票", "高铁", "动车", "车次", "查火车", "买火车票"], "need_login": False, "params": {"departure": "出发城市", "arrival": "到达城市", "date": "YYYY-MM-DD"}},
            "train_detail": {"desc": "车次详情（站点/时刻/席位 seatInfo→resId，下单需要）", "keywords": ["车次详情", "时刻表", "站点", "途经站"], "need_login": False, "params": {"train_num": "车次号", "date": "YYYY-MM-DD"}},
            "search_flight": {"desc": "机票搜索 → 航班列表（低价）", "keywords": ["机票", "航班", "飞机", "打折机票", "坐飞机"], "need_login": False, "params": {"departure": "出发城市", "arrival": "到达城市", "date": "YYYY-MM-DD"}},
            "search_hotel": {"desc": "酒店搜索 → 酒店列表", "keywords": ["酒店", "宾馆", "住宿", "订房", "开房"], "need_login": False, "params": {"city": "城市", "check_in": "入住日期", "check_out": "离店日期"}},
            "search_ticket": {"desc": "景点门票查询", "keywords": ["门票", "景点", "景区", "门票价格"], "need_login": False, "params": {"scenic_name": "景点名"}},
            "book_train": {"desc": "预订火车票 ⚠️真购买（支付走途牛，须确认；需先绑 12306）", "keywords": ["订火车票", "买火车票", "下单", "预订"], "need_login": True, "params": {"resources": "[{resourceId,adultPrice,departsDate}]", "adultTourists": "[{name,psptId,psptType,tel}]", "contact": "{tel}"}},
            "book_train_auto": {"desc": "一键订票：给出发/到达/日期/车次/席别 → 自动组装 ⚠️真购买", "keywords": ["一键订票", "帮我买票", "订票", "买票"], "need_login": True, "params": {"departure": "出发", "arrival": "到达", "date": "日期", "train_num": "车次", "seat_name": "席别", "passengers": "旅客列表", "contact_tel": "联系人手机"}},
            "create_flight_order": {"desc": "创建机票订单 ⚠️真购买", "keywords": ["订机票", "买机票", "机票订单"], "need_login": True, "params": {}},
            "cancel_order": {"desc": "取消未支付订单", "keywords": ["取消订单", "退票", "取消"], "need_login": True, "params": {"category": "分类"}},
        },
        "web_class": "TuniuWebAPI",  # 官网版：查车次/下单（见 web_* 方法）
        "web_methods": {
            "web_search_train": {"desc": "官网查车次（含 trainId/resId/seat/price，下单基础数据）", "need_login": True, "params": {"departure": "出发城市", "arrival": "到达城市", "date": "YYYY-MM-DD"}},
            "web_get_travellers": {"desc": "12306实名乘客列表（下单用 touristList）", "need_login": True, "params": {}},
            "web_add_order": {"desc": "提交火车票订单 ⚠️真购买（AddOrder，需 sessionId）", "need_login": True, "params": {"order": "订单参数字典（车次/席位/乘客/ministryRailwaysId等）"}},
            "web_order_detail": {"desc": "订单详情（状态/金额）", "need_login": True, "params": {"order_id": "订单号"}},
            "web_cancel_order": {"desc": "取消订单 ⚠️真实取消（newCancelOrder）", "need_login": True, "params": {"order_id": "订单号"}},
            "web_contacts": {"desc": "联系人列表（contacts）", "need_login": True, "params": {}},
            "web_coupons": {"desc": "我的火车票优惠券（getMyCoupons）", "need_login": True, "params": {}},
            "web_calendar": {"desc": "车次日历（看哪天有票）", "need_login": True, "params": {"departure": "出发城市", "arrival": "到达城市", "date": "YYYY-MM-DD"}},
        },
    },
}

_instances: dict[str, object] = {}
_web_instances: dict[str, object] = {}


def _get_instance(platform: str):
    if platform not in _instances:
        _instances[platform] = ADAPTERS[platform]["class"]()
    return _instances[platform]


def _get_web_instance(platform: str):
    """web 方法实例：用注册表里的 web_class（如 TuniuWebAPI）。"""
    if platform not in _web_instances:
        cls_name = ADAPTERS[platform].get("web_class")
        if not cls_name:
            return None
        cls = globals().get(cls_name)
        _web_instances[platform] = cls() if cls else None
    return _web_instances[platform]


def list_skills() -> list[dict]:
    """skill_list：所有 skill（平台逆向 API）及其能力（含分层 flow 索引）。"""
    out = []
    for platform, cfg in ADAPTERS.items():
        methods = [{"name": m, **info} for m, info in cfg["methods"].items()]
        if cfg.get("web_methods"):
            methods += [{"name": m, **info} for m, info in cfg["web_methods"].items()]
        out.append({
            "skill": platform,
            "name": cfg["name"],
            "flow": cfg.get("flow", []),   # 分层业务地图（先看这个，按步骤走）
            "methods": methods,
        })
    return out


def run(skill: str, method: str, params: dict | None = None) -> dict:
    """skill_run：执行 skill（调平台逆向 API 方法），返回统一 dict {ok, data/error}。
    web_* 前缀方法走 web_class（如途牛官网 TuniuWebAPI）。"""
    cfg = ADAPTERS.get(skill or "")
    if not cfg:
        return {"ok": False, "error": f"skill 不存在：{skill or '空'}"}
    is_web = str(method or "").startswith("web_") and cfg.get("web_methods")
    methods_map = cfg["web_methods"] if is_web else cfg["methods"]
    if method not in methods_map:
        return {"ok": False, "error": f"skill {skill} 无方法：{method}"}
    try:
        inst = _get_web_instance(skill) if is_web else _get_instance(skill)
        fn = getattr(inst, method)
        data = fn(**(params or {}))
        return {"ok": True, "skill": skill, "method": method, "data": data}
    except Exception as e:
        return {"ok": False, "error": f"{skill}.{method} 异常：{e}"}
