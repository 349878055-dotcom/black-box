# skill 档案：按人分目录，每人下面挂完整 skill 包（含对接）。
from __future__ import annotations

import json
import os


def load_contract_parts(skill_dir: str) -> dict:
    """读某 skill 的契约（强制拆分文件，放在与 api/ 平行的 contract/ 子目录）。

    contract/meta.json    平台说明（id/name/capability/aliases/site/notes…）
    contract/login.json   登录方案 + auth
    contract/methods.json 方法数组
    contract/payment.json 交付/支付
    """
    cdir = os.path.join(skill_dir, "contract")

    def _rd(name: str, default):
        p = os.path.join(cdir, name)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return default
        return default

    meta = _rd("meta.json", {}) or {}
    login = _rd("login.json", {}) or {}
    methods = _rd("methods.json", {}) or {}
    payment = _rd("payment.json", {}) or {}
    # form.json：跨轮表单记忆登记表（2026-08-20）——需要收集客户信息的 skill
    # 都应带 form（customer 字段），让 ask_user 回答自动存进跨轮状态、下次自动补参，
    # 避免跨轮/续跑时模型反复问已给信息（如途牛反复问「出发城市」）。
    form = _rd("form.json", {}) or {}
    return {**meta, **login, **methods, **payment, **form}
