"""meituan_waimai · 查询模块（搜店/店铺/菜单/菜品）。

⚠️ 2026-08-11 真机实测：search 系接口（poiwithfilter/suggest）被 openresty 403 拦；
    首页/homepage、订单等业务接口带登录态 token 走手机通道可通。
"""
from __future__ import annotations

from ._base import BASE, SHANGGOU


class QueryMixin:
    """查询。需 self._get / self._out。"""

    async def homepage(self, **kwargs) -> dict:
        """首页店铺列表 → GET wx-shangou.meituan.com/wxapp/v2/poi/homepage（绕开搜店 403）。

        2026-08-11 还原：homePage = /quickbuy/v2/poi/homepage。
        需位置/城市参数（默认北京，lng/lat 可传覆盖）。返回含 poi_id 的店铺列表（待真机确认结构）。
        """
        params = {"city": kwargs.pop("city", "北京"),
                  "lng": kwargs.pop("lng", "116.4074"),
                  "lat": kwargs.pop("lat", "39.9042"),
                  **kwargs}
        j = await self._get("/wxapp/v2/poi/homepage", params=params,
                            bearer=True, base=SHANGGOU)
        return j

    async def search_poi(self, keyword: str = "", city: str = "北京", **kwargs) -> list:
        """搜店铺 → GET wx-shangou.meituan.com/wxapp/v2/search/v9/poiwithfilter。

        2026-08-11 从 wxapkg 还原（searchPoiNew + quickbuy-domain）：
          quickbuy 域名 = wx-shangou.meituan.com，且 /quickbuy 前缀 → /wxapp；
          query 参数 {keyword, pagesize:20, radius:1000, scenario:"WAIMAI", region:"CITY",
                     orderby:"DISTANCE", city}
        补微信小程序 Referer 过 openresty 403（glyy 同款思路）。
        返回 e.pois = [{poi_id, poi_id_str, name, ...}]（待真机验证结构）。
        """
        from ._base import SHANGGOU
        params = {
            "keyword": keyword,
            "pagesize": 20,
            "radius": 1000,
            "scenario": "WAIMAI",
            "region": "CITY",
            "orderby": "DISTANCE",
            "city": city,
            **kwargs,
        }
        # 微信小程序 Referer（appid wxde8ac0a21135c07d，v1563）——对齐 glyy 过防护思路
        headers = {
            "Referer": "https://servicewechat.com/wxde8ac0a21135c07d/1563/page-frame.html",
            "x5-original-url": "https://wx-shangou.meituan.com/wxapp/v2/search/v9/poiwithfilter",
        }
        j = await self._get("/wxapp/v2/search/v9/poiwithfilter", params=params,
                            bearer=True, base=SHANGGOU, extra_headers=headers)
        # 返回结构：{"pois": [...]} 或 {"data": {"pois": [...]}}，待真机确认
        if isinstance(j, dict) and j.get("pois") is not None:
            return j.get("pois")
        if isinstance(j, dict) and isinstance(j.get("data"), dict) and j["data"].get("pois") is not None:
            return j["data"]["pois"]
        return j

    async def get_poi_info(self, poi_id: str = "", **kwargs) -> dict:
        """店铺信息 → GET wx-shangou.meituan.com/wxapp/v1/poi/info（带登录态）。"""
        j = await self._get("/wxapp/v1/poi/info", {"poi_id": poi_id, **kwargs},
                            bearer=True, base=SHANGGOU)
        return self._out(j, {})

    async def get_product_list(self, poi_id: str = "", **kwargs) -> list:
        """店铺菜单/菜品列表 → GET wx-shangou.meituan.com/wxapp/v1/poi/food（带登录态）。"""
        j = await self._get("/wxapp/v1/poi/food", {"poi_id": poi_id, **kwargs},
                            bearer=True, base=SHANGGOU)
        return self._out(j, [])

    async def get_product_detail(self, product_id: str = "", **kwargs) -> dict:
        """菜品详情 → GET i.waimai.meituan.com/weapp/v7/poi/product/detail（参数待真机验证）。"""
        j = await self._get("/weapp/v7/poi/product/detail", {"product_id": product_id, **kwargs},
                            bearer=False, base=BASE)
        return self._out(j, {})
