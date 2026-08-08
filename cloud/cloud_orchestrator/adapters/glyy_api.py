"""
南京鼓楼医院互联网医院 · AI 可读 API（Device-as-Proxy，仅手机通道版）。

数据来源：电脑微信小程序真实抓包 + 小程序代码逆向（appid wx74a991a2ae77468d）。
链路已验证：token 有效、查科室 533 个、排班/时段/挂号请求体完整破解。

后端：
  域名: https://www.ih.njglyy.com:9532/caring/api
  签名: sign = SHA1(MD5(appKey + timestamp + nonce))，appKey=1340patient
  认证: 公开接口 Basic；登录后带 Authorization: Bearer <access_token>
  UA  : 必须用微信手机 UA，否则服务器挂起

Device-as-Proxy（docs/改造方案_DeviceAsProxy.md 第 2/3 条）：
  - 云端 = 大脑：组装参数、生成「请求蓝图」、解析响应、编排组合方法；
  - 手机 = 手：经 executor（= bridge.send_skill_request 下发 skill_request）执行蓝图，
    手机真实 IP 直连平台，回传原始响应 skill_result；
  - 蓝图占位符（手机 SkillExecutor 按 sign_type 本地替换）：
      {{timestamp}} 毫秒时间戳 / {{nonce}} 随机32位 / {{sign}} 签名 / {{token}} 本地凭据
  - ⚠️ 2026-08-06 已删除「云端直发降级」：未注入 executor 直接报错，不再云端直连。
    保证出问题一定定位在手机执行链路（铁律：glyy 禁云端直连）。

登录态：
  - 通过本文件 login() 方法（图形验证码+短信验证码，手机通道）获取 access_token
  - 第 4 条：登录态迁移手机本地凭据库（Android Keystore / iOS Keychain），云端不持有

方法按功能分五类（方便阅读）：
  A 登录：   get_graphical_captcha / send_sms / login
  B 查号源： list_depts / list_doctors / get_available_dates / get_schedule /
             online_depts / expert_cloud_depts / online_search /
             online_doctor_schedule / re_clinic_schedule / judge_revisit
  C 挂号：   register / book（⚠️ 真挂号，须用户确认）
  D 我的就诊：get_patient / list_orders / cancel_reservation / visit_records /
             list_reports / clinic_no_paid
  E 病历/处方/缴费：get_recipe / get_recipe_detail / clinic_no_paid_detail /
             visit_patient_record / medical_pay
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse

logger = logging.getLogger("xiami.glyy")

BASE = "https://www.ih.njglyy.com:9532/caring/api"
APP_KEY = "1340patient"
TENANT = "1340"
ROLE = "patient"
BASIC_SMS = "Basic c21zOnNtc3NlY3JldA=="          # sms:smssecret（发短信/验证码用）
BASIC_HOSPITAL = "Basic aG9zcGl0YWw6aG9zcGl0YWwtc2VjcmV0"  # hospital:hospital-secret（公开接口）
UA_WX = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38(0x18002623) "
         "NetType/WIFI Language/zh_CN")
REFERER = "https://servicewechat.com/wx74a991a2ae77468d/330/page-frame.html"

# 挂号固定参数（抓包实测）
RES_SRC = 801          # 来源
BUSINESS_TYPE_EXPERT = 2   # 专家号
BUSINESS_TYPE_NORMAL = 1   # 普通号
SOURCE = "wx_tinyapp"

# ── 蓝图占位符（手机 SkillExecutor 本地替换，第 6 条实现）──
PH_TS = "{{timestamp}}"
PH_NONCE = "{{nonce}}"
PH_SIGN = "{{sign}}"
PH_TOKEN = "{{token}}"


class GlyyAPI:
    def __init__(self, token: str | None = None, executor=None) -> None:
        # 手机通道执行函数（async (blueprint) -> {ok,status,headers,body,error}）
        # 由 registry.run 注入（绑定 bridge.send_skill_request）；必须注入，否则报错
        self.token = token or ""
        self.executor = executor

    # ═══════════════════════════ 0. 蓝图生成与底层请求 ═══════════════════════════

    # 单请求方法映射：method -> (path_template, http_method, 需要bearer)
    _REQUEST_MAP: dict[str, tuple] = {
        # B 查号源（公开）
        "list_depts": ("/public/dept", "GET", False),
        "list_doctors": ("/public/schedule/dept/doctor/{dept_code}", "GET", False),
        "get_available_dates": ("/public/v3/schedule/dept/{dept_code}/check", "GET", False),
        "get_schedule": ("/public/v3/schedule/dept/{dept_code}", "GET", False),
        "online_depts": ("/public/expert/dept", "GET", False),
        "expert_cloud_depts": ("/public/expert/cloud/dept", "GET", False),
        "online_search": ("/public/search/online", "GET", False),
        "judge_revisit": ("/public/online/judgeRevisit", "GET", False),
        "online_doctor_schedule": ("/public/schedule/doctor/online", "GET", False),
        "re_clinic_schedule": ("/public/re_clinic/getScheduleByDocId", "GET", True),
        # D 我的就诊（需登录）
        "list_orders": ("/public/orders", "GET", True),
        "cancel_reservation": ("/public/v3/reservation/cancel", "POST", True),
        "list_reports": ("/public/report/{kind}", "GET", True),
        "clinic_no_paid": ("/public/clinic/no_paid", "GET", True),
        "visit_records": ("/public/visit/record", "POST", True),
        # E 病历/处方/缴费（需登录）
        "get_recipe": ("/public/trans/visRecipe/findRecipeByVisitId", "GET", True),
        "get_recipe_detail": ("/public/trans/visRecipe/getRecipeDetail", "GET", True),
        "clinic_no_paid_detail": ("/public/clinic/no_paid_detail", "GET", True),
        "visit_patient_record": ("/public/trans/visPatientRecord/findByVisitId", "GET", True),
        "medical_pay": ("/public/order/medical_pay", "GET", True),
        # C 挂号（需登录，⚠️ 真挂号）
        "register": ("/public/v3/register", "POST", True),
    }

    def _blueprint(self, path: str, params: dict | None = None, body: dict | None = None,
                   bearer: bool = True, method: str = "GET") -> dict:
        """生成可在手机端执行的请求蓝图（sign 等由手机本地按 sign_type 计算）。"""
        headers = {
            "User-Agent": UA_WX, "appKey": APP_KEY, "role": ROLE, "tenant": TENANT,
            "timestamp": PH_TS, "nonce": PH_NONCE, "sign": PH_SIGN,
            "Content-Type": "application/json", "Accept": "*/*", "Referer": REFERER,
        }
        if bearer:
            headers["Authorization"] = "Bearer " + PH_TOKEN
        url = BASE + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        bp = {
            "skill": "glyy",
            "request": {
                "method": method, "url": url, "headers": headers,
                "body": body, "sign_type": "glyy_sha1_md5",
            },
            "credential": {"kind": "bearer" if bearer else "none", "target": "glyy"},
        }
        # 需要登录的请求：手机端发现 token 快过期时自动用 refresh_token 静默续期（第 4 条扩展）
        if bearer:
            bp["auto_refresh"] = True
        return bp

    def describe_request(self, method: str, **params) -> dict | None:
        """第 3 条：返回方法对应的请求蓝图（供第 2 条下发手机）。

        单请求方法 → 完整蓝图；复合方法（login/get_patient/book…）→ None（云端编排）。
        """
        m = self._REQUEST_MAP.get(method)
        if not m:
            return None
        path_t, http, bearer = m
        p = dict(params or {})
        try:
            path = path_t.format(**p)
        except KeyError:
            return None
        # 已用于路径的参数从 query 中剔除
        q = {k: v for k, v in p.items() if ("{" + k + "}") not in path_t}
        if http == "POST":
            return self._blueprint(path, body=q or None, bearer=bearer, method="POST")
        return self._blueprint(path, params=q or None, bearer=bearer, method="GET")

    def parse_response(self, method: str, raw_body: str) -> dict:
        """第 3 条：云端解析手机回传的原始响应为结构化数据（对齐原方法返回）。"""
        try:
            j = json.loads(raw_body or "{}")
        except Exception:
            return {"ok": False, "error": "响应非 JSON", "raw": (raw_body or "")[:300]}
        return {"ok": self.ok(j), "code": j.get("code"), "data": j.get("data"),
                "message": j.get("message") or j.get("dev_message")}

    def _parse_text(self, text: str) -> dict:
        try:
            return json.loads(text)
        except Exception:
            return {"http": -1, "raw": text[:300]}

    async def _exec(self, bp: dict, timeout: int = 25, retries: int = 3) -> dict:
        """经手机执行通道执行蓝图（bridge.send_skill_request → skill_result）。"""
        last = None
        for i in range(retries):
            try:
                res = await self.executor(bp)
                if not isinstance(res, dict):
                    return {"ok": False, "error": "手机执行返回异常"}
                if not res.get("ok"):
                    err = str(res.get("error") or "手机执行失败")
                    logger.warning("[glyy] 手机执行失败 status=%s error=%s url=%s",
                                   res.get("status"), err[:200], str(bp.get("request", {}).get("url", ""))[:100])
                    # 登录相关错误（缺 token / 登录态失效）→ 标记 need_login 供主代理自动登录
                    need = ("登录" in err or "token" in err.lower())
                    out = {"ok": False, "error": err, "status": res.get("status")}
                    if need:
                        out["need_login"] = True
                    return out
                body = str(res.get("body") or "")
                logger.info("[glyy] 手机执行成功 status=%s body前250=%s",
                            res.get("status"), body[:250])
                parsed = self._parse_text(body)
                # 登录态失效/未登录 → 标记 need_login（供主代理自动触发登录）
                if isinstance(parsed, dict):
                    msg = str(parsed.get("message") or parsed.get("dev_message") or "")
                    code = parsed.get("code")
                    if (not parsed.get("code") == 0 and
                            ("token" in msg.lower() or "login" in msg.lower()
                             or "未登录" in msg or code in (30007, 401, 403))):
                        return {"ok": False, "need_login": True,
                                "error": "登录态失效或未登录，请重新登录",
                                "status": res.get("status")}
                return parsed
            except Exception as e:
                last = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}", "attempt": i + 1}
                await asyncio.sleep(2 * (i + 1))
        return last

    async def _get(self, path: str, params: dict | None = None, bearer: bool = True,
                   timeout: int = 25, retries: int = 3) -> dict:
        """GET：仅走手机通道（禁云端直发）。未注入 executor 直接报错。"""
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, bearer=bearer, method="GET")
        return await self._exec(bp, timeout, retries)

    async def _post(self, path: str, body: dict | None = None, params: dict | None = None,
                    bearer: bool = True, timeout: int = 25, retries: int = 3) -> dict:
        """POST：仅走手机通道（禁云端直发）。未注入 executor 直接报错。"""
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, body=body, bearer=bearer, method="POST")
        return await self._exec(bp, timeout, retries)

    def ok(self, j: dict) -> bool:
        return isinstance(j, dict) and j.get("code") == 0

    def _out(self, j: dict, default=None):
        """统一方法返回：手机执行失败(need_login/error) → 透传错误 dict；否则 data 或 default。"""
        if isinstance(j, dict) and (j.get("error") or j.get("need_login")):
            return j
        if self.ok(j):
            d = j.get("data")
            return d if d is not None else default
        return default

    # ═══════════════════════════ A. 登录（验证码真人配合） ═══════════════════════════
    # 铁律（用户 2026-08-06）：glyy 一切请求走手机通道（云端组装蓝图 → 手机直连 →
    # 回传 skill_result → 云端解析）。已删除云端直发降级，未注入 executor 直接报错。

    def _sms_blueprint(self, path: str, params: dict | None = None) -> dict:
        """图形验证码/发短信共用蓝图（Basic sms，无需登录态）。"""
        headers = {
            "User-Agent": UA_WX, "Authorization": BASIC_SMS,
            "appKey": APP_KEY, "role": ROLE, "tenant": TENANT,
            "timestamp": PH_TS, "nonce": PH_NONCE, "sign": PH_SIGN,
            "Content-Type": "application/json", "Accept": "*/*",
            "Referer": REFERER,
        }
        url = BASE + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return {
            "skill": "glyy",
            "request": {"method": "POST", "url": url, "headers": headers,
                        "body": None, "sign_type": "glyy_sha1_md5"},
            "credential": {"kind": "none", "target": "glyy"},
        }

    async def get_graphical_captcha(self, phone: str) -> dict:
        """步骤1：POST /sms/captcha?phone= → 图形验证码 base64（手机通道回传 → App 显示）。"""
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        import base64
        res = await self.executor(self._sms_blueprint("/sms/captcha", {"phone": phone}))
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                    "status": res.get("status")}
        j = self._parse_text(str(res.get("body") or ""))
        data = (j.get("data") or "") if isinstance(j, dict) else ""
        if isinstance(data, str) and data.startswith("data:image"):
            try:
                with open("/tmp/glyy_captcha.png", "wb") as f:
                    f.write(base64.b64decode(data.split(",", 1)[1]))
            except Exception:
                pass
            return {"ok": True, "image_base64": data,
                    "captcha_file": "/tmp/glyy_captcha.png"}
        msg = (j.get("message") or j.get("dev_message") or "图形验证码获取失败") if isinstance(j, dict) else "响应解析失败"
        return {"ok": False, "error": msg}

    async def send_sms(self, phone: str, gcode: str) -> dict:
        """步骤2：POST /sms?phone=&type=1&code=<图形验证码> → 给手机发短信验证码（手机通道）。"""
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        res = await self.executor(
            self._sms_blueprint("/sms", {"phone": phone, "type": "1", "code": gcode}))
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                    "status": res.get("status")}
        j = self._parse_text(str(res.get("body") or ""))
        if isinstance(j, dict) and j.get("code") == 0:
            return {"ok": True, "msg": "短信已发送"}
        msg = (j.get("message") or j.get("dev_message") or "发送短信失败") if isinstance(j, dict) else "响应解析失败"
        return {"ok": False, "error": msg, "code": (j.get("code") if isinstance(j, dict) else None)}

    async def login(self, phone: str, code: str) -> dict:
        """步骤3：POST /v4/session/phone?phone=&code=<短信验证码> + JSON body（Basic hospital）。

        token 由手机回写本地凭据库（第 4 条：云端不持有登录态）。仅走手机通道。
        """
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        headers = {
            "User-Agent": UA_WX, "Authorization": BASIC_HOSPITAL,
            "appKey": APP_KEY, "role": ROLE, "tenant": TENANT,
            "timestamp": PH_TS, "nonce": PH_NONCE, "sign": PH_SIGN,
            "Content-Type": "application/json", "Accept": "*/*",
        }
        url = (BASE + "/v4/session/phone?phone=" + urllib.parse.quote(phone)
               + "&code=" + urllib.parse.quote(code))
        bp = {
            "skill": "glyy",
            "request": {"method": "POST", "url": url, "headers": headers,
                        "body": {"phone": phone, "code": code},
                        "sign_type": "glyy_sha1_md5"},
            "credential": {"kind": "none", "target": "glyy"},
            # 登录成功 → 手机把 access_token/refresh_token/expires_in 写入本地凭据库（第 4 条）
            "store": {"kind": "token", "field": "data.access_token", "target": "glyy",
                      "extra": [
                          {"kind": "refresh_token", "field": "data.refresh_token"},
                          {"kind": "expires_in", "field": "data.expires_in"},
                      ]},
        }
        res = await self.executor(bp)
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                    "status": res.get("status")}
        j = self._parse_text(str(res.get("body") or ""))
        if j.get("code") == 0 and j.get("data"):
            return {"ok": True, "msg": "登录成功，token 已保存到手机本地凭据库"}
        return {"ok": False, "error": j.get("message") or j.get("dev_message")}

    # ═══════════════════════════ B. 查号源（公开，不用登录） ═══════════════════════════

    async def list_depts(self) -> list[dict]:
        """科室列表（533 个）→ [{dept_code, dept_name, branch_code}]。公开接口，不带 token。"""
        j = await self._get("/public/dept", bearer=False)
        return self._out(j, [])

    async def list_doctors(self, dept_code: str) -> list[dict]:
        """科室医生列表 → [{doctor_code, doctor_name, title, intro, ...}]。公开接口。"""
        j = await self._get(f"/public/schedule/dept/doctor/{dept_code}", bearer=False)
        return self._out(j, [])

    async def get_available_dates(self, dept_code: str, begin: str | None = None,
                                  end: str | None = None, business_type: int = 1) -> list[str]:
        """可约日期列表。begin/end 格式 YYYY-MM-DD（默认今天~+7天）。"""
        import datetime
        t = datetime.date.today()
        b = begin or t.isoformat()
        e = end or (t + datetime.timedelta(days=7)).isoformat()
        j = await self._get(f"/public/v3/schedule/dept/{dept_code}/check", {
            "begin_date": b, "end_date": e,
            "branch_code": "1", "business_type": business_type, "res_src": RES_SRC,
        }, bearer=False)
        return self._out(j, [])

    async def get_schedule(self, dept_code: str, date: str, business_type: int = 1,
                           schedule_type: int = 1, type_: int = 0) -> dict:
        """某科室某天排班 → {normal:[...], expert:[...]}，每条含 schedule_id + detail(时段)。

        business_type: 1=普通号 2=专家号；schedule_type: 1=普通 2=专家。
        detail 每条: {time_part, schedule_num_id, remaining_num, is_enable}。
        """
        j = await self._get(f"/public/v3/schedule/dept/{dept_code}", {
            "begin_date": date, "end_date": date,
            "schedule_type": schedule_type, "type": type_,
            "branch_code": "1", "need_detail": "true",
            "business_type": business_type, "res_src": RES_SRC,
        }, bearer=False)
        return self._out(j, {})

    async def online_depts(self) -> list:
        """互联网科室列表（/public/expert/dept）→ [{id, code, name, intro}]。"""
        j = await self._get("/public/expert/dept")
        return self._out(j, [])

    async def expert_cloud_depts(self) -> dict:
        """专家云诊室科室+时段（/public/expert/cloud/dept）→ {cloudDeptList, cloudTimes}。"""
        j = await self._get("/public/expert/cloud/dept")
        return self._out(j, {})

    async def online_search(self, key: str) -> list:
        """在线搜索（/public/search/online?key=）→ 医生/科室。"""
        j = await self._get("/public/search/online", {"key": key})
        return self._out(j, [])

    async def judge_revisit(self, id_card: str) -> dict:
        """复诊判断（/public/online/judgeRevisit?id_card=）→ 是否可复诊/在线。"""
        j = await self._get("/public/online/judgeRevisit", {"id_card": id_card})
        return self._out(j, {})

    async def online_doctor_schedule(self, doctor_code: str = "", **params) -> dict:
        """在线医生排班（/public/schedule/doctor/online）。"""
        if doctor_code:
            params.setdefault("doctorCode", doctor_code)
        j = await self._get("/public/schedule/doctor/online", params)
        return self._out(j, {})

    async def re_clinic_schedule(self, doctor_code: str = "") -> list:
        """复诊排班（/public/re_clinic/getScheduleByDocId）。"""
        j = await self._get("/public/re_clinic/getScheduleByDocId", {"doctorCode": doctor_code} if doctor_code else {})
        return self._out(j, [])

    # ═══════════════════════════ C. 挂号（需登录，⚠️ 真挂号） ═══════════════════════════

    async def register(self, dept_code: str, dept_name: str, doctor_code: str,
                       doctor_name: str, appointment_time: str, noon_code: str,
                       schedule_id: str, schedule_num_id: str, start_hour: str,
                       reg_type: str, reg_name: str, res_title_code: str,
                       res_title_name: str, reg_fee: str, business_type: int,
                       patient: dict, open_id: str = "") -> dict:
        """提交挂号（对齐抓包真实请求体）。

        参数来自：get_schedule 的排班条目（schedule_id/reg_type/...）+
        detail 时段（schedule_num_id/time_part）+ get_patient()（id_card/patient_name）。
        """
        body = {
            "appointment_time": appointment_time,
            "cost": str(int(float(reg_fee) * 100)),
            "dept_code": dept_code,
            "dept_name": dept_name,
            "doctor_code": doctor_code,
            "doctor_name": doctor_name,
            "id_card": patient.get("id_card") or "",
            "mcard_no": patient.get("mcard_no") or "",
            "noon_code": noon_code,
            "patient_code": "",
            "patient_name": patient.get("patient_name") or patient.get("name") or "",
            "pay_channel": "offline",
            "source": SOURCE,
            "open_id": open_id,
            "front_url": "/package/pages/common/pay?url=",
            "re_clinic_id": 0,
            "reg_type": reg_type,
            "reg_name": reg_name,
            "register_level_name": reg_name,
            "schedule_id": schedule_id,
            "schedule_num_id": schedule_num_id,
            "res_title_code": res_title_code,
            "res_title_name": res_title_name,
            "business_type": business_type,
            "start_hour": start_hour,
            "type": 1 if business_type == 2 else 0,
            "oc_token": "",
            "pay_auth_no": "",
            "insu_type": "",
            "res_src": RES_SRC,
        }
        j = await self._post("/public/v3/register", body=body)
        # 第 5 条：挂号支付链接（如有）→ pay_url，App 跳系统浏览器完成支付（App 内零收款）
        if isinstance(j, dict) and j.get("code") == 0:
            d = j.get("data")
            if isinstance(d, dict):
                pay_url = str(d.get("pay_url") or d.get("payUrl") or "")
                if pay_url:
                    return {**j, "pay_url": pay_url}
        return j

    async def book(self, dept_code: str = "", dept_name: str = "", doctor_code: str = "",
                   date: str | None = None, business_type: int = 2,
                   id_card: str = "", open_id: str = "") -> dict:
        """一键挂号：给科室(代码或名称)+医生(可选)+日期(可选) → 自动查排班选可约时段提交。

        ⚠️ 真挂号有副作用，调用前须用户确认。返回服务器原始响应。
        若 doctor_code 为空 → 取该科室第一个可约排班；business_type 2=专家号 1=普通号。
        """
        import datetime
        # 1. 定位科室
        dept = None
        if dept_code:
            dept = {"dept_code": dept_code, "dept_name": dept_name}
        else:
            for d in await self.list_depts():
                if dept_name and dept_name in d.get("dept_name", ""):
                    dept = d
                    break
            if not dept:
                return {"ok": False, "error": "未找到科室"}
        dc, dn = dept["dept_code"], dept["dept_name"]
        # 2. 患者信息
        pat = await self.get_patient()
        if id_card:
            pat["id_card"] = id_card
        # 3. 找可约排班（未来 7 天）
        t = datetime.date.today()
        start = date or t.isoformat()
        for offset in range(0, 8):
            d = (datetime.date.fromisoformat(start) + datetime.timedelta(days=offset)).isoformat()
            st = 2 if business_type == 2 else 1
            ty = 1 if business_type == 2 else 0
            sch = await self.get_schedule(dc, d, business_type=business_type,
                                          schedule_type=st, type_=ty)
            sec = "expert" if business_type == 2 else "normal"
            for item in (sch.get(sec) or []):
                if doctor_code and item.get("doctor_code") != doctor_code:
                    continue
                slots = [s for s in (item.get("detail") or []) if s.get("is_enable") == 1]
                if not slots:
                    continue
                doctor = item.get("doctor") or {}
                j = await self.register(
                    dept_code=dc, dept_name=dn,
                    doctor_code=item.get("doctor_code") or doctor.get("doctor_code") or "",
                    doctor_name=doctor.get("doctor_name") or "",
                    appointment_time=d,
                    noon_code=item.get("noon_code") or "上午",
                    schedule_id=item.get("schedule_id"),
                    schedule_num_id=slots[0].get("schedule_num_id"),
                    start_hour=slots[0].get("time_part"),
                    reg_type=item.get("reg_type") or str(business_type),
                    reg_name=item.get("reg_name") or ("专家号" if business_type == 2 else "普通号"),
                    res_title_code=item.get("res_title_code") or "02",
                    res_title_name=item.get("res_title_name") or "副主任",
                    reg_fee=item.get("reg_fee") or "0",
                    business_type=business_type,
                    patient=pat, open_id=open_id,
                )
                return {"ok": True, "date": d, "dept": dn, "slot": slots[0],
                        "response": j}
        return {"ok": False, "error": "未来7天无该条件可约时段（可能已满）"}

    # ═══════════════════════════ D. 我的就诊（需登录） ═══════════════════════════

    async def get_patient(self) -> dict:
        """患者信息 → 合并 /public/patient/identity + /user/patient/all。

        返回含 name/patient_code/id_card（可能脱敏）/phone/birthday 的字典。
        注：id_card 接口返回脱敏（如 320111*********016）；完整号可从抓包/实名绑定获取。
        """
        out: dict = {}
        try:
            j = await self._get("/public/patient/identity")
            if self.ok(j) and isinstance(j.get("data"), dict):
                out.update(j["data"])
        except Exception:
            pass
        try:
            j = await self._get("/user/patient/all")
            if self.ok(j) and isinstance(j.get("data"), list) and j["data"]:
                p = j["data"][0]
                out.setdefault("patient_name", p.get("name"))
                out.setdefault("phone", p.get("phone"))
                out.setdefault("birthday", p.get("birthday"))
                out.setdefault("patient_id", p.get("id"))
                out.setdefault("mcard_no", p.get("medical_card") or "")
        except Exception:
            pass
        out.setdefault("patient_name", out.get("name") or "")
        return out

    async def list_orders(self, page: int = 0, size: int = 10) -> list[dict]:
        """我的预约/订单列表。"""
        j = await self._get("/public/orders", {"page": page, "size": size,
                                               "start_time": "", "end_time": "", "type": ""})
        return self._out(j, [])

    async def cancel_reservation(self, schedule_id: str, **extra) -> dict:
        """取消预约（/public/v3/reservation/cancel）。"""
        params = {"schedule_id": schedule_id}
        params.update(extra)
        return await self._post("/public/v3/reservation/cancel", params=params)

    async def visit_records(self, **body) -> list:
        """就诊记录（/public/visit/record，POST）。body 可带参数。"""
        j = await self._post("/public/visit/record", body=body or {})
        return self._out(j, [])

    async def list_reports(self, start_date: str = "", end_date: str = "", kind: str = "check") -> list:
        """查报告（kind: check=检查报告 / examine=检验报告）。
        需 start_date/end_date（YYYY-MM-DD，默认近30天）。无数据返回 []。"""
        import datetime
        t = datetime.date.today()
        s = start_date or (t - datetime.timedelta(days=30)).isoformat()
        e = end_date or t.isoformat()
        j = await self._get(f"/public/report/{kind}", {"start_date": s, "end_date": e})
        return self._out(j, [])

    async def clinic_no_paid(self) -> list:
        """门诊待缴费列表（/public/clinic/no_paid）。"""
        j = await self._get("/public/clinic/no_paid")
        return self._out(j, [])

    # ═══════════════════════════ E. 病历 / 处方 / 缴费（需登录） ═══════════════════════════

    async def get_recipe(self, visit_id: str = "") -> list:
        """按就诊查处方列表（/public/trans/visRecipe/findRecipeByVisitId）。"""
        j = await self._get("/public/trans/visRecipe/findRecipeByVisitId", {"visitId": visit_id} if visit_id else {})
        return self._out(j, [])

    async def get_recipe_detail(self, recipe_id: str = "") -> list:
        """处方详情（/public/trans/visRecipe/getRecipeDetail）。"""
        j = await self._get("/public/trans/visRecipe/getRecipeDetail", {"recipeId": recipe_id} if recipe_id else {})
        return self._out(j, [])

    async def clinic_no_paid_detail(self, register_id: str = "") -> list:
        """门诊待缴费详情（/public/clinic/no_paid_detail）。"""
        j = await self._get("/public/clinic/no_paid_detail", {"registerId": register_id} if register_id else {})
        return self._out(j, [])

    async def visit_patient_record(self, visit_id: str = "") -> list:
        """就诊病历记录（/public/trans/visPatientRecord/findByVisitId）。"""
        j = await self._get("/public/trans/visPatientRecord/findByVisitId", {"visitId": visit_id} if visit_id else {})
        return self._out(j, [])

    async def medical_pay(self, **params) -> dict:
        """医疗支付信息（/public/order/medical_pay）。"""
        j = await self._get("/public/order/medical_pay", params)
        return j if isinstance(j, dict) else {"data": j}


if __name__ == "__main__":
    import sys
    import asyncio

    async def main():
        api = GlyyAPI()
        # 仅展示蓝图（真正执行需注入 executor 走手机通道，glyy 禁云端直连）
        bp = api.describe_request("list_depts")
        print("蓝图:", json.dumps(bp, ensure_ascii=False)[:300])
        if not api.executor:
            print("[提示] 未注入 executor，不执行真实请求（glyy 禁云端直连，仅展示蓝图）")

    asyncio.run(main())
