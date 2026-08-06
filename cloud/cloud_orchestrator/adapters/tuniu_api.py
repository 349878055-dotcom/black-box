"""
途牛 MCP · AI 可读 API（途牛官方开放平台 MCP，JSON-RPC + SSE）。

文档：https://open.tuniu.com/mcp/docs/
鉴权：请求头 apiKey（= TUNIU_API_KEY，cloud/config.json 的 tuniu.api_key）
URL ：https://openapi.tuniu.cn/mcp/{category}
业务分类：flight 机票 / train 火车 / hotel 酒店 / ticket 门票 / cruise 邮轮 / holiday 度假
方式：JSON-RPC 2.0（tools/list / tools/call），响应 JSON 或 SSE

实测（2026-08-06）：火车票搜索真实返回（南京→北京 1462 次，含票价/余票）。
搜索/查询免费；下单（bookTrain/saveOrder）走途牛支付（真购买须用户确认）。

用法：
  api = TuniuAPI()
  api.search_train("南京", "北京", "2026-08-06") → 车次+票价+余票
  api.train_detail(train_num, date)             → 车次详情
  api.search_flight("南京", "北京", "2026-08-06")
  api.search_hotel("南京", "2026-08-06", "2026-08-08")
  api.list_tools("train")                        → 该分类可用工具
  api.book_train(...)                            → ⚠️ 订票（支付走途牛，须确认）
"""
from __future__ import annotations

import json
import logging

import requests

from ..config import get

logger = logging.getLogger("xiami.tuniu")

BASE = "https://openapi.tuniu.cn/mcp"


