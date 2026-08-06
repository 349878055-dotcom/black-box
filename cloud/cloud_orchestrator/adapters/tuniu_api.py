"""
途牛 · AI 可读 API（两部分：官方 MCP 查询 + 微信小程序/官网下单支付）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① TuniuAPI — 途牛官方开放平台 MCP（查询为主，免费）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  文档：https://open.tuniu.com/mcp/docs/
  鉴权：请求头 apiKey（= TUNIU_API_KEY，cloud/config.json 的 tuniu.api_key）
  URL ：https://openapi.tuniu.cn/mcp/{category}
  方式：JSON-RPC 2.0（tools/list / tools/call），响应 JSON 或 SSE

  实测（2026-08-06）：火车票搜索真实返回（南京→北京 1462 次，含票价/余票）。
  查询全部免费；下单方法也可用但支付走途牛（真购买须用户确认）。

  用法：
    api = TuniuAPI()
    api.list_tools("train")                     → 该分类可用工具
    api.search_train("南京","北京","2026-08-06")  → 火车票（车次+票价+余票）
    api.train_detail("1462","2026-08-06")        → 车次详情（取 resId，下单前需要）
    api.search_flight("南京","北京","2026-08-06") → 机票（低价航班）
    api.search_hotel("南京","2026-08-06","2026-08-08") → 酒店
    api.search_ticket("故宫")                    → 景点门票
    api.book_train(...)                          → ⚠️ 订火车票（支付走途牛，须确认）
    api.book_train_auto(...)                     → ⚠️ 一键订票（自动组装）
    api.create_flight_order(...)                 → ⚠️ 创建机票订单
    api.cancel_order(...)                        → 取消未支付订单

【TuniuAPI 全部 10 个方法】
  查询：list_tools / search_train / train_detail / search_flight / search_hotel / search_ticket
  下单：book_train / book_train_auto / create_flight_order / cancel_order

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
② TuniuWebAPI — 途牛微信小程序/官网（下单 + 支付闭环）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  来源：途牛微信小程序真实抓包（2026-08-05 实测下单成功 orderId 1259150779）
  登录态：sessionId（途牛小程序会话）+ cookies（App「导出登录态」/ 抓包获取）
  host：m-p.tuniu.com / m.tuniu.com
  说明：这是「真购买」通道——下单走途牛支付，手机 App 内置浏览器 + 支付宝唤起支付

  用法：
    api = TuniuWebAPI(cookies=..., session_id=...)
    api.web_search_train("南京","北京","2026-08-07")  → 官网查车次（含 resId）
    api.web_get_travellers()                          → 12306 实名乘客（下单用）
    api.web_add_order({...})                          → ⚠️ 提交订单（真购买）
    api.web_order_detail(order_id)                    → 订单详情
    api.web_cancel_order(order_id)                    → ⚠️ 取消订单（真实取消）
    api.web_contacts()                                → 联系人列表
    api.web_coupons()                                 → 火车票优惠券
    api.web_calendar("南京","北京","2026-08-07")       → 车次日历

【TuniuWebAPI 全部 8 个方法】
  查车次：web_search_train / web_calendar
  乘客/联系人：web_get_travellers / web_contacts
  下单支付：web_add_order / web_order_detail / web_cancel_order
  优惠券：web_coupons

注册表里调用：web_* 方法走 TuniuWebAPI（registry 的 web_class）。
"""
from __future__ import annotations

import json
import logging
import os

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


