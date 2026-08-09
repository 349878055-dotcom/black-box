"""南京鼓楼医院互联网医院 · AI 可读 API（Device-as-Proxy，仅手机通道版）。

数据来源：电脑微信小程序真实抓包 + 小程序代码逆向（appid wx74a991a2ae77468d）。
链路已验证：token 有效、查科室 533 个、排班/时段/挂号请求体完整破解。

职责拆分（每个文件干净）：
  _base.py   # 常量 + 基础设施（蓝图/手机执行/解析/统一返回）→ GlyyBase
  login.py   # A 登录：get_graphical_captcha / send_sms / login → LoginMixin
  query.py   # B 查号源：list_depts / list_doctors / get_schedule / online_* → QueryMixin
  register.py# C 挂号 + D 我的就诊 + E 病历/缴费 → RegisterMixin
  api.py     # 入口类 GlyyAPI = GlyyBase + LoginMixin + QueryMixin + RegisterMixin

Device-as-Proxy（docs/改造方案_DeviceAsProxy.md 第 2/3 条）：
  - 云端 = 大脑：组装参数、生成「请求蓝图」、解析响应、编排组合方法；
  - 手机 = 手：经 executor（= bridge.send_skill_request 下发 skill_request）执行蓝图，
    手机真实 IP 直连平台，回传原始响应 skill_result；
  - ⚠️ 2026-08-06 已删除「云端直发降级」：未注入 executor 直接报错（铁律：glyy 禁云端直连）。
"""
from __future__ import annotations

import asyncio
import json

from ._base import GlyyBase
from .login import LoginMixin
from .query import QueryMixin
from .visit import RegisterMixin


class GlyyAPI(GlyyBase, LoginMixin, QueryMixin, RegisterMixin):
    """南京鼓楼医院互联网医院：登录 + 查号源 + 挂号 + 我的就诊 + 病历/缴费（仅手机通道）。"""


if __name__ == "__main__":
    async def main():
        api = GlyyAPI()
        # 仅展示蓝图（真正执行需注入 executor 走手机通道，glyy 禁云端直连）
        bp = api.describe_request("list_depts")
        print("蓝图:", json.dumps(bp, ensure_ascii=False)[:300])
        if not api.executor:
            print("[提示] 未注入 executor，不执行真实请求（glyy 禁云端直连，仅展示蓝图）")

    asyncio.run(main())
