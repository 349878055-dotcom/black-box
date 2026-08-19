"""远端验证（venv）：云端 search 工具是否生效（skill 加载 + 检索候选）。"""
from __future__ import annotations

import base64
import pexpect

HOST = "140.143.144.28"
USER = "ubuntu"
PASS = "Jtao_8505"


def _ssh(cmd: str, timeout: int = 180) -> tuple[bool, str]:
    full = (f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 "
            f"{USER}@{HOST} \"{cmd}\"")
    child = pexpect.spawn(full, timeout=timeout, encoding="utf-8", maxread=65536)
    try:
        i = child.expect([r"[Pp]assword:", r"Permission denied",
                          pexpect.TIMEOUT, pexpect.EOF])
        if i == 0:
            child.sendline(PASS)
        elif i == 1:
            child.close()
            return False, "Permission denied"
        child.expect(pexpect.EOF, timeout=timeout)
        return True, (child.before or "")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        child.close()


PY = r'''
import os, sys
os.chdir("/home/ubuntu/xiami/cloud")
sys.path.insert(0, "/home/ubuntu/xiami")
from cloud.cloud_orchestrator.adapters.registry import ADAPTERS, list_skills
print("== 注册的 skill 签名 ==")
print(sorted(ADAPTERS.keys()))
print("== list_skills ==")
for s in list_skills():
    print(" -", s.get("skill"), "|", s.get("name"), "| 方法数", len(s.get("methods") or []))
print("== search 检索测试 ==")
from cloud.cloud_orchestrator.retrieval.index import get_index
idx = get_index()
print("平台数=", len(idx.platform_items), "方法数=", len(idx.method_items))
for q in ["帮我挂个号", "帮我订张高铁票", "帮我点个外卖"]:
    try:
        note = idx.make_note(q, allowed_skills=None, owner_id="jintao")
        plats = note.get("platforms") or []
        print(f"[{q}] top={note.get('top_skill')} 候选={[p.get('skill') for p in plats]}")
    except Exception as e:
        print(f"[{q}] 异常: {type(e).__name__}: {e}")
'''

if __name__ == "__main__":
    b64 = base64.b64encode(PY.encode("utf-8")).decode("ascii")
    cmd = (f"echo {b64} | base64 -d > /tmp/verify.py && "
           f"/home/ubuntu/xiami/venv/bin/python /tmp/verify.py")
    ok, out = _ssh(cmd)
    print(out[-3000:] if ok else f"FAILED: {out}")
