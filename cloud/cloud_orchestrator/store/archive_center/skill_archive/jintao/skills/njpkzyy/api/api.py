"""南京市浦口区中医院 · 公开查询 + 支付宝直达链接。

数据来源：后端 hzfw.njpkzyy.com:18086（公开 HTTP API，普通 UA + 签名可访问）。

职责拆分：
  _base.py   # 常量 + 手机通道 GET 蓝图 + 签名占位符 + 统一返回 → NjpkzyyBase
  query.py   # 查号源（科室/医生/排班/日期/支付渠道）→ QueryMixin
  deep_link.py  # 支付宝直达链接（scheme + https，无需密钥）→ DeepLinkMixin
  api.py     # 入口 NjpkzyyAPI = NjpkzyyBase + QueryMixin + DeepLinkMixin

不做登录/支付代做——登录=客户自己的支付宝账号，支付=支付宝环境内自做；
只交付「查询 + 支付宝直达链接」，客户点开唤起支付宝 App 直达挂号确认页，自行确认挂号并支付。
"""
from __future__ import annotations

from ._base import NjpkzyyBase
from .deep_link import DeepLinkMixin
from .query import QueryMixin


class NjpkzyyAPI(NjpkzyyBase, QueryMixin, DeepLinkMixin):
    """浦口中医院：公开查询（科室/排班/日期/支付渠道）+ 支付宝直达挂号确认页。"""


if __name__ == "__main__":
    import asyncio

    async def main():
        api = NjpkzyyAPI()
        if not api.executor:
            print("[提示] 未注入 executor，不执行真实请求（禁云端直连，仅展示深链）")
        print("支付宝直达链接:", await api.generate_deep_link())

    asyncio.run(main())
