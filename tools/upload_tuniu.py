"""上传修好的 tuniu api 文件到云端（修复 cloud_orchestrator import 兼容）。

用法：python3 tools/upload_tuniu.py
"""
from __future__ import annotations

import os
import pexpect

HOST = "140.143.144.28"
USER = "ubuntu"
PASS = "Jtao_8505"
REMOTE_DIR = "/home/ubuntu/xiami/cloud/cloud_orchestrator/store/archive_center/skill_archive/jintao/skills/tuniu/api"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DIR = os.path.join(
    ROOT, "cloud", "cloud_orchestrator", "store", "archive_center",
    "skill_archive", "jintao", "skills", "tuniu", "api",
)

FILES = ["query.py", "api.py"]


def _scp(local: str, remote: str, timeout: int = 90) -> tuple[bool, str]:
    full = (f"scp -o StrictHostKeyChecking=no -o ConnectTimeout=15 "
            f"{local} {USER}@{HOST}:{remote}")
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


def _ssh(cmd: str, timeout: int = 90) -> tuple[bool, str]:
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


if __name__ == "__main__":
    ok, _ = _ssh(f"mkdir -p '{REMOTE_DIR}'")
    print("远端目录就绪" if ok else "远端目录创建失败")
    for f in FILES:
        local = os.path.join(LOCAL_DIR, f)
        ok, out = _scp(local, f"{REMOTE_DIR}/{f}")
        print(f"  {'✓' if ok else '✗'} {f} {out[:120]}")
    # 远端 py_compile 验证
    ok, out = _ssh(f"cd {REMOTE_DIR} && /home/ubuntu/xiami/venv/bin/python -m py_compile {FILES[0]} {FILES[1]} && echo TUNIU_COMPILE_OK")
    print("远端语法:", "OK" if "TUNIU_COMPILE_OK" in out else out[-300:])
