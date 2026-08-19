"""glyy · 查号源模块（公开接口，不用登录）。

list_depts / list_doctors / get_available_dates / get_schedule / online_depts /
expert_cloud_depts / online_search / judge_revisit / online_doctor_schedule / re_clinic_schedule。
"""
from __future__ import annotations

import datetime

from ._base import RES_SRC


class QueryMixin:
    """查号源（公开，不用登录）。需 self._get / self._out。"""

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
        """某科室某天排班 → {normal:[...], expert:[...]}。

        展平结构：每个「时段」一条记录，医生字段平铺到每条记录上——
        [{schedule_id, doctor_code, doctor_name, noon_code, time_part, schedule_num_id,
          remaining_num, is_enable, reg_type, reg_name, res_title_code, res_title_name,
          reg_fee, business_type}]。
        便于 register 按「医生 + 时段」精确匹配时段编号（不再取第一个时段）。
        """
        j = await self._get(f"/public/v3/schedule/dept/{dept_code}", {
            "begin_date": date, "end_date": date,
            "schedule_type": schedule_type, "type": type_,
            "branch_code": "1", "need_detail": "true",
            "business_type": business_type, "res_src": RES_SRC,
        }, bearer=False)
        return self._flatten_schedule(self._out(j, {}))

    @staticmethod
    def _flatten_schedule(data) -> dict:
        """把 {normal/expert:[{...,doctor:{...},detail:[{time_part,schedule_num_id,...}]}]}
        展平成 {normal/expert:[时段记录]}，doctor/detail 字段平铺到每条时段记录。"""
        if not isinstance(data, dict):
            return data
        out: dict = {}
        for key in ("normal", "expert"):
            rows = data.get(key)
            if not isinstance(rows, list):
                out[key] = rows if rows is not None else []
                continue
            flat = []
            for row in rows:
                if not isinstance(row, dict):
                    flat.append(row)
                    continue
                doctor = row.get("doctor") if isinstance(row.get("doctor"), dict) else {}
                details = row.get("detail")
                if not isinstance(details, list) or not details:
                    details = [{}]
                for d in details:
                    if not isinstance(d, dict):
                        continue
                    item = {k: v for k, v in row.items() if k not in ("doctor", "detail")}
                    item.update(doctor)
                    item.update(d)
                    flat.append(item)
            out[key] = flat
        return out

    async def online_depts(self) -> list:
        """互联网科室列表（/public/expert/dept）→ [{id, code, name, intro}]。"""
        j = await self._get("/public/expert/dept", bearer=False)
        return self._out(j, [])

    async def expert_cloud_depts(self) -> dict:
        """专家云诊室科室+时段（/public/expert/cloud/dept）→ {cloudDeptList, cloudTimes}。"""
        j = await self._get("/public/expert/cloud/dept", bearer=False)
        return self._out(j, {})

    async def online_search(self, key: str) -> list:
        """在线搜索（/public/search/online?key=）→ 医生/科室。"""
        j = await self._get("/public/search/online", {"key": key}, bearer=False)
        return self._out(j, [])

    async def judge_revisit(self, id_card: str) -> dict:
        """复诊判断（/public/online/judgeRevisit?id_card=）→ 是否可复诊/在线。"""
        j = await self._get("/public/online/judgeRevisit", {"id_card": id_card}, bearer=False)
        return self._out(j, {})

    async def online_doctor_schedule(self, doctor_code: str = "", **params) -> dict:
        """在线医生排班（/public/schedule/doctor/online）。"""
        if doctor_code:
            params.setdefault("doctorCode", doctor_code)
        j = await self._get("/public/schedule/doctor/online", params, bearer=False)
        return self._out(j, {})

    async def re_clinic_schedule(self, doctor_code: str = "") -> list:
        """复诊排班（/public/re_clinic/getScheduleByDocId）。"""
        j = await self._get("/public/re_clinic/getScheduleByDocId", {"doctorCode": doctor_code} if doctor_code else {}, bearer=False)
        return self._out(j, [])
