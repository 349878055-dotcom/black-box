"""美团外卖 · AI 可读 API（Device-as-Proxy，仅手机通道版）。

数据来源：微信小程序 wxapkg 解包（appid wxde8ac0a21135c07d v1563）。
登录：手机号+验证码（passport.meituan.com /api/v3/account/mobileloginapply|mobilelogin）。
业务：i.waimai.meituan.com（搜店/菜单/购物车/下单/订单/地址）。

职责拆分（每个文件干净）：
  _base.py # 常量 + 基础设施（蓝图/手机执行/解析/统一返回）→ MeituanWaimaiBase
  login.py # A 登录：mobileloginapply / mobilelogin / refresh_token → LoginMixin
  query.py # B 查询：搜店/店铺/菜单/菜品 → QueryMixin
  order.py # C 购物车+下单+订单/取消 → OrderMixin
  api.py   # 入口类 MeituanWaimaiAPI = Base + Login + Query + Order

Device-as-Proxy：云端组装蓝图 → 手机直连 → 回传 skill_result → 云端解析。
⚠️ 未注入 executor 直接报错（禁云端直连，与 glyy/njpkzyy 同铁律）。
⚠️ 骨架版：参数/请求头/签名待真机验证（禁 mock，以真实响应为准）。
"""
from __future__ import annotations

import asyncio
import json

from ._base import BASE, LOGIN_BASE, SHANGGOU, MeituanWaimaiBase
from .login import LoginMixin
from .order import OrderMixin
from .query import QueryMixin


class MeituanWaimaiAPI(MeituanWaimaiBase, LoginMixin, QueryMixin, OrderMixin):
    """美团外卖：搜店/菜单 + 手机号验证码登录 + 下单 + 查单/取消（仅手机通道）。"""

    # 单请求方法映射：method -> (path_template, http_method, 需要bearer, base)
    _REQUEST_MAP: dict[str, tuple] = {
        # B 查询 —— 2026-08-11 还原到 wx-shangou /wxapp 前缀，均需登录态(带 token)
        "homepage": ("/wxapp/v2/poi/homepage", "GET", True, SHANGGOU),
        "search_poi": ("/wxapp/v2/search/v9/poiwithfilter", "GET", True, SHANGGOU),
        "get_poi_info": ("/wxapp/v1/poi/info", "GET", True, SHANGGOU),
        "get_product_list": ("/wxapp/v1/poi/food", "GET", True, SHANGGOU),
        "get_product_detail": ("/weapp/v7/poi/product/detail", "GET", False, BASE),
        # C 购物车（需登录）
        "get_cart_info": ("/weapp/v1/multiplecart/allcartinfo", "GET", True, BASE),
        "sync_cart": ("/weapp/v1/multiplecart/syncfood", "POST", True, BASE),
        # C 地址（需登录）
        "get_address_list": ("/user/address/getaddr", "GET", True, BASE),
        # C 下单（需登录）
        "preview_order": ("/order/preview/container", "GET", True, BASE),
        "update_order_container": ("/order/update/container", "POST", True, BASE),
        "submit_order": ("/order/submit", "POST", True, BASE),
        # D 订单（需登录，2026-08-11 还原到 wx-shangou /wxapp 前缀）
        "get_orders": ("/wxapp/v1/order/getuserorders", "GET", True, SHANGGOU),
        "get_order_detail": ("/wxapp/v1/order/detail", "GET", True, SHANGGOU),
        "cancel_order": ("/wxapp/v1/order/cancel", "POST", True, SHANGGOU),
    }


if __name__ == "__main__":
    async def main():
        api = MeituanWaimaiAPI()
        # 仅展示蓝图（真正执行需注入 executor 走手机通道，meituan_waimai 禁云端直连）
        bp = api.describe_request("get_poi_info", poi_id="123")
        print("蓝图:", json.dumps(bp, ensure_ascii=False)[:400])
        if not api.executor:
            print("[提示] 未注入 executor，不执行真实请求（meituan_waimai 禁云端直连，仅展示蓝图）")

    asyncio.run(main())
