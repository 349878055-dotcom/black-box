"""注册接入：加载同目录 contract.json + api 类 → 导出 REGISTER。

消费端扫描 skills/*/register.py。无全局 ADAPTERS。不做登录编排。
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
    "class": MeituanWaimaiAPI,
    "capability": _contract.get("capability", ""),
    "capability_note": _contract.get("capability_note", ""),
    "aliases": _contract.get("aliases", []),
    "flow": _contract.get("flow", []),
    "methods": {
        m["name"]: {k: v for k, v in m.items() if k != "name"}
        for m in _contract.get("methods", [])
    },
}
