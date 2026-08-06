"""
南京鼓楼医院互联网医院 · AI 可读 API（requests 直调后端接口，无需 UI 自动化）。

数据来源：电脑微信小程序真实抓包 + 小程序代码逆向（appid wx74a991a2ae77468d）。
链路已验证：token 有效、查科室 533 个、排班/时段/挂号请求体完整破解。

后端：
  域名: https://www.ih.njglyy.com:9532/caring/api
  签名: sign = SHA1(MD5(appKey + timestamp + nonce))，appKey=1340patient
  认证: 公开接口 Basic；登录后带 Authorization: Bearer <access_token>
  UA  : 必须用微信手机 UA，否则服务器挂起

登录态：
  - 抓包拿到的真实 token 存于 /tmp/glyy_session.json（get_token()）
  - 或调用登录流程（见 glyy_session.py）生成新 token

挂号流程：
  api.list_depts()                     → 科室列表 [{dept_code, dept_name, branch_code}]
  api.list_doctors(dept_code)          → 医生列表（专家号科室）
  api.get_available_dates(dept_code)   → 可约日期列表
  api.get_schedule(dept_code, date)    → 排班 {normal:[...], expert:[...]}（含 detail 时段）
  api.get_patient()                    → 患者信息（id_card/patient_name）
  api.register(...)                    → 提交挂号（⚠️ 真挂号！谨慎调用）
  api.list_orders()                    → 我的预约订单
  api.cancel_reservation(...)          → 取消预约
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import string
import time

import requests
import urllib3

urllib3.disable_warnings()

BASE = "https://www.ih.njglyy.com:9532/caring/api"
APP_KEY = "1340patient"
TENANT = "1340"
ROLE = "patient"
UA_WX = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38(0x18002623) "
         "NetType/WIFI Language/zh_CN")
SESSION_FILE = "/tmp/glyy_session.json"
REFERER = "https://servicewechat.com/wx74a991a2ae77468d/330/page-frame.html"

# 挂号固定参数（抓包实测）
RES_SRC = 801          # 来源
BUSINESS_TYPE_EXPERT = 2   # 专家号
BUSINESS_TYPE_NORMAL = 1   # 普通号
SOURCE = "wx_tinyapp"


def _nonce() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=32))


def _sign(app_key: str, timestamp: str, nonce: str) -> str:
    md5hex = hashlib.md5((app_key + timestamp + nonce).encode()).hexdigest()
    return hashlib.sha1(md5hex.encode()).hexdigest()


def load_token() -> str:
    """从 /tmp/glyy_session.json 加载 access_token。"""
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return (json.load(f).get("access_token") or "").strip()
    return ""


class GlyyAPI:
    def __init__(self, token: str | None = None) -> None:
        self.token = token if token is not None else load_token()
        self.s = requests.Session()

    # ─────────── 登录（验证码真人配合）───────────
    def get_graphical_captcha(self, phone: str) -> dict:
        """步骤1：POST /sms/captcha?phone= → 图形验证码 base64，存 /tmp/glyy_captcha.png 给人看。"""
        import base64
        from glyy_session import BASIC_SMS, sign_headers
        r = requests.post(BASE + "/sms/captcha", params={"phone": phone},
                          headers=sign_headers(BASIC_SMS), timeout=20, verify=False)
        j = self._parse(r)
        data = (j.get("data") or "")
        if j.get("code") == 0 and isinstance(data, str) and data.startswith("data:image"):
            with open("/tmp/glyy_captcha.png", "wb") as f:
                f.write(base64.b64decode(data.split(",", 1)[1]))
            return {"ok": True, "captcha_file": "/tmp/glyy_captcha.png"}
        return {"ok": False, "error": j.get("message") or j.get("dev_message")}

    def send_sms(self, phone: str, gcode: str) -> dict:
        """步骤2：POST /sms?phone=&type=1&code=<图形验证码> → 给手机发短信验证码。"""
        from glyy_session import BASIC_SMS, sign_headers
        r = requests.post(BASE + "/sms", params={"phone": phone, "type": "1", "code": gcode},
                          headers=sign_headers(BASIC_SMS), timeout=20, verify=False)
        j = self._parse(r)
        return {"ok": j.get("code") == 0,
                "msg": "短信已发送" if j.get("code") == 0 else (j.get("message") or j.get("dev_message"))}

    def login(self, phone: str, code: str) -> dict:
        """步骤3：POST /v4/session/phone?phone=&code=<短信验证码> + JSON body（Basic hospital）→ 设 token。"""
        from glyy_session import BASIC_HOSPITAL, make_nonce, make_sign
        ts = str(int(time.time() * 1000)); nc = make_nonce()
        headers = {
            "User-Agent": UA_WX, "Authorization": BASIC_HOSPITAL,
            "appKey": APP_KEY, "role": ROLE, "tenant": TENANT,
            "timestamp": ts, "nonce": nc, "sign": make_sign(APP_KEY, ts, nc),
            "Content-Type": "application/json", "Accept": "*/*",
        }
        r = self.s.post(BASE + "/v4/session/phone", params={"phone": phone, "code": code},
                        json={"phone": phone, "code": code}, headers=headers, timeout=20, verify=False)
        j = self._parse(r)
        if j.get("code") == 0 and j.get("data"):
            data = j["data"]
            self.token = data.get("access_token") or ""
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return {"ok": True, "msg": "登录成功，token 已保存"}
        return {"ok": False, "error": j.get("message") or j.get("dev_message")}

    def _headers(self, bearer: bool = True) -> dict:
        ts = str(int(time.time() * 1000))
        nc = _nonce()
        h = {
            "User-Agent": UA_WX,
            "appKey": APP_KEY,
            "role": ROLE,
            "tenant": TENANT,
            "timestamp": ts,
            "nonce": nc,
            "sign": _sign(APP_KEY, ts, nc),
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Referer": REFERER,
        }
        if bearer and self.token:
            h["Authorization"] = "Bearer " + self.token
        return h

    def _get(self, path: str, params: dict | None = None, bearer: bool = True,
             timeout: int = 25, retries: int = 3) -> dict:
        """GET + 自动重试（服务器不稳定，超时/连接失败自动重试）。"""
        last = None
        for i in range(retries):
            try:
                r = self.s.get(BASE + path, params=params, headers=self._headers(bearer),
                               timeout=timeout, verify=False)
                return self._parse(r)
            except Exception as e:
                last = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}", "attempt": i + 1}
                time.sleep(2 * (i + 1))
        return last

    def _post(self, path: str, body: dict | None = None, params: dict | None = None,
              bearer: bool = True, timeout: int = 25, retries: int = 3) -> dict:
        last = None
        for i in range(retries):
            try:
                r = self.s.post(BASE + path, params=params, json=body,
                                headers=self._headers(bearer), timeout=timeout, verify=False)
                return self._parse(r)
            except Exception as e:
                last = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}", "attempt": i + 1}
                time.sleep(2 * (i + 1))
        return last

    def _parse(self, r: requests.Response) -> dict:
        try:
            return r.json()
        except Exception:
            return {"http": r.status_code, "raw": r.text[:300]}

    def ok(self, j: dict) -> bool:
        return isinstance(j, dict) and j.get("code") == 0

    # ─────────── 查询（登录态）───────────
    def list_depts(self) -> list[dict]:
        """科室列表（533 个）→ [{dept_code, dept_name, branch_code}]。"""
        j = self._get("/public/dept")
        return j.get("data") or [] if self.ok(j) else []

    def list_doctors(self, dept_code: str) -> list[dict]:
        """科室医生列表 → [{doctor_code, doctor_name, title, intro, ...}]。"""
        j = self._get(f"/public/schedule/dept/doctor/{dept_code}")
        return j.get("data") or [] if self.ok(j) else []

    def get_available_dates(self, dept_code: str, begin: str | None = None,
                            end: str | None = None, business_type: int = 1) -> list[str]:
        """可约日期列表。begin/end 格式 YYYY-MM-DD（默认今天~+7天）。"""
        import datetime
        t = datetime.date.today()
        b = begin or t.isoformat()
        e = end or (t + datetime.timedelta(days=7)).isoformat()
        j = self._get(f"/public/v3/schedule/dept/{dept_code}/check", {
            "begin_date": b, "end_date": e,
            "branch_code": "1", "business_type": business_type, "res_src": RES_SRC,
        })
        return j.get("data") or [] if self.ok(j) else []

    def get_schedule(self, dept_code: str, date: str, business_type: int = 1,
                     schedule_type: int = 1, type_: int = 0) -> dict:
        """某科室某天排班 → {normal:[...], expert:[...]}，每条含 schedule_id + detail(时段)。

        business_type: 1=普通号 2=专家号；schedule_type: 1=普通 2=专家。
        detail 每条: {time_part, schedule_num_id, remaining_num, is_enable}。
        """
        j = self._get(f"/public/v3/schedule/dept/{dept_code}", {
            "begin_date": date, "end_date": date,
            "schedule_type": schedule_type, "type": type_,
            "branch_code": "1", "need_detail": "true",
            "business_type": business_type, "res_src": RES_SRC,
        })
        return j.get("data") or {} if self.ok(j) else {}

    def get_patient(self) -> dict:
        """患者信息 → 合并 /public/patient/identity + /user/patient/all。

        返回含 name/patient_code/id_card（可能脱敏）/phone/birthday 的字典。
        注：id_card 接口返回脱敏（如 320111*********016）；完整号可从抓包/实名绑定获取。
        """
        out: dict = {}
        try:
            j = self._get("/public/patient/identity")
            if self.ok(j) and isinstance(j.get("data"), dict):
                out.update(j["data"])
        except Exception:
            pass
        try:
            j = self._get("/user/patient/all")
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

    def list_orders(self, page: int = 0, size: int = 10) -> list[dict]:
        """我的预约/订单列表。"""
        j = self._get("/public/orders", {"page": page, "size": size,
                                         "start_time": "", "end_time": "", "type": ""})
        return j.get("data") or [] if self.ok(j) else []

    # ─────────── 挂号（⚠️ 真挂号）───────────
    def register(self, dept_code: str, dept_name: str, doctor_code: str,
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
        return self._post("/public/v3/register", body=body)

    def cancel_reservation(self, schedule_id: str, **extra) -> dict:
        """取消预约（/public/v3/reservation/cancel）。"""
        params = {"schedule_id": schedule_id}
        params.update(extra)
        return self._post("/public/v3/reservation/cancel", params=params)

    # ─────────── 报告/缴费/病历（自动摸索补充）───────────
    def list_reports(self, start_date: str = "", end_date: str = "", kind: str = "check") -> list:
        """查报告（kind: check=检查报告 / examine=检验报告）。
        需 start_date/end_date（YYYY-MM-DD，默认近30天）。无数据返回 []。"""
        import datetime
        t = datetime.date.today()
        s = start_date or (t - datetime.timedelta(days=30)).isoformat()
        e = end_date or t.isoformat()
        j = self._get(f"/public/report/{kind}", {"start_date": s, "end_date": e})
        return j.get("data") or [] if self.ok(j) else []

    def clinic_no_paid(self) -> list:
        """门诊待缴费列表（/public/clinic/no_paid）。"""
        j = self._get("/public/clinic/no_paid")
        return j.get("data") or [] if self.ok(j) else []

    def visit_records(self, **body) -> list:
        """就诊记录（/public/visit/record，POST）。body 可带参数。"""
        j = self._post("/public/visit/record", body=body or {})
        return j.get("data") or [] if self.ok(j) else []

    # ─────────── 处方/缴费/病历/复诊（自动摸索补充2）───────────
    def get_recipe(self, visit_id: str = "") -> list:
        """按就诊查处方列表（/public/trans/visRecipe/findRecipeByVisitId）。"""
        j = self._get("/public/trans/visRecipe/findRecipeByVisitId", {"visitId": visit_id} if visit_id else {})
        return j.get("data") or [] if self.ok(j) else []

    def get_recipe_detail(self, recipe_id: str = "") -> list:
        """处方详情（/public/trans/visRecipe/getRecipeDetail）。"""
        j = self._get("/public/trans/visRecipe/getRecipeDetail", {"recipeId": recipe_id} if recipe_id else {})
        return j.get("data") or [] if self.ok(j) else []

    def clinic_no_paid_detail(self, register_id: str = "") -> list:
        """门诊待缴费详情（/public/clinic/no_paid_detail）。"""
        j = self._get("/public/clinic/no_paid_detail", {"registerId": register_id} if register_id else {})
        return j.get("data") or [] if self.ok(j) else []

    def visit_patient_record(self, visit_id: str = "") -> list:
        """就诊病历记录（/public/trans/visPatientRecord/findByVisitId）。"""
        j = self._get("/public/trans/visPatientRecord/findByVisitId", {"visitId": visit_id} if visit_id else {})
        return j.get("data") or [] if self.ok(j) else []

    def re_clinic_schedule(self, doctor_code: str = "") -> list:
        """复诊排班（/public/re_clinic/getScheduleByDocId）。"""
        j = self._get("/public/re_clinic/getScheduleByDocId", {"doctorCode": doctor_code} if doctor_code else {})
        return j.get("data") or [] if self.ok(j) else []

    def medical_pay(self, **params) -> dict:
        """医疗支付信息（/public/order/medical_pay）。"""
        j = self._get("/public/order/medical_pay", params)
        return j if isinstance(j, dict) else {"data": j}

    # ─────────── 在线咨询/互联网医院（自动摸索补充3）───────────
    def online_depts(self) -> list:
        """互联网科室列表（/public/expert/dept）→ [{id, code, name, intro}]。"""
        j = self._get("/public/expert/dept")
        return j.get("data") or [] if self.ok(j) else []

    def expert_cloud_depts(self) -> dict:
        """专家云诊室科室+时段（/public/expert/cloud/dept）→ {cloudDeptList, cloudTimes}。"""
        j = self._get("/public/expert/cloud/dept")
        return j.get("data") or {} if self.ok(j) else {}

    def online_search(self, key: str) -> list:
        """在线搜索（/public/search/online?key=）→ 医生/科室。"""
        j = self._get("/public/search/online", {"key": key})
        return j.get("data") or [] if self.ok(j) else []

    def judge_revisit(self, id_card: str) -> dict:
        """复诊判断（/public/online/judgeRevisit?id_card=）→ 是否可复诊/在线。"""
        j = self._get("/public/online/judgeRevisit", {"id_card": id_card})
        return j.get("data") or {} if self.ok(j) else {}

    def online_doctor_schedule(self, doctor_code: str = "", **params) -> dict:
        """在线医生排班（/public/schedule/doctor/online）。"""
        if doctor_code:
            params.setdefault("doctorCode", doctor_code)
        j = self._get("/public/schedule/doctor/online", params)
        return j.get("data") or {} if self.ok(j) else {}

    # ─────────── 一键挂号（高封装，给 AI 用）───────────
    def book(self, dept_code: str = "", dept_name: str = "", doctor_code: str = "",
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
            for d in self.list_depts():
                if dept_name and dept_name in d.get("dept_name", ""):
                    dept = d
                    break
            if not dept:
                return {"ok": False, "error": "未找到科室"}
        dc, dn = dept["dept_code"], dept["dept_name"]
        # 2. 患者信息
        pat = self.get_patient()
        if id_card:
            pat["id_card"] = id_card
        # 3. 找可约排班（未来 7 天）
        t = datetime.date.today()
        start = date or t.isoformat()
        for offset in range(0, 8):
            d = (datetime.date.fromisoformat(start) + datetime.timedelta(days=offset)).isoformat()
            st = 2 if business_type == 2 else 1
            ty = 1 if business_type == 2 else 0
            sch = self.get_schedule(dc, d, business_type=business_type,
                                    schedule_type=st, type_=ty)
            sec = "expert" if business_type == 2 else "normal"
            for item in (sch.get(sec) or []):
                if doctor_code and item.get("doctor_code") != doctor_code:
                    continue
                slots = [s for s in (item.get("detail") or []) if s.get("is_enable") == 1]
                if not slots:
                    continue
                doctor = item.get("doctor") or {}
                j = self.register(
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


if __name__ == "__main__":
    import sys
    api = GlyyAPI()
    print("token:", (api.token or "")[:40], "...")
    if not api.token:
        print("[error] 无 token，请先运行 glyy_session.py 登录")
        sys.exit(1)
    depts = api.list_depts()
    print(f"科室数: {len(depts)}")
    if depts:
        d = depts[0]
        print(f"示例: {d}")