# ══════════════════════════════════════════════════════════════════
# 途牛官网版（m-p.tuniu.com / m.tuniu.com）— 查车次 + 下单
# 数据来源：途牛微信小程序真实抓包（2026-08-05 实测下单成功）。
# 登录态：sessionId（途牛小程序会话）+ 可选 cookies。
# ══════════════════════════════════════════════════════════════════
class TuniuWebAPI:
    """途牛官网/小程序 API：查车次（含 resId/价格）→ 乘客 → 下单 → 订单详情。

    - 查车次/乘客：带 cookies（登录态）即可
    - 下单 AddOrder：body 里带 sessionId（途牛小程序会话，需登录后获取）
    """

    BASE = "https://m-p.tuniu.com"
    MBASE = "https://m.tuniu.com"
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781")
    REFERER = "https://servicewechat.com/wx340329c7ee375a33/523/page-frame.html"

    _HERE = os.path.dirname(os.path.abspath(__file__))
    _SESS_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "cloud", "cloud_orchestrator", "data", "sessions"))
    SESSION_FILE = os.path.join(_SESS_DIR, "tuniu_web_session.json")

    def __init__(self, cookies: str | dict | None = None, session_id: str = "") -> None:
        self.cookies: dict[str, str] = {}
        if isinstance(cookies, str):
            for it in cookies.split(";"):
                it = it.strip()
                if "=" in it:
                    k, v = it.split("=", 1)
                    self.cookies[k.strip()] = v.strip()
        elif isinstance(cookies, dict):
            self.cookies = cookies
        self.session_id = session_id
        self.token = ""
        # 未传登录态 → 从持久化目录加载（重启不丢）
        if not self.cookies and not self.session_id:
            self._load_session()

    # ─────────── 登录态持久化（data/sessions/，云端重启不丢）───────────
    def _load_session(self) -> None:
        try:
            if os.path.exists(self.SESSION_FILE):
                with open(self.SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.cookies = dict(data.get("cookies") or {})
                self.session_id = str(data.get("session_id") or "")
        except Exception as e:
            logger.warning("途牛登录态加载失败: %s", e)

    def save_session(self, cookies=None, session_id: str = "") -> str:
        """保存途牛登录态（App 导出/抓包后调用），返回保存路径。"""
        try:
            if cookies is not None:
                if isinstance(cookies, str):
                    self.cookies = {}
                    for it in cookies.split(";"):
                        it = it.strip()
                        if "=" in it:
                            k, v = it.split("=", 1)
                            self.cookies[k.strip()] = v.strip()
                elif isinstance(cookies, dict):
                    self.cookies = cookies
            if session_id:
                self.session_id = session_id
            os.makedirs(self._SESS_DIR, exist_ok=True)
            with open(self.SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump({"cookies": self.cookies, "session_id": self.session_id},
                          f, ensure_ascii=False, indent=2)
            logger.info("途牛登录态已保存 → %s", self.SESSION_FILE)
            return self.SESSION_FILE
        except Exception as e:
            logger.warning("途牛登录态保存失败: %s", e)
            return ""

    def _post(self, base: str, path: str, body: dict, use_session: bool = False) -> dict:
        h = {"User-Agent": self.UA, "Content-Type": "application/json",
             "Referer": self.REFERER}
        if self.token:
            h["token"] = self.token
        if use_session and self.session_id:
            body = dict(body)
            body.setdefault("sessionId", self.session_id)
        r = requests.post(base + path, json=body, headers=h, cookies=self.cookies,
                          timeout=25, verify=False)
        try:
            return r.json()
        except Exception:
            return {"raw": r.text[:300], "http": r.status_code}

    def init_token(self) -> str:
        """getLocalVersion → token（查车次前需要）。"""
        j = self._post(self.BASE, "/api/train/trainApi/getLocalVersion", {})
        self.token = (j.get("data") or {}).get("token", "")
        return self.token

    # ─────────── 查车次（官网，无需 sessionId）───────────
    def web_search_train(self, departure: str, arrival: str, date: str) -> dict:
        """官网查车次（m-p.tuniu.com ticketList）→ {rows:[...], count}。
        每条含 trainId/trainNum/resId/seat/price/leftNumber（下单基础数据）。"""
        self.init_token()
        # 城市→代码（fuzzySearch data 是 list）
        code = {}
        for city in [departure, arrival]:
            fz = self._post(self.BASE, "/api/train/product/fuzzySearch", {"keyword": city})
            d = fz.get("data")
            if isinstance(d, list) and d:
                code[city] = d[0].get("cityCode")
            elif isinstance(d, dict):
                code[city] = d.get("cityCode")
        dep_code = code.get(departure, ""); arr_code = code.get(arrival, "")
        j = self._post(self.BASE, "/api/train/product/ticketList", {
            "departureCityCode": dep_code, "arrivalCityCode": arr_code,
            "departureCityName": departure, "arrivalCityName": arrival,
            "departureDate": date,
        })
        if j.get("errorCode") == 710000:
            return {"ok": True, "count": (j.get("data") or {}).get("count"),
                    "rows": (j.get("data") or {}).get("rows") or []}
        return {"ok": False, "error": j.get("msg") or str(j)[:200]}

    # ─────────── 乘客 ───────────
    def web_get_travellers(self) -> dict:
        """12306 实名乘客（mergeQueryTravellerInfo）→ [{name, contacterId, psptId, ...}]。"""
        j = self._post(self.MBASE, "/api/train/product/mergeQueryTravellerInfo",
                       {"sessionId": self.session_id} if self.session_id else {})
        if j.get("errorCode") == 710000:
            return {"ok": True, "travellers": j.get("data") or []}
        return {"ok": False, "error": j.get("msg") or str(j)[:200]}

    # ─────────── 下单（⚠️ 真购买，须确认）───────────
    def web_add_order(self, order: dict) -> dict:
        """提交火车票订单（AddOrder，⚠️真购买，走途牛支付）。
        order 需含：trainId/trainNumber/departDate/resourceId/seat/seatId/seatPrice/
        ministryRailwaysId(12306绑定ID)/departure-arrival城市站/touristList(乘客)/contactList。
        """
        if not self.session_id:
            return {"ok": False, "error": "缺少 sessionId（途牛小程序登录态）"}
        body = dict(order)
        body.setdefault("sessionId", self.session_id)
        j = self._post(self.MBASE, "/api/train/order/AddOrder", body)
        if j.get("errorCode") == 710000 and (j.get("data") or {}).get("success"):
            return {"ok": True, "order_id": (j.get("data") or {}).get("orderId"),
                    "data": j.get("data")}
        return {"ok": False, "error": j.get("msg") or j.get("errorCode") or str(j)[:200],
                "raw": j}

    def web_order_detail(self, order_id) -> dict:
        """订单详情（orderDetail）。"""
        j = self._post(self.MBASE, "/api/train/order/orderDetail",
                       {"sessionId": self.session_id, "orderId": str(order_id)})
        if j.get("errorCode") == 710000:
            return {"ok": True, "order": j.get("data")}
        return {"ok": False, "error": j.get("msg") or str(j)[:200]}

    # ─────────── 订单操作（小程序逆向补充）───────────
    def web_cancel_order(self, order_id) -> dict:
        """取消订单（newCancelOrder，GET + d 参数，⚠️真实取消）。"""
        params = {"d": json.dumps({"sessionId": self.session_id,
                                   "orderId": str(order_id)}, ensure_ascii=False)}
        r = requests.get(self.MBASE + "/api/train/order/newCancelOrder", params=params,
                         headers={"User-Agent": self.UA, "Referer": self.REFERER},
                         cookies=self.cookies, timeout=25, verify=False)
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "raw": r.text[:300]}
        if j.get("errorCode") == 710000:
            return {"ok": True, "data": j.get("data")}
        return {"ok": False, "error": j.get("msg") or str(j)[:200], "raw": j}

    def web_contacts(self, **extra) -> dict:
        """联系人列表（contacts，GET + d 参数）。"""
        body = {"sessionId": self.session_id, **extra}
        r = requests.get(self.MBASE + "/api/train/order/contacts",
                         params={"d": json.dumps(body, ensure_ascii=False)},
                         headers={"User-Agent": self.UA, "Referer": self.REFERER},
                         cookies=self.cookies, timeout=25, verify=False)
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "raw": r.text[:300]}
        return {"ok": j.get("errorCode") == 710000, "data": j.get("data"), "raw": j}

    def web_coupons(self, **extra) -> dict:
        """我的火车票优惠券（getMyCoupons，GET + d 参数）。"""
        body = {"sessionId": self.session_id, **extra}
        r = requests.get(self.MBASE + "/api/train/order/getMyCoupons",
                         params={"d": json.dumps(body, ensure_ascii=False)},
                         headers={"User-Agent": self.UA, "Referer": self.REFERER},
                         cookies=self.cookies, timeout=25, verify=False)
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "raw": r.text[:300]}
        return {"ok": j.get("errorCode") == 710000, "data": j.get("data"), "raw": j}

    def web_calendar(self, departure: str, arrival: str, date: str) -> dict:
        """车次日历（calendarV2，看哪天有票）。"""
        self.init_token()
        j = self._post(self.BASE, "/api/train/product/calendarV2", {
            "departureCityName": departure, "arrivalCityName": arrival,
            "departureDate": date,
        })
        return {"ok": j.get("errorCode") == 710000, "data": j.get("data"), "raw": j}


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
