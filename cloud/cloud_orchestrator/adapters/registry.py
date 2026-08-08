"""
skill 注册表（平台逆向 API）— 主代理 skill_list / skill_run 的依据。

本仓库只「消费 skill」：每个 skill = 一个平台逆向 API（*_api.py 类，
requests 直调 HTTP 接口，返回结构化 dict/list，AI 可直接读）。
skill 的「制作」由专门项目（Skill工作台）负责，这里只注册 + 执行。
适配器实例全局保持（session 登录态不丢）。

2026-08-06 更新：
- 新增 glyy（南京鼓楼医院互联网医院，26 方法）
- tuniu 增加官网版 web_* 方法（TuniuWebAPI：查车次/下单/订单/取消）

2026-08-xx 更新：
- 删除 tuniu 微信小程序 m-p 下单通道（loginWithPhone 需微信授权 710003，无法代下单）；
  保留官方 MCP 查询（查票/详情/航班/酒店/门票，capability=query），待用 m.tuniu.com H5 重建
"""
from __future__ import annotations

import logging

from .tuniu_api import TuniuAPI
from .glyy_api import GlyyAPI

logger = logging.getLogger("xiami.registry")

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
        "name": "途牛（查：MCP 查询；买：M 站下单+支付）",
        "aliases": ["途牛", "途牛旅游", "途牛火车票", "途牛机票", "途牛酒店", "途牛门票", "买票", "订票", "购票"],
        # ── 能力边界（Skill工作台方法论 §1.55 / §1.1a，制作第 0 步探测）──
        # 查：MCP apiKey，无需登录 ✅
        # 买：M 站 m.tuniu.com 接口直调（AddOrder），需登录 cookie；登录 = passport.tuniu.com 手机号+短信
        #     + 腾讯滑块（⚠️滑块必现、不可跳过，只能真人网页拖拽；手机聊天验证码引擎无法完成）→ 真人登录一次存 cookie 复用；
        #     乘客直传 touristList 免网页"添加乘客"弹窗 ✅（2026-08-07 实测下单成功）
        # 支付：手机支付宝/途牛 App 完成（电脑无支付宝客户端付不了）⚠️ 真人确认
        # 已删除：微信小程序 m-p 通道（loginWithPhone 需微信授权 710003，无法代下单）
        "capability": "operate",
        "capability_note": "查票（MCP 免登录）；下单（M 站，需登录 cookie，乘客直传 touristList）；支付在手机支付宝/途牛 App 完成（需真人确认）",
        "class": TuniuAPI,
        "flow": [
            {"step": 1, "title": "① 查车次/机票/酒店/门票（MCP，免费）", "methods": ["search_train", "search_flight", "search_hotel", "search_ticket"]},
            {"step": 2, "title": "② 车次详情（MCP）", "methods": ["train_detail"]},
            {"step": 3, "title": "③ 下单创建订单（M站，乘客直传 touristList）⚠️真购票", "methods": ["submit_order"]},
            {"step": 4, "title": "④ 支付（内置浏览器打开订单页/收银台，手机支付宝/途牛 App 完成）", "methods": ["pay"]},
            {"step": 5, "title": "⑤ 订单列表/订单详情/出票状态（M站）", "methods": ["order_list", "order_detail"]},
            {"step": 6, "title": "⑥ 退票/取消订单（M站）⚠️真实退票", "methods": ["cancel_order"]},
        ],
        # ── 登录：M 站登录 = passport.tuniu.com 手机号+短信+腾讯滑块（⚠️滑块必现不可跳过，只能真人网页拖）──
        # 登录态 = cookie（isLogined/ssoUser/muser/TUNIUmuser/tuniuuser_id），由 App 内置浏览器真人配合登录后
        # export_cookies 存手机凭据库（CredentialStore "tuniu"）；蓝图 credential=kind:cookie 由手机自动补 Cookie 头。
        # 不配 sms_verify login（滑块必现、引擎无滑块步骤）→ agent._ensure_login("tuniu") 引导网页登录。
        "methods": {
            "list_tools": {"desc": "列出某分类可用工具（flight/train/hotel/ticket/cruise/holiday）", "keywords": ["工具", "可用功能"], "need_login": False, "params": {"category": "分类，默认 train"}, "success_ret": "工具列表 [{name,desc}]", "error_ret": ""},
            "search_train": {"desc": "火车票搜索（MCP，免费，仅查询）→ 车次+票价+余票", "keywords": ["火车票", "高铁", "动车", "车次", "查火车", "买火车票"], "need_login": False, "params": {"departure": "出发城市", "arrival": "到达城市", "date": "YYYY-MM-DD"}, "success_ret": "{ok, trains:[{trainNum,departureTime,arrivalTime,seat:{seatName,price,leftNumber}}]}", "error_ret": "{ok:false, error}"},
            "train_detail": {"desc": "车次详情（MCP，站点/时刻/席位；需带出发/到达城市名）", "keywords": ["车次详情", "时刻表", "站点", "途经站"], "need_login": False, "params": {"train_num": "车次号", "date": "YYYY-MM-DD", "departure": "出发城市（可选）", "arrival": "到达城市（可选）"}, "success_ret": "{ok, train:{trainNum,stations,seats}}", "error_ret": "{ok:false, error}"},
            "search_flight": {"desc": "机票搜索（MCP）→ 航班列表（低价）", "keywords": ["机票", "航班", "飞机", "打折机票", "坐飞机"], "need_login": False, "params": {"departure": "出发城市", "arrival": "到达城市", "date": "YYYY-MM-DD"}, "success_ret": "{ok, flights:[]}", "error_ret": "{ok:false, error}"},
            "search_hotel": {"desc": "酒店搜索（MCP）→ 酒店列表", "keywords": ["酒店", "宾馆", "住宿", "订房", "开房"], "need_login": False, "params": {"city": "城市", "check_in": "入住日期", "check_out": "离店日期"}, "success_ret": "{ok, hotels:[]}", "error_ret": "{ok:false, error}"},
            "search_ticket": {"desc": "景点门票查询（MCP）", "keywords": ["门票", "景点", "景区", "门票价格"], "need_login": False, "params": {"scenic_name": "景点名"}, "success_ret": "{ok, tickets:[]}", "error_ret": "{ok:false, error}"},
            "set_cookies": {"desc": "设置 M 站登录 cookie（下单前调用；手机通道下由手机凭据库自动补）", "keywords": ["登录", "cookie"], "need_login": False, "params": {"cookies": "登录cookie字典"}, "success_ret": "{ok}", "error_ret": ""},
            "submit_order": {"desc": "下单创建订单（M站 AddOrder，乘客直传 touristList，免网页添加乘客弹窗）⚠️真购票", "keywords": ["买票", "下单", "订票", "购买", "买火车票"], "need_login": True, "params": {"dep": "出发城市", "arr": "到达城市", "date": "YYYY-MM-DD", "train_num": "车次", "seat_name": "席别", "passengers": "乘客数组[{name,psptId,tel,birthday,sex}]", "contact_tel": "联系人手机"}, "success_ret": "{ok, order_id, order_amount, pay_url}", "error_ret": "{ok:false, error, need_login?}（170001参数错误/179998未登录→need_login）"},
            "pay": {"desc": "支付：内置浏览器打开途牛收银台，选支付宝自动拉起支付宝 App 完成支付（alipays://，桌面弹出支付宝）", "keywords": ["支付", "付款", "付钱", "支付宝", "拉起支付宝"], "need_login": True, "params": {"order_id": "订单号", "order_type": "订单类型(默认38)"}, "success_ret": "{ok, pay_url, pay_ways:[]}", "error_ret": "{ok:false, error}"},
            "order_detail": {"desc": "订单详情（M站，状态/金额/可否支付取消；支付后确认用）", "keywords": ["订单详情", "订单状态", "查订单", "支付成功了吗"], "need_login": True, "params": {"order_id": "订单号", "order_type": "订单类型(默认38)"}, "success_ret": "{ok, order:{statusName(待出票/购票成功), orderStatusCode, payStatusName, canPay, canCancel, ticketInfo, touristsInfo, refundServiceFee}}", "error_ret": "{ok:false, error}"},
            "cancel_order": {"desc": "退票/取消订单：①未支付/占座订单 → newCancelOrder 自动退（实测成功）；②已出票订单途牛网页无自助退票（平台限制）→ 自动退不了，需告知用户打途牛客服 400-797-6666 或凭证件到火车站窗口办理（按铁路规则扣手续费）", "keywords": ["退票", "取消订单", "退", "退掉", "怎么退票", "退票入口"], "need_login": True, "params": {"order_id": "订单号", "order_type": "订单类型(默认38)"}, "success_ret": "{ok, data:{success:true}}", "error_ret": "{ok:false, error}（已出票→711001取消失败，需转客服/窗口）"},
            "order_list": {"desc": "我的火车票订单列表（M站 orderList）→ 订单号/状态/金额/乘车日期；查询票务用", "keywords": ["订单列表", "我的订单", "查询票务", "我买的票", "查订单", "订单"], "need_login": True, "params": {"page_no": "页码(默认1)", "page_size": "每页条数(默认10)"}, "success_ret": "{ok, orders:[{orderId, beginTime, productName, status, amount}]}", "error_ret": "{ok:false, error}"},
        },
    },
}

