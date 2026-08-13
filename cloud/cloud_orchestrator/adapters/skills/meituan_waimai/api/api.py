"""美团外卖 · 查询 + 美团 App 订单链接（路径 B）。

探路：微信小程序 wxapkg / H5。交付：imeituan:// 拉起美团 App。
不做登录/下单/支付代做——登录和支付都在美团 App 内客户自做。

职责拆分：
  _base.py      # 常量 + 手机通道查询基础设施 → MeituanWaimaiBase
  query.py      # 搜店/店铺/菜单/菜品 → QueryMixin
  deep_link.py  # 美团 App 订单 scheme → DeepLinkMixin
  api.py        # 入口 MeituanWaimaiAPI = Base + Query + DeepLink
"""
from __future__ import annotations

import json

from ._base import BASE, SHANGGOU, MeituanWaimaiBase
from .deep_link import DeepLinkMixin
from .query import QueryMixin


class MeituanWaimaiAPI(MeituanWaimaiBase, QueryMixin, DeepLinkMixin):
    """美团外卖：查店/菜单 + 生成美团 App 订单链接（路径 B，不持有登录态）。"""

    _REQUEST_MAP: dict[str, tuple] = {
        "homepage": ("/wxapp/v2/poi/homepage", "GET", False, SHANGGOU),
        "search_poi": ("/wxapp/v2/search/v9/poiwithfilter", "GET", False, SHANGGOU),
        "get_poi_info": ("/wxapp/v1/poi/info", "GET", False, SHANGGOU),
        "get_product_list": ("/wxapp/v1/poi/food", "GET", False, SHANGGOU),
        "get_product_detail": ("/weapp/v7/poi/product/detail", "GET", False, BASE),
    }


if __name__ == "__main__":
    api = MeituanWaimaiAPI()
    print("订单链接示例:", json.dumps(api.generate_order_link(poi_id="示例勿用"), ensure_ascii=False))
