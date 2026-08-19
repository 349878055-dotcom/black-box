"""njpkzyy · 查号源模块（公开接口，不用登录，走手机通道）。

list_depts / list_noon_codes / list_dept_doctors / get_available_dates / get_schedule /
judge_online / get_schedule_detail / get_pay_channels。

⚠️ 统一 async 形态（registry.run 用 await 调用）；内部 _get 走手机蓝图。
"""
from __future__ import annotations

import datetime

from ._base import ONLINE_AGENT_ID


class QueryMixin:
    """查号源（公开，不用登录）。需 self._get / self._out。"""

    async def list_depts(self, branch_code: str = "") -> list[dict]:
        """科室列表（两级：父科室 pid 分组 + 子科室）→ [{dept_code, dept_name, pid, ...}]。"""
        res = await self._get("/api/public/basic/v3/depts", {"branch_code": branch_code})
        return self._out(res, [])

    async def list_noon_codes(self, branch_code: str = "", branch_name: str = "") -> list[dict]:
        """午别/时段编码 → [{noon_name, noon_code(1上午/2下午/3夜间/6全天), time_part}]。"""
        res = await self._get("/api/public/v3/noon_code",
                              {"branch_code": branch_code, "branch_name": branch_name})
        return self._out(res, [])

    async def list_dept_doctors(self, dept_code: str = "", branch_code: str = "",
                                branch_name: str = "") -> list[dict]:
        """科室医生 → [{doctor_code, doctor_name, dept_name, speciality, ...}]。

        注意：科室是两级结构，查医生/排班必须先 list_depts 拿到真实 dept_code 再传。
        """
        path = f"/api/public/v3/dept/doctor/{dept_code}" if dept_code else "/api/public/v3/dept/doctor"
        res = await self._get(path, {"branch_code": branch_code, "branch_name": branch_name})
        return self._out(res, [])

    async def get_available_dates(self, dept_code: str = "", begin_date: str = "",
                                  end_date: str = "", schedule_type: str = "3",
                                  channel: str = "dept", type: str = "0") -> list[str]:
        """可约日期 → [YYYY-MM-DD, ...]（默认今天~+7天）。

        dept_code 必填（真实科室代码）；schedule_type 3=号源；channel=dept 按科室查。
        """
        t = datetime.date.today()
        b = begin_date or t.isoformat()
        e = end_date or (t + datetime.timedelta(days=7)).isoformat()
        res = await self._get("/api/public/v3/schedule/check", {
            "begin_date": b, "end_date": e, "dept_code": dept_code,
            "schedule_type": schedule_type, "channel": channel, "type": type,
        })
        return self._out(res, [])

    async def get_schedule(self, dept_code: str = "", begin_date: str = "",
                           end_date: str = "", channel: str = "dept", type: str = "0") -> dict:
        """某科室某天排班 → [{schedule_id, reg_name, noon_code, doctor, detail(时段)…}]。

        detail 每条：{time_part, schedule_num_id, remaining_num, is_enable}。
        """
        t = datetime.date.today()
        b = begin_date or t.isoformat()
        e = end_date or b
        res = await self._get("/api/public/v3/schedule", {
            "begin_date": b, "end_date": e, "dept_code": dept_code,
            "channel": channel, "type": type,
        })
        return self._out(res, {})

    async def judge_online(self, date: str, dept_code: str = "", doctor_code: str = "",
                           noon_code: str = "", time_type: str = "", type: str = "0") -> dict:
        """在线号判断（是否可挂在线号）。在线号类接口须用 ONLINE_AGENT_ID。"""
        res = await self._get("/api/public/v3/schedule/online/judge", {
            "date": date, "dept_code": dept_code, "doctor_code": doctor_code,
            "noon_code": noon_code, "time_type": time_type, "type": type,
        }, agent_id=ONLINE_AGENT_ID)
        return self._out(res, {})

    async def get_schedule_detail(self, schedule_id: str = "", schedule_day: str = "",
                                  type: str = "0") -> dict:
        """在线号时段详情 → [{time_part, schedule_num_id, remaining_num, is_enable, ...}]。

        需先从 get_schedule 拿到 schedule_id。
        """
        res = await self._get("/api/public/v3/schedule/online/detail", {
            "schedule_id": schedule_id, "schedule_day": schedule_day, "type": type,
        }, agent_id=ONLINE_AGENT_ID)
        return self._out(res, {})

    async def get_pay_channels(self) -> list[dict]:
        """支付渠道 → [{pay_channel, name, status}]（如 WX_JSAPI 微信支付）。"""
        res = await self._get("/api/public/v3/pay_channel", agent_id=ONLINE_AGENT_ID)
        return self._out(res, [])