def _make_executor(device_id: str):
    """构造手机执行通道（第 2 条两段式）：async (blueprint) -> skill_result dict。

    绑定 bridge.send_skill_request：云端不再直发平台请求，
    手机真实 IP 直连平台，回传原始响应由云端 API 解析层处理。
    设备未在线 -> bridge 返回 {ok:False, error:...}，方法如实上报。
    """
    async def executor(blueprint: dict) -> dict:
        from ..channel.bridge import bridge
        return await bridge.send_skill_request(device_id, blueprint or {})
    return executor


def _get_instance(platform: str, executor=None):
    cls = ADAPTERS[platform]["class"]
    if isinstance(cls, str):
        cls = globals().get(cls)  # 兼容发布生成/手写的字符串类名
    if not cls:
        return None
    # 每次新建实例：executor 绑定设备；登录态从持久化文件/手机凭据恢复
    return cls(executor=executor) if executor else cls()


def list_skills() -> list[dict]:
    """skill_list：所有 skill（平台逆向 API）及其能力（含分层 flow 索引）。

    system_only 方法（如途牛登录 4 步）只供系统内部 _ensure_login 编排调用，
    对 LLM 不可见，避免 AI 自行调用登录方法导致流程混乱。
    """
    out = []
    for platform, cfg in ADAPTERS.items():
        methods = [{"name": m, **info} for m, info in cfg["methods"].items()
                   if not info.get("system_only")]
        out.append({
            "skill": platform,
            "name": cfg["name"],
            "flow": cfg.get("flow", []),   # 分层业务地图（先看这个，按步骤走）
            "methods": methods,
            # 能力边界（Skill工作台方法论 §1.55）：query=只能查 / operate_sms=手机号+短信能操作 / operate_wechat=需微信授权（我们 App 不能代做）
            "capability": cfg.get("capability", ""),
            "capability_note": cfg.get("capability_note", ""),
        })
    return out


