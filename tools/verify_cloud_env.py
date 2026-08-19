"""远端检查：云端 Python 环境（numpy/sentence-transformers/torch 是否齐全）。"""
from __future__ import annotations

import base64
import pexpect

HOST = "140.143.144.28"
USER = "ubuntu"
PASS = "Jtao_8505"


def _ssh(cmd: str, timeout: int = 120) -> tuple[bool, str]:
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
import sys
print("python:", sys.executable, sys.version.split()[0])
for m in ["numpy", "sentence_transformers", "torch", "langchain_openai", "langgraph"]:
    try:
        mod = __import__(m)
        v = getattr(mod, "__version__", "?")
        print(f"  OK  {m} == {v}")
    except Exception as e:
        print(f"  MISS {m}: {type(e).__name__}")
'''

if __name__ == "__main__":
    b64 = base64.b64encode(PY.encode("utf-8")).decode("ascii")
    cmd = f"echo {b64} | base64 -d > /tmp/venv.py && python3 /tmp/venv.py"
    ok, out = _ssh(cmd)
    print(out[-3000:] if ok else f"FAILED: {out}")
