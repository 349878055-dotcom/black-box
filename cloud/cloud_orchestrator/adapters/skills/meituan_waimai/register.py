"""注册接入：加载同目录 contract.json + api 类 → 导出 REGISTER。

消费端扫描 skills/*/register.py（产出/{id}/ 或样本）。无全局 ADAPTERS。
"""
from __future__ import annotations

import json
import os

from .api.api import MeituanWaimaiAPI

_here = os.path.dirname(os.path.abspath(__file__))
_contract = json.load(open(os.path.join(_here, "contract.json"), encoding="utf-8"))

REGISTER: dict = {
    "id": _contract.get("id", "meituan_waimai"),
    "name": _contract.get("name", "美团外卖"),
    "class": MeituanWaimaiAPI,                 # 函数实现类（api.py）
    "capability": _contract.get("capability", ""),
    "capability_note": _contract.get("capability_note", ""),
    "aliases": _contract.get("aliases", []),   # 别名（美团外卖/点外卖等客户说法命中）
    "flow": _contract.get("flow", []),         # 业务流程图（功能清单）
    # login: 登录配置（method=sms_verify 手机号+验证码），由云端 login_flow 通用编排执行
    "login": _contract.get("login", {}),
    # methods: 方法名 → {desc, need_login, params, keywords, success_ret, error_ret, system_only}
    "methods": {
        m["name"]: {k: v for k, v in m.items() if k != "name"}
        for m in _contract.get("methods", [])
    },
}
