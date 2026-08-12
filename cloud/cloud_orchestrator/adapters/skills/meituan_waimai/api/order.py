"""meituan_waimai · 购物车/下单/订单模块（需手机号验证码登录）。

购物车：sync_cart / get_cart_info；地址：get_address_list；
下单：preview_order（结算预览）→ update_order_container（更新结算）→ submit_order（提交 ⚠️真操作）；
订单：get_orders / get_order_detail / cancel_order。
⚠️ 请求参数/请求体待真机验证；真下单/取消有副作用，调用前须用户确认。
"""
from __future__ import annotations

from ._base import BASE


class OrderMixin:
    """购物车/下单/订单（需登录）。需 self._get / self._post / self._out / self.executor / self._blueprint / self._exec。"""

    # ═════════════ 购物车 ═════════════

    async def sync_cart(self, **kwargs) -> dict:
        """同步购物车/加购 → POST /weapp/v1/multiplecart/syncfood（body 待真机验证：poi_id+foods[]）。"""
        j = await self._post("/weapp/v1/multiplecart/syncfood", body=dict(kwargs),
                             bearer=True, base=BASE)
        return self._out(j, {})

    async def get_cart_info(self, **kwargs) -> dict:
        """购物车信息 → GET /weapp/v1/multiplecart/allcartinfo（参数待真机验证）。"""
        j = await self._get("/weapp/v1/multiplecart/allcartinfo", kwargs or None,
                            bearer=True, base=BASE)
        return self._out(j, {})

    # ═════════════ 地址（下单前置）═════════════

    async def get_address_list(self, **kwargs) -> list:
        """收货地址列表 → GET /user/address/getaddr（参数待真机验证）→ [{address_id, detail, ...}]。"""
        j = await self._get("/user/address/getaddr", kwargs or None, bearer=True, base=BASE)
        return self._out(j, [])

    # ═════════════ 下单 ═════════════

    async def preview_order(self, **kwargs) -> dict:
        """结算预览 → GET /order/preview/container（参数待真机验证：poi_id/address_id）。"""
        j = await self._get("/order/preview/container", kwargs or None, bearer=True, base=BASE)
        return self._out(j, {})

    async def update_order_container(self, **kwargs) -> dict:
        """更新结算 → POST /order/update/container（改地址/备注/餐具等，body 待真机验证）。"""
        j = await self._post("/order/update/container", body=dict(kwargs),
                             bearer=True, base=BASE)
        return self._out(j, {})

    async def submit_order(self, **kwargs) -> dict:
        """提交订单 ⚠️真操作有副作用，调用前须用户确认 → POST /order/submit。

        请求体（wxapkg order-submit-param.js 还原，2026-08-11）：
          {
            "wxapp_base_data": "<风控：risk-param.js + jsguard 设备指纹，手机端生成>",
            "data": {
              "wm_poi_id": "<店铺id>", "poi_id_str": "<店铺id字符串>",
              "foodlist": [{id, attrs, count, ...}],     # 购物车菜品
              "user_id": "<用户id>", "wm_order_pay_type": "2",
              "recipient_name/address/phone/gender/house_number": "<收货人>",
              "addr_id": "<地址id>", "addr_longitude/latitude": "<坐标>",
              "caution": "<备注>", "token": "<购物车token>",
              "coupon_view_id": "<优惠券id>", "coupon_code": "", ...
            },
            "foodlist": "<同 data.foodlist>"
          }
        前置依赖：购物车(foodlist) + 地址(recipient_*) + 风控(wxapp_base_data)。
        ⚠️ 下单接口有双版本：/order/submit 与 /weapp/v1/order/submit（wxapkg 接口表两者都有，
        真机验证确认用哪个后固定）。返回订单号/支付信息；支付在手机端完成。
        """
        if not self.executor:
            return {"ok": False, "error": "meituan_waimai 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint("/order/submit", body=dict(kwargs), bearer=True,
                             method="POST", base=BASE)
        return await self._exec(bp)

    # ═════════════ 订单 ═════════════

    async def get_orders(self, page: int = 0, size: int = 10, **kwargs) -> list:
        """订单列表 → GET wx-shangou.meituan.com/wxapp/v1/order/getuserorders。

        2026-08-11 从 wxapkg 还原：orders = /quickbuy/v1/order/getuserorders，quickbuy→wxapp。
        浏览器实测返回 {"code":9999,"msg":"unknown error"}（缺登录态）；带 token 待真机验证。
        """
        from ._base import SHANGGOU
        j = await self._get("/wxapp/v1/order/getuserorders", {"page": page, "size": size, **kwargs},
                            bearer=True, base=SHANGGOU)
        return self._out(j, [])

    async def get_order_detail(self, order_id: str = "", **kwargs) -> dict:
        """订单详情 → GET /order/detail（参数待真机验证：order_id）。"""
        j = await self._get("/order/detail", {"order_id": order_id, **kwargs},
                            bearer=True, base=BASE)
        return self._out(j, {})

    async def cancel_order(self, order_id: str = "", **kwargs) -> dict:
        """取消订单 ⚠️有副作用 → POST /order/cancel（body 待真机验证：order_id）。"""
        j = await self._post("/order/cancel", body={"order_id": order_id, **kwargs},
                             bearer=True, base=BASE)
        return self._out(j, {})
