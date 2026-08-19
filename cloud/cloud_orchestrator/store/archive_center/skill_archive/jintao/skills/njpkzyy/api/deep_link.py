"""njpkzyy · 深链：生成支付宝直达链接，客户点开 → 唤起支付宝 → 直达挂号确认页。

方案（查询 + 支付宝直达）：系统查好号源 + 生成支付宝 scheme/https 直达链接；
客户点链接 → 唤起支付宝 App → 进入「南京市浦口区中医院挂号缴费」小程序挂号确认页 →
客户在支付宝内自己确认挂号并支付（登录=客户自己的支付宝账号，支付=支付宝环境内自做，系统不做代做）。

支付宝 appId 与页面路径从小程序分享链接解码得到，无需任何管理员密钥（个人即可生成直达链接）。
"""
from __future__ import annotations

from urllib.parse import quote

# 南京市浦口区中医院挂号缴费 · 支付宝小程序
ALIPAY_APPID = "2021002127607132"
# 挂号确认页（最终操作页），来自小程序分享链接解码
ALIPAY_PAGE = "pages/public/bookingConfirm/bookingConfirm?__appxPageId=11"
# 原始分享短链（wmslz.com），点开同样可达
ALIPAY_SHORT_LINK = "https://www.wmslz.com/s/7qu50YE81Xb"


def _build_scheme(appid: str = ALIPAY_APPID, page: str = ALIPAY_PAGE) -> str:
    """拼 alipays:// scheme（支付宝 App 内直接拉起）。page 里的 / ? 需 URL 编码（与官方分享链接一致）。"""
    page_enc = quote(page, safe="")
    return f"alipays://platformapi/startapp?appId={appid}&page={page_enc}"


class DeepLinkMixin:
    """支付宝直达链接：生成 scheme + https 可点链接，直达挂号确认页。"""

    async def generate_deep_link(self, appid: str = ALIPAY_APPID, page: str = ALIPAY_PAGE) -> dict:
        """生成支付宝直达链接 → {ok, scheme, https_link, short_link, appid, page}。

        无需任何密钥；https_link 可在任意手机浏览器打开（装了支付宝则唤起 App，否则落支付宝 H5）。
        """
        scheme = _build_scheme(appid, page)
        https_link = f"https://render.alipay.com/p/s/i/?scheme={quote(scheme, safe='')}"
        return {
            "ok": True,
            "scheme": scheme,
            "https_link": https_link,
            "short_link": ALIPAY_SHORT_LINK,
            "appid": appid,
            "page": page,
        }
