"""注册接入：加载 contract.json（功能清单）+ api.py（函数实现）→ 注册到总注册表 registry。

总注册表扫描 skills/*/register.py，取 REGISTER 变量（skill 元数据 + 类）。
"""
from __future__ import annotations

import json
import os

from .api.api import GlyyAPI

_here = os.path.dirname(os.path.abspath(__file__))
_contract = json.load(open(os.path.join(_here, "contract.json"), encoding="utf-8"))

REGISTER: dict = {
    "id": _contract.get("id", "glyy"),
    "name": _contract.get("name", "南京鼓楼医院互联网医院"),
    "class": GlyyAPI,                        # 函数实现类（api.py）
    "capability": _contract.get("capability", ""),
    "capability_note": _contract.get("capability_note", ""),
    "flow": _contract.get("flow", []),       # 业务流程图（功能清单）
    # methods: 方法名 → {desc, need_login, params, keywords, success_ret, error_ret, system_only}
    "methods": {
        m["name"]: {k: v for k, v in m.items() if k != "name"}
        for m in _contract.get("methods", [])
    },
}
