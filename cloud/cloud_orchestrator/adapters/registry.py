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
  "name": "南京鼓楼医院互联网医院",
  "class": "GlyyAPI",
  "flow": [
    {
      "step": 1,
      "title": "① 使用",
      "methods": [
        "login",
        "list_depts",
        "list_doctors",
        "get_available_dates",
        "get_schedule",
        "get_patient",
        "register",
        "list_orders"
      ]
    }
  ],
  "methods": {
    "login": {
      "desc": "手机号+短信验证码登录 → {access_token, refresh_token, ...}",
      "keywords": [
        "登录(手机验证码)"
      ],
      "examples": [
        "登录(手机验证码)"
      ],
      "need_login": False,
      "params": {
        "phone": "{phone}"
      }
    },
    "list_depts": {
      "desc": "科室列表（533个）→ [{dept_code, dept_name, branch_code}]",
      "keywords": [
        "科室",
        "医院科室",
        "有哪些科"
      ],
      "examples": [
        "鼓楼医院有哪些科室",
        "看皮肤科挂哪个科"
      ],
      "need_login": False,
      "params": {}
    },
    "list_doctors": {
      "desc": "科室医生 → [{doctor_code, doctor_name, title, intro}]",
      "keywords": [
        "医生",
        "专家",
        "大夫"
      ],
      "examples": [
        "皮肤科有哪些医生",
        "看专家号"
      ],
      "need_login": False,
      "params": {}
    },
    "get_available_dates": {
      "desc": "可预约日期列表（business_type 1=普通号 2=专家号）",
      "keywords": [
        "可约日期",
        "哪天能约",
        "放号"
      ],
      "examples": [
        "这周哪天能约",
        "什么时候放号"
      ],
      "need_login": False,
      "params": {
        "begin_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD",
        "branch_code": "1",
        "business_type": "1|2",
        "res_src": "801"
      }
    },
    "get_schedule": {
      "desc": "排班 → {normal:[...], expert:[...]}，每条含 schedule_id/reg_fee/noon_code/doctor + detail(时段数组: time_part/schedule_num_id/remaining_num/is_enable)",
      "keywords": [
        "排班",
        "出诊时间",
        "哪天有号"
      ],
      "examples": [
        "张医生这周出诊吗",
        "明天有号吗"
      ],
      "need_login": False,
      "params": {
        "begin_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD",
        "schedule_type": "1|2",
        "type": "0|1",
        "branch_code": "1",
        "need_detail": "true",
        "business_type": "1|2",
        "res_src": "801"
      }
    },
    "get_patient": {
      "desc": "患者信息 → {patient_codes, name, id_card(脱敏), phone}；另 /user/patient/all 返回完整列表",
      "keywords": [
        "我的信息",
        "就诊人",
        "患者"
      ],
      "examples": [
        "我的就诊人信息",
        "添加就诊人"
      ],
      "need_login": True,
      "params": {}
    },
    "register": {
      "desc": "提交预约（⚠️真挂号有副作用，须用户确认）",
      "keywords": [
        "挂号",
        "预约",
        "提交"
      ],
      "examples": [
        "帮我挂号",
        "预约皮肤科"
      ],
      "need_login": True,
      "params": {}
    },
    "list_orders": {
      "desc": "预约/订单列表 → [{id, order_no, state, create_time}]",
      "keywords": [
        "我的订单",
        "预约记录",
        "查订单"
      ],
      "examples": [
        "我挂的号有哪些",
        "我的预约记录"
      ],
      "need_login": True,
      "params": {
        "page": "0",
        "size": "10",
        "start_time": "",
        "end_time": "",
        "type": ""
      }
    },
    "cancel_reservation": {
      "desc": "取消预约（⚠️7天内退约次数有限制）",
      "keywords": [
        "取消预约"
      ],
      "examples": [
        "取消预约"
      ],
      "need_login": True,
      "params": {
        "schedule_id": ""
      }
    },
    "list_reports": {
      "desc": "查报告（kind=check检查/examine检验，需日期范围；无数据返回[]）",
      "keywords": [
        "检查报告",
        "检验报告",
        "报告"
      ],
      "examples": [
        "我的检查报告",
        "查检验报告"
      ],
      "need_login": True,
      "params": {
        "start_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD"
      }
    },
    "clinic_no_paid": {
      "desc": "门诊待缴费列表",
      "keywords": [
        "待缴费",
        "未缴费",
        "缴费"
      ],
      "examples": [
        "我有待缴费的吗",
        "门诊费用"
      ],
      "need_login": True,
      "params": {}
    },
    "visit_records": {
      "desc": "就诊记录（POST）",
      "keywords": [
        "就诊记录",
        "病历",
        "看过什么病"
      ],
      "examples": [
        "我的就诊记录",
        "历史病历"
      ],
      "need_login": True,
      "params": {}
    }
  }
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
        cls = ADAPTERS[platform]["class"]
        if isinstance(cls, str):
            cls = globals().get(cls)  # 兼容发布生成/手写的字符串类名
        _instances[platform] = cls() if cls else None
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
