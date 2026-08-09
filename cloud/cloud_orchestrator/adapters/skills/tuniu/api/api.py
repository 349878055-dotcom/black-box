"""途牛 · AI 可读 API（一个 skill 两种能力：查 + 买）。

① 查（途牛官方开放平台 MCP，apiKey，免费，免登录）→ query.py（QueryMixin）
   文档 https://open.tuniu.com/mcp/docs/；JSON-RPC + SSE
   list_tools / search_train / train_detail / search_flight / search_hotel / search_ticket
   —— 官方开放平台，只查询，不能下单（book 无权限）

② 买（途牛 M 站 m.tuniu.com，接口直调，需登录 cookie）→ order.py（OrderMixin）
   set_cookies → submit_order（AddOrder，乘客直传 touristList，免网页"添加乘客"弹窗）→ pay
   —— 下单创建订单，支付在手机支付宝/途牛 App 完成（电脑无支付宝客户端付不了）

本文件 = 入口类（TuniuAPI = QueryMixin + OrderMixin），职责拆分到 query.py / order.py。

Device-as-Proxy（docs/改造方案_DeviceAsProxy.md）：
  - 云端 = 大脑：组装参数、生成「请求蓝图」、解析响应；
  - 手机 = 手：经 executor（= bridge.send_skill_request 下发 skill_request）执行蓝图，
    手机真实 IP 直连平台，回传原始响应 skill_result；
  - ② M 站蓝图 credential=kind:cookie → 手机 SkillExecutor 从本地凭据库补 Cookie 头（云端不持有登录态）；
  - 未注入 executor 时自动降级为旧「云端直发」（兼容单机测试）。
"""
from __future__ import annotations

import asyncio
import json
import logging

from .....config import get

from .query import QueryMixin
from .order import OrderMixin

logger = logging.getLogger("xiami.tuniu")


class TuniuAPI(QueryMixin, OrderMixin):
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
