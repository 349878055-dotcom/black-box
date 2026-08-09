"""njpkzyy_new · 就诊/挂号模块（需微信授权登录）。

get_medical_card（就诊卡/患者信息）→ register_online（在线挂号 ⚠️真挂号）→
get_order（订单详情）→ get_order_goods（订单商品详情）。
"""
from __future__ import annotations

from ._base import ONLINE_AGENT_ID


class VisitMixin:
    """就诊/挂号（需登录）。需 self._get / self._post / self._out。"""

    async def get_medical_card(self) -> list[dict]:
        """就诊卡/患者信息（需登录）→ [{id, patient_code, is_valid, is_default, ...}]。"""
        j = await self._get("/api/user/medical_card", bearer=True)
        return self._out(j, [])

    async def register_online(self, **kwargs) -> dict:
        """在线挂号（POST /api/public/v3/register/online）⚠️真挂号有副作用，须用户确认。

        需登录 + ONLINE_AGENT_ID。请求体字段（对齐抓包真实请求体）：
        appointment_time/dept_code/dept_name/doctor_code/doctor_name/id_card/patient_code/
        patient_name/noon_code/schedule_id/schedule_num_id/time_part/cost/pay_channel/open_id…
        """
        if not self.executor:
            return {"ok": False, "error": "njpkzyy_new 未注入手机通道 executor，已停止执行（禁云端直连）"}
        body = dict(kwargs)
        bp = self._blueprint("/api/public/v3/register/online", body=body, bearer=True,
                             method="POST", agent_id=ONLINE_AGENT_ID)
        return await self._exec(bp)

    async def get_order(self, order_id: str = "") -> dict:
        """订单详情（需登录）→ {id, order_no, state, is_paid, dept_name, appointment_time, ...}。"""
        path = f"/api/order/order/v2/order/{order_id}" if order_id else "/api/order/order/v2/order"
        j = await self._get(path, bearer=True)
        return self._out(j, {})

    async def get_order_goods(self, id: str = "", type: str = "appointment") -> dict:
        """订单商品详情（需登录，在线号用 ONLINE_AGENT_ID）→ {id, order_id, dept_name, ...}。"""
        j = await self._get("/api/public/order/goods/detail", {"id": id, "type": type},
                            bearer=True, agent_id=ONLINE_AGENT_ID)
        return self._out(j, {})
