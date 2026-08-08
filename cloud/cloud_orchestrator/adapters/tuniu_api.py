
"""
途牛 · AI 可读 API（一个 skill 两种能力：查 + 买）。

① 查（途牛官方开放平台 MCP，apiKey，免费，免登录）：
   文档 https://open.tuniu.com/mcp/docs/；JSON-RPC + SSE
   list_tools / search_train / train_detail / search_flight / search_hotel / search_ticket
   —— 官方开放平台，只查询，不能下单（book 无权限）

② 买（途牛 M 站 m.tuniu.com，接口直调，需登录 cookie）：
   set_cookies → submit_order（AddOrder，乘客直传 touristList，免网页"添加乘客"弹窗）→ pay
   —— 下单创建订单，支付在手机支付宝/途牛 App 完成（电脑无支付宝客户端付不了）

关键点（2026-08-07 实测，AddOrder 下单成功 orderId=1259153040）：
  - 下单必须登录（cookie：isLogined/ssoUser/muser/tuniuuser_id）；
    登录 = passport.tuniu.com 手机号+短信（+腾讯滑块），真人配合一次保存 cookie 复用
  - 「添加乘客拉不下来」= 途牛弹窗按手机屏做、电脑宽视口失效；本接口直接传乘客（touristList）完全绕开
  - M 站有风控：直接访问详情页 URL 会"异常访问"，需从搜索页点入（页面自动化时注意）

Device-as-Proxy（docs/改造方案_DeviceAsProxy.md）：
  - 云端 = 大脑：组装参数、生成「请求蓝图」、解析响应；
  - 手机 = 手：经 executor（= bridge.send_skill_request 下发 skill_request）执行蓝图，
    手机真实 IP 直连平台，回传原始响应 skill_result；
  - ② M 站蓝图 credential=kind:cookie → 手机 SkillExecutor 从本地凭据库补 Cookie 头（云端不持有登录态）；
  - 未注入 executor 时自动降级为旧「云端直发」（兼容单机测试）。

用法：
  api = TuniuAPI()                                  # —— 查（MCP）——
  await api.search_train("南京", "北京", "2026-08-06")  # → 车次+票价+余票

  api = TuniuAPI(executor=...)                      # —— 买（M 站，手机通道）——
  await api.set_cookies({...})                      # 先设登录 cookie（手机通道下由手机凭据库提供）
  await api.submit_order(dep="上海", arr="苏州", date="2026-08-08",
                         train_num="K528", seat_name="硬座",
                         passengers=[{"name":"金涛","psptId":"320111198705186016",
                                      "tel":"18913300200","psptType":1,
                                      "birthday":"1987-05-18","sex":1}],
                         contact_tel="18913300200")
      # → {ok, order_id, order_amount, pay_url}，支付请用户在手机支付宝/途牛 App 完成
  await api.pay(order_id)                           # → 返回支付入口（手机 App 完成）
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse

import requests

from ..config import get

logger = logging.getLogger("xiami.tuniu")

BASE = "https://openapi.tuniu.cn/mcp"     # ① MCP 查询
M = "https://m.tuniu.com"                  # ② M 站（网页）
MAPI = "https://api.tuniu.com"             # ② M 站接口
CITY_CODES = {"上海": "2500", "苏州": "1615"}  # 途牛城市代码（实测确认；其余待补）
M_UA = ("Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")

# ── 蓝图占位符（手机 SkillExecutor 本地替换）──
PH_API_KEY = "{{api_key}}"


class TuniuAPI:
    """途牛：① 查（MCP，apiKey，免费）+ ② 买（M 站，cookie，下单/支付）。"""

    def __init__(self, api_key: str | None = None, cookies: dict | None = None,
                 executor=None) -> None:
        # —— ① 查（MCP）——
        self.api_key = api_key or get("tuniu_api_key", "")
        # Device-as-Proxy：手机执行通道（async (blueprint) -> {ok,status,headers,body,error}）
        self.executor = executor
        self.headers = {
            "apiKey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # —— ② 买（M 站）——（手机通道下登录态由手机凭据库提供，此处仅云端直发降级用）
        self.cookies: dict[str, str] = dict(cookies or {})

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
            return {"ok": False, "error": "途牛 apiKey 未配置（cloud/config.json 的 tuniu.api_key）"}
        if self.executor:
            bp = self._blueprint(category, method, params)
            res = await self.executor(bp)
            if not isinstance(res, dict):
                return {"ok": False, "error": "手机执行返回异常"}
            if not res.get("ok"):
                return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                        "status": res.get("status")}
            payload = self._parse(str(res.get("body") or ""))
        else:
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

    # ══════════════════ ② 买（M 站 m.tuniu.com，需登录 cookie）══════════════════
    def _m_blueprint(self, method: str, url: str, body: dict | None = None,
                     need_cookie: bool = True, form: bool = False) -> dict:
        """M 站蓝图：手机 SkillExecutor 自动补 Cookie 头（credential kind=cookie）。
        form=True → 手机端按表单编码（application/x-www-form-urlencoded）提交（AddOrder 用）。"""
        h = {"User-Agent": M_UA, "Accept": "application/json, text/plain, */*",
             "Referer": "https://m.tuniu.com/"}
        req = {"method": method, "url": url, "headers": h,
               "body": body, "sign_type": "none"}
        if form:
            req["body_type"] = "form"
        return {
            "skill": "tuniu",
            "request": req,
            "credential": ({"kind": "cookie", "target": "tuniu", "needs": ["cookie"]}
                           if need_cookie else {"kind": "none", "target": "tuniu"}),
        }

    async def _m_exec(self, bp: dict) -> dict:
        """执行 M 站蓝图：有 executor 走手机（cookie 由手机凭据库补），否则云端直发降级。"""
        if self.executor:
            res = await self.executor(bp)
            if not isinstance(res, dict):
                return {"ok": False, "error": "手机执行返回异常"}
            if not res.get("ok"):
                return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                        "status": res.get("status")}
            body = str(res.get("body") or "")
            try:
                return json.loads(body or "{}")
            except Exception:
                return {"raw": body[:400], "http": res.get("status")}
        # 云端直发降级（单机测试/无手机通道的 API 入口）
        method = bp["request"]["method"]
        url = bp["request"]["url"]
        req_body = bp["request"].get("body")
        form = bp["request"].get("body_type") == "form"
        try:
            r = requests.request(method, url,
                                 data=req_body if form else None,
                                 json=None if form else req_body,
                                 headers=bp["request"].get("headers"),
                                 cookies=self.cookies, timeout=25, verify=False)
            try:
                return r.json()
            except Exception:
                return {"raw": r.text[:400], "http": r.status_code}
        except Exception as e:
            return {"ok": False, "error": f"途牛 M 站请求失败：{e}"}

    async def set_cookies(self, cookies: dict) -> dict:
        """设置登录 cookie（从浏览器 / passport 登录后获取；手机通道下由手机凭据库提供，本方法为显式设置）。"""
        self.cookies = dict(cookies or {})
        return {"ok": True, "cookies_set": len(self.cookies),
                "note": "手机通道下 Cookie 由手机本地凭据库自动补（本方法仅云端直发降级用）"}

    async def _resolve_train(self, departure: str, arrival: str, date: str) -> dict:
        """私有：下单前从 M 站 ticketList 取车次/席别参数（resId/seatId/price/站点代码）。"""
        dc, ac = CITY_CODES.get(departure, ""), CITY_CODES.get(arrival, "")
        if not (dc and ac):
            return {"ok": False,
                    "error": f"未内置城市代码：{departure}/{arrival}，请在 tuniu_api.CITY_CODES 补充"}
        d = json.dumps({
            "ticketType": 0, "departureCityCode": dc, "arrivalCityCode": ac,
            "departureCityName": departure, "arrivalCityName": arrival,
            "departureDate": date,
        }, ensure_ascii=False, separators=(",", ":"))
        url = f"{M}/api/train/product/ticketList?d={urllib.parse.quote(d)}"
        j = await self._m_exec(self._m_blueprint("GET", url, need_cookie=False))
        data = j.get("data") or {}
        if j.get("errorCode") != 710000:
            return {"ok": False, "error": j.get("msg") or str(j)[:200], "raw": j}
        trains = []
        for t in (data.get("rows") or []):
            seats = [{
                "seatName": s.get("seatName"), "seatId": s.get("seatId"),
                "price": s.get("adultPrice") or s.get("price"),
                "resId": s.get("resId"), "leftNumber": s.get("leftNumber"),
                "seatStatus": s.get("seatStatus"),
            } for s in (t.get("seatDesc") or [])]
            trains.append({
                "trainId": t.get("trainId"), "trainNum": t.get("trainNum"),
                "depart": t.get("departStationName"), "arrive": t.get("destStationName"),
                "departCode": t.get("departStationCode"), "arriveCode": t.get("destStationCode"),
                "departTime": t.get("departDepartTime"), "arriveTime": t.get("destArriveTime"),
                "duration": t.get("duration"), "price_from": t.get("price"),
                "seatDesc": seats,
            })
        return {"ok": True, "count": len(trains), "trains": trains}

    async def submit_order(self, dep: str, arr: str, date: str, train_num: str, seat_name: str,
                           passengers: list, contact_tel: str = "") -> dict:
        """下单创建订单（M 站 AddOrder，⚠️真购票，需登录 cookie）。

        passengers: [{"name","psptId","tel","psptType":1,"birthday":"YYYY-MM-DD","sex":1}]
        → {ok, order_id, order_amount, pay_url}；支付由用户在手机支付宝/途牛 App 完成。
        """
        # 1) 取该车次的座席参数（resId/seatId/price/站点代码）
        sr = await self._resolve_train(dep, arr, date)
        if not sr.get("ok"):
            return sr
        train = next((t for t in sr["trains"] if t["trainNum"] == train_num), None)
        if not train:
            return {"ok": False, "error": f"未找到车次 {train_num}"}
        seat = next((s for s in train["seatDesc"] if seat_name in (s["seatName"] or "")), None)
        if not seat:
            return {"ok": False,
                    "error": f"无席别「{seat_name}」，可选：{[s['seatName'] for s in train['seatDesc']]}"}

        # 2) 组装 AddOrder 参数（字段与 2026-08-07 实测订单 1259153040 一致）
        tourist = [{
            "name": p.get("name"), "tel": p.get("tel"),
            "psptType": p.get("psptType", 1), "psptId": p.get("psptId"),
            "country": None, "birthday": p.get("birthday"),
            "sex": p.get("sex", 1), "isAdult": p.get("isAdult", 1),
            "psptEndDate": None, "isStuDisabledArmyPolice": 0, "stu": None,
        } for p in passengers]
        adult_price = seat["price"] or 0
        body = {
            "trainId": train["trainId"], "trainNumber": train["trainNum"],
            "resourceId": seat["resId"], "seatId": seat["seatId"],
            "isInsCashBack": 0, "departDate": date,
            "adultCount": len(tourist), "childCount": 0,
            "adultPrice": adult_price,
            "ministryRailwaysId": 0,   # 12306 绑定 ID，便捷购票可 0（待实测确认）
            "departureCityCode": CITY_CODES.get(dep, ""), "arrivalCityCode": CITY_CODES.get(arr, ""),
            "departureCityName": dep, "arrivalCityName": arr,
            "departureStations": [train["departCode"]], "departureStationName": train["depart"],
            "arrivalStations": [train["arriveCode"]], "arrivalStationName": train["arrive"],
            "insuranceResourceId": 0, "insurancePrice": 0,
            "acceptStandingTicket": False, "isExcess": 0,
            "contactList": {"name": "", "appellation": "", "email": "", "phone": "",
                            "tel": contact_tel or (passengers[0].get("tel") if passengers else "")},
            "touristList": tourist,
            "isTransferToDispatchTicket": 0,
            "extension": {
                "servicePackageInfo": [{"type": 24, "number": len(tourist)}],  # 便捷购票 +¥10/张
                "appBookInfo": [{"bookType": 5}],
                "voucherInfo": [], "refundInsInfo": [{"hasBuyRefundIns": 0}],
                "stuExtendedInfo": [{"fromStuPassageWay": False}],
            },
            "personalTailorInfo": {"info": ""},
        }
        # d 参数放 form body（body_type=form，手机 SkillExecutor 表单编码；与 2026-08-07 真实抓包一致）
        d = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        url = f"{MAPI}/tcs/gtc/train/order/AddOrder"
        j = await self._m_exec(self._m_blueprint("POST", url,
                                                 body={"d": d}, form=True))
        data = j.get("data") or {}
        # 途牛 AddOrder 成功判定（2026-08-07 实测）：
        #   errorCode=710000 且 data.success；或 errorCode=130000（订单已创建/占座中）且 data.success；
        #   或 data.errorCode=200（订单提交成功）。注意 130000 不是失败，是「订单创建成功」。
        ok = ((j.get("errorCode") in (710000, 130000) and data.get("success"))
              or data.get("errorCode") == 200)
        if ok:
            order_id = data.get("orderId") or data.get("orderNo")
            pay_url = (str(data.get("orderDetailUrl") or "")
                       or str(data.get("payUrl") or data.get("pay_url") or "")
                       or f"{M}/u/order/{order_id}")
            return {
                "ok": True, "order_id": order_id,
                "order_amount": data.get("orderAmount"),
                "pay_url": pay_url,   # 手机打开此页支付
                "raw": j,
            }
        msg = str(j.get("msg") or "")
        # 170001「参数错误」：登录态已有仍参数错 → 下单参数问题，不是登录
        if j.get("errorCode") == 170001 or "参数" in msg:
            logger.warning("[tuniu] AddOrder 参数错误 errorCode=%s msg=%s raw=%s",
                           j.get("errorCode"), msg[:120], str(j)[:300])
            return {"ok": False, "error": (msg or "途牛下单参数错误"), "raw": j}
        # 「已有相同订单正在处理」→ 重复下单拦截（非失败、非登录）
        if "已有相同订单" in msg or "正在处理" in msg or "订单提交成功" in msg:
            return {"ok": True, "order_id": data.get("orderId") or data.get("orderNo"),
                    "duplicate": True, "error": msg, "raw": j}
        # 其它失败（未登录/风控等）→ 触发登录引导（agent._login_tuniu 自动弹内置浏览器登录）
        logger.warning("[tuniu] AddOrder 未成功 errorCode=%s msg=%s raw=%s",
                       j.get("errorCode"), msg[:120], str(j)[:300])
        return {"ok": False, "need_login": True,
                "error": (msg or f"途牛下单未成功（{j.get('errorCode')}），可能未登录，请先登录后重试"), "raw": j}

    async def pay(self, order_id: str, order_type: int = 38) -> dict:
        """返回订单支付入口；pay_url 供 agent 自动 navigate 到内置浏览器支付页。"""
        return {
            "ok": True,
            "order_id": order_id,
            "pay_url": f"{M}/u/order/{order_id}?orderType={order_type}",
            "pay_ways": [
                f"手机打开途牛订单页支付：{M}/u/order/{order_id}?orderType={order_type}",
                "途牛收银台（电脑需支付宝客户端/扫码）：cashier.tuniu.com",
                "手机支付宝 App 内搜索/扫码支付",
            ],
        }

    async def order_detail(self, order_id: str, order_type: int = 38) -> dict:
        """订单详情（M 站 orderDetail，状态/金额/可否支付取消）；支付后确认用。"""
        d = json.dumps({"orderId": str(order_id), "orderType": order_type},
                       ensure_ascii=False, separators=(",", ":"))
        url = f"{M}/api/train/order/orderDetail?d={urllib.parse.quote(d)}"
        j = await self._m_exec(self._m_blueprint("GET", url))
        if j.get("errorCode") in (710000, 130000):
            return {"ok": True, "order": j.get("data"), "raw": j}
        return {"ok": False, "error": j.get("msg") or str(j)[:200], "raw": j}

    async def cancel_order(self, order_id: str, order_type: int = 38) -> dict:
        """退票/取消订单（M 站 newCancelOrder，⚠️真实退票，须用户确认）。

        占座中/未支付订单→取消；已出票订单→按途牛退票规则退票。
        """
        d = json.dumps({"orderId": str(order_id), "orderType": order_type},
                       ensure_ascii=False, separators=(",", ":"))
        url = f"{M}/api/train/order/newCancelOrder?d={urllib.parse.quote(d)}"
        j = await self._m_exec(self._m_blueprint("GET", url))
        if j.get("errorCode") in (710000, 130000):
            return {"ok": True, "data": j.get("data"), "raw": j}
        return {"ok": False, "error": j.get("msg") or str(j)[:200], "raw": j}

    async def order_list(self, page_no: int = 1, page_size: int = 10) -> dict:
        """我的火车票订单列表（M 站 orderList）→ [{orderId, 状态, 车次, 金额, 乘车日期, ...}]。

        2026-08-07 实测：`GET m.tuniu.com/api/train/order/orderList?d={"pageNo":1,"pageSize":10}`
        → data.orderList[]（orderId/orderTime/beginTime/productName/productType/status...）。
        """
        d = json.dumps({"pageNo": int(page_no), "pageSize": int(page_size)},
                       ensure_ascii=False, separators=(",", ":"))
        url = f"{M}/api/train/order/orderList?d={urllib.parse.quote(d)}"
        j = await self._m_exec(self._m_blueprint("GET", url))
        if j.get("errorCode") == 710000:
            return {"ok": True, "orders": (j.get("data") or {}).get("orderList", []), "raw": j}
        return {"ok": False, "error": j.get("msg") or str(j)[:200], "raw": j}


# 便捷入口
api = TuniuAPI()

if __name__ == "__main__":
    import datetime

    async def main():
        tm = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        print("工具列表:", (await api.list_tools("train")).get("ok"))
        r = await api.search_train("南京", "北京", tm)
        if r.get("ok"):
            d = r.get("data")
            if isinstance(d, list):
                for t in d[:3]:
                    print(t.get("trainNum"), t.get("departureTime"), "→", t.get("arrivalTime"),
                          "硬座:", t.get("price", {}).get("yzPrice", ""))
        bp = api.describe_request("search_train", departure="南京", arrival="北京", date=tm)
        print("蓝图:", json.dumps(bp, ensure_ascii=False)[:300])

    asyncio.run(main())
