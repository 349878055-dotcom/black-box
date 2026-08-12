#!/usr/bin/env python3
"""检查美团 skill 一致性：本地 vs 工作台3.0 vs 远程。"""
import hashlib
import os
import sys
sys.path.insert(0, ".")
from tools.deploy_agent_glyy import _ssh

LOCAL = "cloud/cloud_orchestrator/adapters/skills/meituan_waimai"
WB_SRC = "/home/jintao/桌面/工作台3.0/skills/meituan_waimai"
WB_OUT = "/home/jintao/桌面/工作台3.0/产出/meituan_waimai"

FILES = ["contract.json", "register.py", "api/api.py", "api/_base.py",
         "api/query.py", "api/login.py", "api/order.py", "api/__init__.py", "docs/README.md"]


def md5(p):
    try:
        return hashlib.md5(open(p, "rb").read()).hexdigest()[:8]
    except Exception:
        return "无"


print("=== 本地 vs 工作台3.0 (md5 前8位) ===")
print(f"{'文件':<20}{'本地':<10}{'源':<10}{'产出':<10} 说明")
for f in FILES:
    a = md5(os.path.join(LOCAL, f))
    b = md5(os.path.join(WB_SRC, f))
    c = md5(os.path.join(WB_OUT, f))
    note = ""
    if a != b and a != c:
        note = "⚠️ 本地与工作台不一致（可能是我加了 login / 或本地更新）"
    elif a == c and a != b:
        note = "本地=产出"
    elif a == b and a != c:
        note = "本地=源"
    print(f"{f:<20}{a:<10}{b:<10}{c:<10} {note}")

print("\n=== 本地 login 配置检查 ===")
with open(os.path.join(LOCAL, "contract.json"), encoding="utf-8") as f:
    import json
    d = json.load(f)
    lg = d.get("login", {})
    print("本地 contract.login.method:", lg.get("method"))
    print("本地 contract.login.steps:", list((lg.get("steps") or {}).keys()))
with open(os.path.join(LOCAL, "register.py"), encoding="utf-8") as f:
    print("本地 register.py 含 login 透传:", '"login": _contract.get("login"' in f.read())

print("\n=== 远程一致性 ===")
ok, out = _ssh("cd /home/ubuntu/xiami/cloud/cloud_orchestrator/adapters/skills/meituan_waimai && md5sum contract.json register.py | cut -c1-8")
print("远程 contract/register md5:", out.strip())
