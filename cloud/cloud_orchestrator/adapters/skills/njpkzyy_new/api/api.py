"""南京市浦口区中医院挂号 · AI 可读 API（Device-as-Proxy，仅手机通道版）。

数据来源：电脑微信小程序真实抓包（appid wxca05bc9d9f69226c，后端 hzfw.njpkzyy.com:18086）。
链路已验证：sign 签名、科室两级结构、排班/在线号/挂号请求体完整破解。

职责拆分（每个文件干净）：
  _base.py  # 常量 + 基础设施（蓝图/手机执行/解析/统一返回）→ NjpkzyyNewBase
  query.py  # B 查号源：list_depts / list_doctors / 排班 / 在线号 → QueryMixin
  login.py  # A 登录：微信授权登录（真人配合）→ LoginMixin
  visit.py  # C 挂号 + D 就诊/订单 → VisitMixin
  api.py    # 入口类 NjpkzyyNewAPI = NjpkzyyNewBase + QueryMixin + LoginMixin + VisitMixin

Device-as-Proxy（docs/改造方案_DeviceAsProxy.md 第 2/3 条）：
  - 云端 = 大脑：组装参数、生成「请求蓝图」、解析响应、编排组合方法；
  - 手机 = 手：经 executor（= bridge.send_skill_request 下发 skill_request）执行蓝图，
    手机真实 IP 直连平台，回传原始响应 skill_result；
  - ⚠️ 禁云端直连（与 glyy 同铁律）：未注入 executor 直接报错。
  - 签名 sign_type="glyy_sha1_md5"（SHA1(MD5(appKey+timestamp+nonce))），与手机端完全一致。
"""
from __future__ import annotations

import asyncio
import json

from ._base import (AGENT_ID, NjpkzyyNewBase, ONLINE_AGENT_ID)
from .login import LoginMixin
from .query import QueryMixin
from .visit import VisitMixin


class NjpkzyyNewAPI(NjpkzyyNewBase, QueryMixin, LoginMixin, VisitMixin):
    """南京市浦口区中医院挂号：查号源 + 微信授权登录 + 在线挂号 + 就诊/订单（仅手机通道）。"""

    # 单请求方法映射：method -> (path_template, http_method, 需要bearer, agent_id)
    _REQUEST_MAP: dict[str, tuple] = {
        # B 查号源（公开，普通 agent_id）
        "list_depts": ("/api/public/basic/v3/depts", "GET", False, AGENT_ID),
        "list_noon_codes": ("/api/public/v3/noon_code", "GET", False, AGENT_ID),
        "list_dept_doctors": ("/api/public/v3/dept/doctor/{dept_code}", "GET", False, AGENT_ID),
        "get_available_dates": ("/api/public/v3/schedule/check", "GET", False, AGENT_ID),
        "get_schedule": ("/api/public/v3/schedule", "GET", False, AGENT_ID),
        "list_notices": ("/api/cms/news/category/3912", "GET", False, AGENT_ID),
        "get_notice_detail": ("/api/cms/news/{news_id}", "GET", False, AGENT_ID),
        # B2 在线号（公开，但必须 ONLINE_AGENT_ID）
        "judge_online": ("/api/public/v3/schedule/online/judge", "GET", False, ONLINE_AGENT_ID),
        "get_schedule_detail": ("/api/public/v3/schedule/online/detail", "GET", False, ONLINE_AGENT_ID),
        "get_pay_channels": ("/api/public/v3/pay_channel", "GET", False, ONLINE_AGENT_ID),
        # D 就诊/订单（需登录）
        "get_medical_card": ("/api/user/medical_card", "GET", True, AGENT_ID),
        "get_order": ("/api/order/order/v2/order/{order_id}", "GET", True, AGENT_ID),
        "get_order_goods": ("/api/public/order/goods/detail", "GET", True, ONLINE_AGENT_ID),
    }


if __name__ == "__main__":
    async def main():
        api = NjpkzyyNewAPI()
        # 仅展示蓝图（真正执行需注入 executor 走手机通道，njpkzyy_new 禁云端直连）
        bp = api.describe_request("list_depts")
        print("蓝图:", json.dumps(bp, ensure_ascii=False)[:400])
        if not api.executor:
            print("[提示] 未注入 executor，不执行真实请求（njpkzyy_new 禁云端直连，仅展示蓝图）")

    asyncio.run(main())