async def run(skill: str, method: str, params: dict | None = None, device_id: str = "") -> dict:
    """skill_run（第 2 条两段式）：云端组装蓝图 -> 经 bridge 下发手机 -> 手机直连平台 ->
    回传 skill_result -> 云端解析成结构化数据返回（与旧直发返回一致）。

    device_id 非空 -> 平台请求全部由手机发出（云端不直发，防封机房）；
    device_id 为空 -> 传 executor=None：
        glyy 已删除云端直发降级（2026-08-06）→ 直接返回「未注入 executor」报错；
        tuniu MCP 保留原有降级（单机测试/无手机通道的 API 入口）。
    """
    cfg = ADAPTERS.get(skill or "")
    if not cfg:
        return {"ok": False, "error": f"skill 不存在：{skill or '空'}"}
    methods_map = cfg["methods"]
    if method not in methods_map:
        return {"ok": False, "error": f"skill {skill} 无方法：{method}"}
    # 第 7 条降级兜底：带 device_id（App 主代理路径）但手机离线 → 不执行也不云端直发
    if device_id:
        try:
            from ..channel.bridge import bridge
            online = bridge.online_devices()
            if not bridge.has(device_id):
                logger.warning("[registry] 手机离线拦截 skill=%s method=%s device=%s 在线=%s",
                               skill, method, device_id, online)
                return {"ok": False,
                        "error": f"手机未在线（请打开 App 保持在线），已停止执行避免云端直发",
                        "skill": skill, "method": method}
        except Exception as e:
            logger.warning("[registry] bridge 检查异常: %s", e)
    logger.info("[registry] run skill=%s method=%s device=%s", skill, method, device_id)
    try:
        executor = _make_executor(device_id) if device_id else None
        inst = _get_instance(skill, executor)
        if inst is None:
            return {"ok": False, "error": f"skill {skill} 适配器加载失败"}
        fn = getattr(inst, method)
        data = await fn(**(params or {}))
        # 登录态缺失/失效 → 返回 need_login 标记（供主代理自动触发登录）
        if isinstance(data, dict) and data.get("need_login"):
            return {"ok": False, "need_login": True, "skill": skill, "method": method,
                    "error": str(data.get("error") or "需要登录")}
        return {"ok": True, "skill": skill, "method": method, "data": data}
    except Exception as e:
        return {"ok": False, "error": f"{skill}.{method} 异常：{e}"}
