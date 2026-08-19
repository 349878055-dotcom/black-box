"""注册接入：加载 meta/login/methods/payment + api → REGISTER。"""
from __future__ import annotations

import os

from .api.api import GlyyAPI
from .... import load_contract_parts

_here = os.path.dirname(os.path.abspath(__file__))
_c = load_contract_parts(_here)

REGISTER: dict = {
    "id": _c.get("id", "glyy"),
    "name": _c.get("name", "南京鼓楼医院互联网医院"),
    "class": GlyyAPI,
    "schema_version": _c.get("schema_version", "2"),
    "category": _c.get("category", ""),
    "capability": _c.get("capability", ""),
    "capability_note": _c.get("capability_note", ""),
    "deliver": _c.get("deliver", ""),
    "aliases": _c.get("aliases", []),
    "transport": _c.get("transport", ""),
    "ua_profile": _c.get("ua_profile", ""),
    "exec": _c.get("exec") or {},
    "error_map": _c.get("error_map") or {},
    "auth": _c.get("auth") or {},
    "login": _c.get("login") or {},
    "payment": _c.get("payment") or {},
    "rules": _c.get("rules") or [],
    "form": _c.get("form") or [],
    "methods": {
        m["name"]: {k: v for k, v in m.items() if k != "name"}
        for m in _c.get("methods", [])
    },
}
