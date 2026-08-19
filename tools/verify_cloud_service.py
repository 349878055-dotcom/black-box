"""远端检查：云端服务实际用的 Python / venv / 依赖。"""
from __future__ import annotations

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


if __name__ == "__main__":
    # 1) systemd 服务定义（ExecStart 用什么 python）
    cmd = ("systemctl cat shimeban-cloud.service 2>/dev/null | grep -E 'ExecStart|WorkingDirectory|Environment'; "
           "echo ---VENVS---; "
           "ls -d /home/ubuntu/*/bin/python* /home/ubuntu/.venv*/bin/python* 2>/dev/null; "
           "ls -d /home/ubuntu/xiami/venv/bin/python* 2>/dev/null; "
           "find /home/ubuntu -maxdepth 3 -name 'activate' 2>/dev/null | head")
    ok, out = _ssh(cmd)
    print("== systemd ExecStart / venv 探测 ==")
    print(out[-2500:] if ok else f"FAILED: {out}")