class TuniuAPI:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get("tuniu_api_key", "")
        self.headers = {
            "apiKey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

    # ─────────── MCP 底层（JSON-RPC + SSE 解析）───────────
    def _rpc(self, category: str, method: str, params: dict | None = None) -> dict:
        """调途牛 MCP：返回 {ok, data/text/error}。"""
        if not self.api_key:
            return {"ok": False, "error": "途牛 apiKey 未配置（cloud/config.json 的 tuniu.api_key）"}
        try:
            r = requests.post(
                f"{BASE}/{category}",
                headers=self.headers,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                timeout=30,
            )
            payload = self._parse(r.text)
        except Exception as e:
            return {"ok": False, "error": f"途牛请求失败：{e}"}

        if isinstance(payload, dict) and payload.get("error"):
            return {"ok": False, "error": json.dumps(payload["error"], ensure_ascii=False)[:300]}
        result = payload.get("result") if isinstance(payload, dict) else None
        return self._extract(result)

    def _parse(self, text: str):
        """解析响应：先试纯 JSON，再试 SSE（data: 行）。"""
        t = (text or "").strip()
        if not t:
            return {}
        try:
            return json.loads(t)
        except Exception:
            pass
        for line in t.split("\n"):
            s = line.strip()
            if s.startswith("data:"):
                try:
                    return json.loads(s[5:].strip())
                except Exception:
                    continue
        return {"_raw": t[:500]}

    def _extract(self, result) -> dict:
        """MCP 返回 result.content[].text（常是 JSON 字符串）→ 解包成结构化。"""
        if isinstance(result, dict) and result.get("content"):
            text = ""
            for b in result.get("content") or []:
                if isinstance(b, dict):
                    text += b.get("text", "") if b.get("type") == "text" else json.dumps(b, ensure_ascii=False)
            text = text.strip()
            try:
                inner = json.loads(text)
                if isinstance(inner, dict) and inner.get("data") is not None:
                    return {"ok": True, "data": inner["data"], "meta": inner}
                return {"ok": True, "data": inner}
            except Exception:
                return {"ok": True, "text": text[:3000]}
        if result is None:
            return {"ok": True, "data": None}
        return {"ok": True, "data": result}

    # ─────────── 查询（免费）───────────
    def list_tools(self, category: str = "train") -> dict:
        """列出某分类可用工具。"""
        return self._rpc(category, "tools/list")

    def search_train(self, departure: str, arrival: str, date: str) -> dict:
        """火车票搜索：南京→北京 2026-08-06 → 车次列表（含票价/余票）。"""
        return self._rpc("train", "tools/call", {
            "name": "searchLowestPriceTrain",
            "arguments": {"departureCityName": departure, "arrivalCityName": arrival, "departureDate": date},
        })

    def train_detail(self, train_num: str, date: str) -> dict:
        """车次详情（站点/时刻）。"""
        return self._rpc("train", "tools/call", {
            "name": "queryTrainDetail",
            "arguments": {"trainNum": train_num, "departureDate": date},
        })

    def search_flight(self, departure: str, arrival: str, date: str) -> dict:
        """机票搜索：南京→北京 日期 → 航班列表（低价）。"""
        return self._rpc("flight", "tools/call", {
            "name": "searchLowestPriceFlight",
            "arguments": {"departureCityName": departure, "arrivalCityName": arrival, "departureDate": date},
        })

    def search_hotel(self, city: str, check_in: str, check_out: str) -> dict:
        """酒店搜索：城市 + 入住/离店日期 → 酒店列表。"""
        return self._rpc("hotel", "tools/call", {
            "name": "tuniu_hotel_search",
            "arguments": {"cityName": city, "checkIn": check_in, "checkOut": check_out},
        })

    def search_ticket(self, scenic_name: str) -> dict:
        """景点门票查询。"""
        return self._rpc("ticket", "tools/call", {
            "name": "query_cheapest_tickets",
            "arguments": {"scenic_name": scenic_name},
        })

    # ─────────── 下单（⚠️ 涉及支付，须用户确认）───────────
    def book_train(self, **kwargs) -> dict:
        """预订火车票（⚠️ 真购买，支付走途牛，须用户确认）。参数按途牛官方 bookTrain 要求。
        必填：resources=[{resourceId, adultPrice, departsDate}], adultTourists=[{name,psptId,psptType,tel}],
              contact={tel}。resourceId 必须来自 train_detail 的 seatInfo.resId。"""
        return self._rpc("train", "tools/call", {"name": "bookTrain", "arguments": kwargs})

    def book_train_auto(self, departure: str, arrival: str, date: str,
                        train_num: str, seat_name: str = "二等座",
                        passengers: list | None = None, contact_tel: str = "") -> dict:
        """一键订火车票（⚠️ 真购买，支付走途牛，须用户明确确认）。
        自动完成：搜车次 → 查详情（从 seatInfo 取 resId/price）→ 组装 → 下单。
        passengers: [{"name":"张三","psptId":"身份证号","psptType":"1","tel":"手机号"}]
        contact_tel: 联系人手机号。返回 {ok, order/error}。"""
        try:
            # 1. 搜车次（确认存在）
            sr = self.search_train(departure, arrival, date)
            if not sr.get("ok"):
                return {"ok": False, "error": f"搜车次失败：{sr.get('error','')}"}
            # 2. 查详情，从 seatInfo 找目标席别 resId
            tr = self.train_detail(train_num, date)
            if not tr.get("ok"):
                return {"ok": False, "error": f"查车次详情失败：{tr.get('error','')}"}
            detail = tr.get("data")
            if isinstance(detail, dict):
                detail = detail.get("data") or detail
            seat_info = []
            departs_date = date
            if isinstance(detail, dict):
                departs_date = detail.get("departsDate") or date
                seat_info = detail.get("seatInfo") or []
            elif isinstance(detail, list):
                # 兼容：detail 可能是列表
                for it in detail:
                    if isinstance(it, dict) and it.get("seatInfo"):
                        departs_date = it.get("departsDate") or date
                        seat_info = it.get("seatInfo") or []
                        break
            if not seat_info:
                return {"ok": False, "error": "车次详情没有 seatInfo（可能无票）"}
            target = None
            for s in seat_info:
                name = str(s.get("seatName") or "")
                if seat_name in name:
                    target = s
                    break
            if target is None:
                names = [str(s.get("seatName") or "") for s in seat_info]
                return {"ok": False, "error": f"没有席别「{seat_name}」，可选：{names}"}
            # 3. 组装下单参数
            resources = [{
                "resourceId": target.get("resId"),
                "adultPrice": target.get("price"),
                "departsDate": departs_date,
            }]
            adult_tourists = passengers or []
            contact = {"tel": contact_tel}
            return {
                "ok": True,
                "ready": True,
                "order_params": {
                    "train_num": train_num, "seat": seat_name,
                    "resources": resources, "adultTourists": adult_tourists, "contact": contact,
                },
                "confirm_payload": {
                    "resources": resources, "adultTourists": adult_tourists, "contact": contact,
                },
            }
        except Exception as e:
            return {"ok": False, "error": f"一键订票异常：{e}"}

    def create_flight_order(self, **kwargs) -> dict:
        """创建机票订单（⚠️ 真购买，支付走途牛，须用户确认）。"""
        return self._rpc("flight", "tools/call", {"name": "saveOrder", "arguments": kwargs})

    def cancel_order(self, category: str = "train", **kwargs) -> dict:
        """取消未支付订单。"""
        return self._rpc(category, "tools/call", {"name": "cancelOrder", "arguments": kwargs})


# 便捷入口
api = TuniuAPI()

if __name__ == "__main__":
    import datetime
    tm = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    print("工具列表:", api.list_tools("train").get("ok"))
    r = api.search_train("南京", "北京", tm)
    if r.get("ok"):
        d = r.get("data")
        if isinstance(d, list):
            for t in d[:3]:
                print(t.get("trainNum"), t.get("departureTime"), "→", t.get("arrivalTime"),
                      "硬座:", t.get("price", {}).get("yzPrice", ""))
