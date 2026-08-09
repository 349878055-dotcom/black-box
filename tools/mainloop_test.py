#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主循环（MasterAgent → Agent.handle LLM+工具循环）自动化测试脚本。

用法：
  python3 tools/mainloop_test.py            # 跑内置默认话题组（仅验证连通）
  python3 tools/mainloop_test.py -m "现在几点了"
  python3 tools/mainloop_test.py --multi    # 跑多轮记忆话题（同一会话连续两句）

工作方式（本地仅测试验证，绝不充当云端运行时）：
  1. 用手机 App 登录态（access token，必要时 refresh 续期）调腾讯云 API
  2. POST /api/v1/chat 提交话题 → 主循环异步处理
  3. 轮询 GET /api/v1/task 直到 done/failed/waiting_user/超时
  4. 遇到 waiting_user（ask_user 需用户配合：验证码/确认）→ 等待 wait_user 秒后 cancel，
     记录 ask 内容供人工在手机 App 上配合。

环境变量 / 常量：见下方 ACCESS/REFRESH/BASE（本机仅供开发自测）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

# ── 测试账号（登录态一次性 30 天：refresh_token 有效期 30 天，脚本登录后自动持久化复用）──
BASE = "http://140.143.144.28"
# 优先用本地持久化的登录态；没有或失效则用 EMAIL/PASSWORD 自动登录并落盘
ACCESS = ""
REFRESH = ""
EMAIL = ""
PASSWORD = ""
# 登录态持久化文件（access/refresh/email，30 天有效期内复用，避免反复登录）
TOKEN_FILE = "/tmp/xiami_test_token.json"

def _load_or_login() -> None:
    """加载本地登录态；无/失效 → 用账号密码登录并落盘（refresh 30 天，可复用）。"""
    global ACCESS, REFRESH, EMAIL, PASSWORD
    import json as _json, os as _os
    # 1) 尝试本地持久化
    if _os.path.isfile(TOKEN_FILE):
        try:
            d = _json.load(open(TOKEN_FILE, encoding="utf-8"))
            ACCESS, REFRESH, EMAIL = d.get("access", ""), d.get("refresh", ""), d.get("email", "")
        except Exception:
            pass
    # 2) 无账号 → 尝试读本地账号文件
    if not EMAIL or not PASSWORD:
        try:
            for p in ("/tmp/test_account.txt", "tools/.test_account.txt"):
                if _os.path.isfile(p):
                    line = open(p, encoding="utf-8").read().strip()
                    if "|" in line:
                        EMAIL, PASSWORD = line.split("|", 1)
                        break
        except Exception:
            pass
    # 3) 用 refresh 续期；失败则重新登录
    if ACCESS and REFRESH:
        if _try_refresh():
            return
    if EMAIL and PASSWORD:
        if _do_login():
            return
    print("[警告] 无有效登录态，请配置 EMAIL/PASSWORD 或 TOKEN_FILE")

def _http_raw(method: str, path: str, body: dict | None = None,
              with_auth: bool = True, timeout: int = 30) -> dict:
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if with_auth and _token:
        req.add_header("Authorization", "Bearer " + _token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "detail": e.read().decode()[:300]}
    except Exception as e:
        return {"ok": False, "detail": str(e)}

def _try_refresh() -> bool:
    """用 refresh 换新 access（腾讯云 /api/v1/auth/refresh，30 天有效期内可用）。"""
    global ACCESS, REFRESH, _token
    try:
        req = urllib.request.Request(BASE + "/api/v1/auth/refresh",
                                     data=json.dumps({"refresh_token": REFRESH}).encode(),
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode())
        if j.get("access_token"):
            ACCESS, _token = j["access_token"], j["access_token"]
            if j.get("refresh_token"):
                REFRESH = j["refresh_token"]
            _persist_token()
            print(f"[登录态] refresh 续期成功 email={EMAIL}")
            return True
    except Exception as e:
        print(f"[续期失败] {e}")
    return False

def _do_login() -> bool:
    """账号密码登录，落盘 token（refresh 30 天复用）。"""
    global ACCESS, REFRESH, _token, EMAIL
    try:
        req = urllib.request.Request(BASE + "/api/v1/auth/login",
                                     data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode())
        if j.get("access_token"):
            ACCESS, _token = j["access_token"], j["access_token"]
            REFRESH = j.get("refresh_token", "")
            EMAIL = (j.get("user") or {}).get("email", EMAIL)
            _persist_token()
            print(f"[登录态] 账号登录成功 email={EMAIL}（refresh 30 天有效）")
            return True
        print("[登录失败]", j)
    except Exception as e:
        print(f"[登录异常] {e}")
    return False

