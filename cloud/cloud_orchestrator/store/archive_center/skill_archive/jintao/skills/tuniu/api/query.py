"""途牛 · MCP 查询模块（官方开放平台，apiKey，免费，免登录）。

只负责「查」：list_tools / search_train / train_detail / search_flight / search_hotel / search_ticket。
查询用 MCP JSON-RPC + SSE；必须走手机通道（禁云端直发）。
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("xiami.tuniu")

BASE = "https://openapi.tuniu.cn/mcp"     # ① MCP 查询
PH_API_KEY = "{{api_key}}"                # 蓝图占位符（手机 SkillExecutor 本地替换）


class QueryMixin:
    """MCP 查询（查车次/机票/酒店/门票）。需 self.api_key / self.executor / self.headers。"""

    # ─────────── 蓝图（第 3 条）───────────
    def _blueprint(self, category: str, method: str, params: dict | None = None) -> dict:
        # apiKey 是开放平台配置 key（非用户登录态），直接下发真实值，不依赖手机凭据库
        api_key = self.api_key or PH_API_KEY
        return {
            "skill": "tuniu",
            "request": {
                "method": "POST",
                "url": f"{BASE}/{category}",
                "headers": {"apiKey": api_key, "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream"},
                "body": {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                "sign_type": "none",
            },
            "credential": {"kind": "none", "target": "tuniu"},
        }

    def describe_request(self, method: str, **params) -> dict | None:
        """第 3 条：MCP 方法名 → 蓝图（category 由方法决定）。复合方法返回 None。"""
        cat = {
            "list_tools": "train", "search_train": "train", "train_detail": "train",
            "search_flight": "flight",
            "search_hotel": "hotel", "search_ticket": "ticket",
        }.get(method)
        if not cat:
            return None
        rpc_name = {
            "list_tools": "tools/list", "search_train": "tools/call",
            "train_detail": "tools/call",
            "search_flight": "tools/call",
            "search_hotel": "tools/call",
            "search_ticket": "tools/call",
        }[method]
        args = dict(params or {})
        tool_name = {
            "search_train": "searchLowestPriceTrain", "train_detail": "queryTrainDetail",
            "search_flight": "searchLowestPriceFlight", "search_hotel": "tuniu_hotel_search",
            "search_ticket": "query_cheapest_tickets",
        }.get(method)
        if rpc_name == "tools/call" and tool_name:
            args = {"name": tool_name, "arguments": args}
        return self._blueprint(cat, rpc_name, args)

    # ─────────── MCP 底层（JSON-RPC + SSE 解析；有 executor 走手机）───────────
    async def _rpc(self, category: str, method: str, params: dict | None = None) -> dict:
        """调途牛 MCP：返回 {ok, data/text/error}。"""
        if not self.api_key:
            return {"ok": False, "error": "途牛 apiKey 未配置（cloud/config.json 的 skills.tuniu.api_key）"}
        if not self.executor:
            return {"ok": False, "error": "tuniu 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(category, method, params)
        res = await self.executor(bp)
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                    "status": res.get("status")}
        payload = self._parse(str(res.get("body") or ""))

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

    # ─────────── 查询（MCP，免费）───────────
    async def list_tools(self, category: str = "train") -> dict:
        """列出某分类可用工具。"""
        return await self._rpc(category, "tools/list")

    async def search_train(self, departure: str, arrival: str, date: str) -> dict:
        """火车票搜索（MCP，免费，仅查询）→ 车次+票价+余票。"""
        return await self._rpc("train", "tools/call", {
            "name": "searchLowestPriceTrain",
            "arguments": {"departureCityName": departure, "arrivalCityName": arrival, "departureDate": date},
        })

    async def train_detail(self, train_num: str, date: str,
                           departure: str = "", arrival: str = "") -> dict:
        """车次详情（MCP，站点/时刻/席位）。

        ⚠️ 途牛 MCP queryTrainDetail 必填 departureStationName/arrivalStationName，
        缺站名会失败（2026-08-07 实测修复）。departure/arrival 为出发/到达城市名。
        """
        args = {"trainNum": train_num, "departureDate": date}
        if departure:
            args["departureStationName"] = departure
        if arrival:
            args["arrivalStationName"] = arrival
        return await self._rpc("train", "tools/call", {
            "name": "queryTrainDetail", "arguments": args})

    async def search_flight(self, departure: str, arrival: str, date: str) -> dict:
        """机票搜索（MCP）→ 航班列表（低价）。"""
        return await self._rpc("flight", "tools/call", {
            "name": "searchLowestPriceFlight",
            "arguments": {"departureCityName": departure, "arrivalCityName": arrival, "departureDate": date},
        })

    async def search_hotel(self, city: str, check_in: str, check_out: str) -> dict:
        """酒店搜索（MCP）→ 酒店列表。"""
        return await self._rpc("hotel", "tools/call", {
            "name": "tuniu_hotel_search",
            "arguments": {"cityName": city, "checkIn": check_in, "checkOut": check_out},
        })

    async def search_ticket(self, scenic_name: str) -> dict:
        """景点门票查询（MCP）。"""
        return await self._rpc("ticket", "tools/call", {
            "name": "query_cheapest_tickets",
            "arguments": {"scenic_name": scenic_name},
        })
