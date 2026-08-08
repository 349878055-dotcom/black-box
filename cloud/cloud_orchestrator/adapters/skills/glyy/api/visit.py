"""glyy · 挂号 + 我的就诊 + 病历/缴费模块（需登录）。

C 挂号：register（提交挂号 ⚠️真挂号）/ book（一键挂号）
D 我的就诊：get_patient / list_orders / cancel_reservation / visit_records / list_reports / clinic_no_paid
E 病历/处方/缴费：get_recipe / get_recipe_detail / clinic_no_paid_detail / visit_patient_record / medical_pay
"""
from __future__ import annotations

import datetime

from ._base import RES_SRC, SOURCE


class RegisterMixin:
    """挂号 + 就诊/病历（需登录）。需 self._get / self._post / self.ok / self._out / self.list_depts / self.get_schedule / self.get_patient。"""

    # ═════════════ C. 挂号（需登录，⚠️ 真挂号）═════════════

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

    # ═════════════ D. 我的就诊（需登录）═════════════

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
        t = datetime.date.today()
        s = start_date or (t - datetime.timedelta(days=30)).isoformat()
        e = end_date or t.isoformat()
        j = await self._get(f"/public/report/{kind}", {"start_date": s, "end_date": e})
        return self._out(j, [])

    async def clinic_no_paid(self) -> list:
        """门诊待缴费列表（/public/clinic/no_paid）。"""
        j = await self._get("/public/clinic/no_paid")
        return self._out(j, [])

    # ═════════════ E. 病历 / 处方 / 缴费（需登录）═════════════

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
