"""meituan_waimai · 查询模块（搜店/店铺/菜单/菜品）。不持有登录态。

search 系可能被 403；可改 homepage。poi_id 给 generate_order_link 拼美团 App scheme。
"""
from __future__ import annotations

from ._base import BASE, SHANGGOU


class QueryMixin:
    """查询。需 self._get / self._out。全部免登录。"""

    async def homepage(self, **kwargs) -> dict:
        """首页店铺列表 → GET wx-shangou.meituan.com/wxapp/v2/poi/homepage。"""
        params = {"city": kwargs.pop("city", "北京"),
                  "lng": kwargs.pop("lng", "116.4074"),
                  "lat": kwargs.pop("lat", "39.9042"),
                  **kwargs}
        return await self._get("/wxapp/v2/poi/homepage", params=params,
                               bearer=False, base=SHANGGOU)

    async def search_poi(self, keyword: str = "", city: str = "北京", **kwargs) -> list:
        """搜店铺 → GET wx-shangou.meituan.com/wxapp/v2/search/v9/poiwithfilter。"""
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
        j = await self._get("/wxapp/v2/search/v9/poiwithfilter", params=params,
                            bearer=False, base=SHANGGOU)
        if isinstance(j, dict) and j.get("pois") is not None:
            return j.get("pois")
        if isinstance(j, dict) and isinstance(j.get("data"), dict) and j["data"].get("pois") is not None:
            return j["data"]["pois"]
        return j

    async def get_poi_info(self, poi_id: str = "", **kwargs) -> dict:
        """店铺信息 → GET wx-shangou.meituan.com/wxapp/v1/poi/info。"""
        j = await self._get("/wxapp/v1/poi/info", {"poi_id": poi_id, **kwargs},
                            bearer=False, base=SHANGGOU)
        return self._out(j, {})

    async def get_product_list(self, poi_id: str = "", **kwargs) -> list:
        """店铺菜单 → GET wx-shangou.meituan.com/wxapp/v1/poi/food。"""
        j = await self._get("/wxapp/v1/poi/food", {"poi_id": poi_id, **kwargs},
                            bearer=False, base=SHANGGOU)
        return self._out(j, [])

    async def get_product_detail(self, product_id: str = "", **kwargs) -> dict:
        """菜品详情 → GET i.waimai.meituan.com/weapp/v7/poi/product/detail。"""
        j = await self._get("/weapp/v7/poi/product/detail", {"product_id": product_id, **kwargs},
                            bearer=False, base=BASE)
        return self._out(j, {})
