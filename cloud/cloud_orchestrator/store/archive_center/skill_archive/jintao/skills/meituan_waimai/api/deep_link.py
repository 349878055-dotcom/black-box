"""meituan_waimai · 深链：生成美团 App 订单/点餐 scheme。

路径 B：放弃登录 + 支付。系统不持有登录态、不代下单、不代支付。
交付 = 明文 scheme，壳用系统 Intent / openURL 直接拉起美团 App，进该店点餐页。
客户在美团 App 内自己登录、选菜、确认、付钱。

禁止：丢进 WebView / 系统浏览器当主路径；只给美团首页。
"""
from __future__ import annotations

from urllib.parse import quote

# 美团 App（主交付，用户指定拉起这个）
MEITUAN_SCHEME = "imeituan://www.meituan.com/takeout/food"
MEITUAN_PACKAGE = "com.sankuai.meituan"  # Android Intent package

# 美团外卖独立 App（备选；未装美团、只装了外卖时用）
WAIMAI_SCHEME = "meituanwaimai://waimai.meituan.com/menu"
WAIMAI_PACKAGE = "com.sankuai.meituan.takeoutnew"


class DeepLinkMixin:
    """美团 App 订单链接：明文 scheme，壳原生拉起，直达该店点餐页。"""

    async def generate_order_link(self, poi_id: str = "", poi_id_str: str = "", **kwargs) -> dict:
        """生成美团 App 订单/点餐 scheme → {ok, scheme, package, scheme_waimai, package_waimai, poi_id, poi_id_str}。

        实测（2026-08-13 真机）：美团外卖分享链接用的是字符串 poi_id_str，
        scheme = meituanwaimai://waimai.meituan.com/menu?poi_id_str=...（已验证能唤起 WMRestaurantActivity）。
        主 App imeituan://www.meituan.com/takeout/food?poi_id=...（数字 poi_id，待真机验证）。

        壳：Android Intent(scheme) + package；iOS openURL。禁止走 H5 中间页 / 只给美团首页。
        """
        poi_id = str(poi_id or "").strip()
        poi_id_str = str(poi_id_str or kwargs.get("wm_poi_id_str") or kwargs.get("poi_id_str") or "").strip()
        if not poi_id and not poi_id_str:
            return {"ok": False, "error": "缺 poi_id / poi_id_str（先 search_poi 或从分享链接拿真实店铺 id，禁止编造）"}
        scheme = f"{MEITUAN_SCHEME}?poi_id={quote(poi_id, safe='')}" if poi_id else ""
        # 实测：美团外卖独立 App 用 poi_id_str（字符串店铺标识）
        scheme_waimai = f"{WAIMAI_SCHEME}?poi_id_str={quote(poi_id_str or poi_id, safe='')}"
        return {
            "ok": True,
            "scheme": scheme,
            "package": MEITUAN_PACKAGE,
            "scheme_waimai": scheme_waimai,
            "package_waimai": WAIMAI_PACKAGE,
            "poi_id": poi_id,
            "poi_id_str": poi_id_str or poi_id,
        }
