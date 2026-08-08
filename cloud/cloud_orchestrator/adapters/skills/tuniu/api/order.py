"""途牛 · M 站交易模块（m.tuniu.com，需登录 cookie）。

负责「买」：submit_order（AddOrder，乘客直传 touristList，免网页"添加乘客"弹窗）→ pay
（支付拉起支付宝 App）→ order_detail / order_list（订单确认/查询）→ cancel_order（退票）。
走手机通道（executor，cookie 由手机凭据库补）或云端直发降级。

关键点（2026-08-07 实测，AddOrder 下单成功）：
- 下单必须登录（cookie：isLogined/ssoUser/muser/tuniuuser_id）；
- AddOrder 成功判定：errorCode=710000/130000 且 data.success，或 data.errorCode=200；
- 已出票订单途牛网页无自助退票（平台限制）→ 需客服/火车站窗口。
"""
from __future__ import annotations

import json
import logging
import urllib.parse

import requests

logger = logging.getLogger("xiami.tuniu")

M = "https://m.tuniu.com"                  # ② M 站（网页）
MAPI = "https://api.tuniu.com"             # ② M 站接口
CITY_CODES = {"上海": "2500", "苏州": "1615"}  # 途牛城市代码（实测确认；其余待补）
M_UA = ("Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")


class OrderMixin:
    """M 站交易（下单/支付/订单/退票）。需 self.executor / self.cookies。"""

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
                    "error": f"未内置城市代码：{departure}/{arrival}，请在 skills/tuniu/order.py 的 CITY_CODES 补充"}
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
        """返回订单支付入口；pay_url 供 agent 自动 navigate 到内置浏览器支付页（拉起支付宝）。"""
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
        """订单详情（M 站 orderDetail，状态/金额/可否支付取消/出票）；支付后确认用。"""
        d = json.dumps({"orderId": str(order_id), "orderType": order_type},
                       ensure_ascii=False, separators=(",", ":"))
        url = f"{M}/api/train/order/orderDetail?d={urllib.parse.quote(d)}"
        j = await self._m_exec(self._m_blueprint("GET", url))
        if j.get("errorCode") in (710000, 130000):
            return {"ok": True, "order": j.get("data"), "raw": j}
        return {"ok": False, "error": j.get("msg") or str(j)[:200], "raw": j}

    async def cancel_order(self, order_id: str, order_type: int = 38) -> dict:
        """退票/取消订单（M 站 newCancelOrder，⚠️真实退票，须用户确认）。

        占座中/未支付订单→取消；已出票订单→途牛网页无自助退票（平台限制），需客服/火车站窗口。
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