def _persist_token() -> None:
    import json as _json
    try:
        _json.dump({"access": ACCESS, "refresh": REFRESH, "email": EMAIL},
                   open(TOKEN_FILE, "w", encoding="utf-8"))
    except Exception:
        pass

WAIT_USER_SEC = 25          # waiting_user 等待（期间可人工在 App 配合）秒
POLL_INTERVAL = 2.0         # task 轮询间隔秒
DONE_TIMEOUT = 240          # 单话题最长等待秒

_token = ACCESS


def http(method: str, path: str, body: dict | None = None, with_auth: bool = True) -> dict:
    """请求腾讯云 API，401 自动用 refresh 续期重试一次。"""
    global _token
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(2):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if with_auth:
            req.add_header("Authorization", "Bearer " + _token)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0 and REFRESH:
                if _try_refresh():
                    continue
            return {"ok": False, "detail": f"HTTP {e.code}", "raw": e.read().decode()[:300]}
        except Exception as e:
            return {"ok": False, "detail": str(e)}


def submit(message: str, session_id: str = "") -> dict:
    return http("POST", "/api/v1/chat", {"message": message, "session_id": session_id})


def get_task() -> dict:
    r = http("GET", "/api/v1/task")
    return (r.get("task") or {})


def cancel() -> None:
    http("POST", "/api/v1/cancel")


def run_one(message: str, session_id: str = "", wait_user: int = WAIT_USER_SEC,
            done_timeout: int = DONE_TIMEOUT) -> dict:
    """提交一条话题并轮询到终态。返回结果字典。"""
    print("=" * 72)
    print(f"[提交] 会话={session_id or 'default'} | {message}")
    r = submit(message, session_id)
    if r.get("status") != "ok":
        print(f"[提交失败] {r}")
        return {"status": "submit_failed", "detail": r}
    t0 = time.time()
    last = {}
    while time.time() - t0 < done_timeout:
        t = get_task()
        last = t
        st = t.get("status")
        if st == "waiting_user":
            ask = t.get("ask") or {}
            print(f"[⏳ waiting_user] 需用户配合：{ask.get('question','')} "
                  f"(图片={'有' if ask.get('image') else '无'})")
            if wait_user <= 0:
                cancel()
                print("[已取消] 测试脚本不替用户输入，交由人工在手机 App 处理")
                return {"status": "waiting_user", "ask": ask}
            wait_user -= 1
            time.sleep(POLL_INTERVAL)
            continue
        if st in ("done", "failed", "cancelled"):
            print(f"[终态] status={st}")
            if st == "done":
                print(f"[回复] {t.get('reply','')}")
            elif st == "failed":
                print(f"[错误] {t.get('error','')}")
            else:
                print(f"[摘要] {t.get('summary','')}")
            return t
        time.sleep(POLL_INTERVAL)
    cancel()
    print("[超时] 已达最长等待，已取消；当前 task:", json.dumps(last, ensure_ascii=False)[:500])
    return {"status": "timeout", "task": last}


def run_multi(messages: list[str], session_id: str = "mem_test") -> None:
    """多轮记忆测试：同一会话连续提交多条，验证上下文记忆。"""
    print("\n" + "#" * 72)
    print("# 多轮对话记忆测试（同一会话 mem_test，连续多句）")
    print("#" * 72)
    for m in messages:
        run_one(m, session_id)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", help="单条消息")
    ap.add_argument("--multi", action="store_true", help="多轮记忆话题")
    ap.add_argument("--session", default="", help="会话 ID")
    ap.add_argument("--wait-user", type=int, default=WAIT_USER_SEC, help="waiting_user 等待秒")
    args = ap.parse_args()

    # 加载/刷新登录态（refresh 30 天有效期内复用；失效自动账号登录并落盘）
    _load_or_login()
    if not _token:
        print("[错误] 无有效登录态")
        sys.exit(1)
    # 先验证登录态/连通
    me = http("GET", "/api/v1/me")
    if not me.get("ok"):
        print("[错误] 登录态无效:", me)
        sys.exit(1)
    print(f"[登录] {EMAIL} 登录态有效")

    if args.multi:
        run_multi([
            "帮我订一张明天从南京到北京的火车票",   # 触发 tuniu
            "刚才说的出发城市是哪个？",            # 验证记忆（应记得南京）
        ], args.session or "mem_test")
        return

    if args.message:
        run_one(args.message, args.session)
        return

    print("请用 -m '话题' 或 --multi 指定测试话题。")


if __name__ == "__main__":
    main()
