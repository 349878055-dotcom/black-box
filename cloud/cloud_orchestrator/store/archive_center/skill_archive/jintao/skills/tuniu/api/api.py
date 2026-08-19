"""途牛 · AI 可读 API（一个 skill 两种能力：查 + 买）。

① 查（途牛官方开放平台 MCP，apiKey，免费，免登录）→ query.py（QueryMixin）
   文档 https://open.tuniu.com/mcp/docs/；JSON-RPC + SSE
   list_tools / search_train / train_detail / search_flight / search_hotel / search_ticket
   —— 官方开放平台，只查询，不能下单（book 无权限）

② 买（途牛 M 站 m.tuniu.com，接口直调，需登录 cookie）→ order.py（OrderMixin）
   resolve_city_code / train_booking_info（原子查询：城市码/车次下单编码）
   → submit_order（AddOrder，原子终结点，乘客直传 touristList）→ pay
   —— 下单创建订单，支付在手机支付宝/途牛 App 完成（电脑无支付宝客户端付不了）
   —— 原子化：submit_order 不再内部自动连串，前置编码由 train_booking_info / resolve_city_code 提供（requires 声明，agent 可自动补齐）

本文件 = 入口类（TuniuAPI = QueryMixin + OrderMixin），职责拆分到 query.py / order.py。

Device-as-Proxy（docs/改造方案_DeviceAsProxy.md）：
  - 云端 = 大脑：组装参数、生成「请求蓝图」、解析响应；
  - 手机 = 手：经 executor（= bridge.send_skill_request 下发 skill_request）执行蓝图，
    手机真实 IP 直连平台，回传原始响应 skill_result；
  - ② M 站蓝图 credential=kind:cookie → 手机 SkillExecutor 从本地凭据库补 Cookie 头（云端不持有登录态）；
  - 未注入 executor 直接报错（禁云端直连）。
"""
from __future__ import annotations

import asyncio
import json
import logging

# 兼容两种包结构：本地 cloud_orchestrator / 云端 cloud.cloud_orchestrator
try:
    from cloud_orchestrator.config import skill_secret
except ImportError:  # pragma: no cover
    from cloud.cloud_orchestrator.config import skill_secret

from .query import QueryMixin
from .order import OrderMixin

logger = logging.getLogger("xiami.tuniu")


class TuniuAPI(QueryMixin, OrderMixin):
    """途牛：① 查（MCP，apiKey，免费）+ ② 买（M 站，cookie，下单/支付）。"""

    def __init__(self, api_key: str | None = None, cookies: dict | None = None,
                 executor=None) -> None:
        # —— ① 查（MCP）——
        self.api_key = api_key or skill_secret("tuniu", "api_key", "")
        # Device-as-Proxy：手机执行通道（async (blueprint) -> {ok,status,headers,body,error}）
        self.executor = executor
        self.headers = {
            "apiKey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # —— ② 买（M 站）——登录态由手机凭据库提供
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
