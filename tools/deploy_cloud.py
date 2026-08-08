#!/usr/bin/env python3
"""
部署 date_utils.py + agent.py 到腾讯云 140.143.144.28 并重启云端服务。

用法（项目根目录）：
    python3 tools/deploy_cloud.py

- 账号/密码：桌面「我的账号密钥/账号密钥汇总.md」第 7 节（ubuntu / Jtao_8505）
- 目标路径：/home/ubuntu/xiami/cloud/cloud_orchestrator/core/ 与 adapters/
- 步骤：上传 → 远端 py_compile 检查 → systemctl restart 重启 → curl 健康检查
- 用 pexpect 自动输密码（无 sshpass 也能用）
- ⚠️ 云端用 systemd 管理（shimeban-cloud.service，Restart=always），
  必须用 systemctl restart（不要 pkill+nohup，会与 systemd 抢端口）
- FILES 可含 core/ 和 adapters/ 下的文件，自动按目录上传
"""
from __future__ import annotations

import os
import sys
import time

import pexpect

HOST = "140.143.144.28"
USER = "ubuntu"
PASS = "Jtao_8505"
REMOTE_BASE = "/home/ubuntu/xiami/cloud/cloud_orchestrator/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根
LOCAL_BASE = os.path.join(ROOT, "cloud", "cloud_orchestrator")
# (子目录, 文件名) 列表 —— 自动定位本地/远端对应子目录
FILES = [
    ("core", "date_utils.py"),
    ("core", "agent.py"),
    ("adapters", "tuniu_api.py"),
    ("adapters", "registry.py"),
    ("channel", "ws.py"),
]


def _ssh(cmd: str, timeout: int = 60) -> tuple[bool, str]:
    """ssh 执行远程命令并自动输密码。返回 (成功?, 输出)。"""
    full = (f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 "
            f"{USER}@{HOST} \"{cmd}\"")
    child = pexpect.spawn(full, timeout=timeout, encoding="utf-8",
                          maxread=65536)
    try:
        i = child.expect([r"[Pp]assword:", r"Permission denied",
                          pexpect.TIMEOUT, pexpect.EOF])
        if i == 0:
            child.sendline(PASS)
        elif i == 1:
            child.close()
            return False, "Permission denied"
        j = child.expect([pexpect.EOF, pexpect.TIMEOUT], timeout=timeout)
        out = (child.before or "")
        # 去掉密码回显等多余行
        return True, out
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        child.close()


def _scp_put(local: str, remote: str, timeout: int = 90) -> tuple[bool, str]:
    """scp 上传并自动输密码。"""
    full = (f"scp -o StrictHostKeyChecking=no -o ConnectTimeout=15 "
            f"{local} {USER}@{HOST}:{remote}")
    child = pexpect.spawn(full, timeout=timeout, encoding="utf-8",
                          maxread=65536)
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


def main() -> int:
    print(f"[1/4] 上传 {len(FILES)} 个文件 → {REMOTE_BASE}")
    for sub, f in FILES:
        local = os.path.join(LOCAL_BASE, sub, f)
        remote = REMOTE_BASE + sub + "/" + f
        if not os.path.isfile(local):
            print(f"  ✗ 本地文件不存在: {local}")
            return 1
        ok, out = _scp_put(local, remote)
        if not ok or "100%" not in out:
            print(f"  ✗ 上传失败 {sub}/{f}: {out[:200]}")
            return 1
        print(f"  ✓ {sub}/{f}")

    print("[2/4] 远端 py_compile 语法检查")
    compile_parts = " ".join(f"{sub}/{f}" for sub, f in FILES)
    ok, out = _ssh("cd %s && python3 -m py_compile %s && echo COMPILE_ALL_OK"
                   % (REMOTE_BASE, compile_parts))
    if not ok or "COMPILE_ALL_OK" not in out:
        print(f"  ✗ 远端语法检查失败: {out[:300]}")
        return 1
    print("  ✓ 语法检查通过")

    print("[3/4] 重启云端服务（sudo systemctl restart）")
    # ubuntu 用户无 systemd 管理权限，需 sudo（密码从 stdin 经 sudo -S 传入）
    ok, out = _ssh("echo %s | sudo -S systemctl restart shimeban-cloud.service 2>&1; "
                   "echo RESTART_EXIT=$?" % PASS)
    print(f"  重启输出: {out.strip()[:160]}")
    time.sleep(8)

    print("[4/4] 健康检查")
    ok, out = _ssh("curl -s http://127.0.0.1:19000/health; "
                   "echo; echo ---JOURNAL---; "
                   "journalctl -u shimeban-cloud.service -n 4 --no-pager 2>/dev/null | tail -4")
    print(out.strip())
    if "status" in out and "ok" in out:
        print("\n✅ 部署成功，云端已重启，health 正常")
        return 0
    print("\n⚠️ health 未见 ok，请查看上方日志")
    return 1


if __name__ == "__main__":
    sys.exit(main())
