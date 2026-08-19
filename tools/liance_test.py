#!/usr/bin/env python3
"""真机联测 CLI 客户端：驱动云端「金涛」agent，模拟 3 场景。

用法：
  python3 tools/liance_test.py "南京哪个医院心内科比较好？" [conv_id]
  python3 tools/liance_test.py "帮我挂个号" [conv_id]
  python3 tools/liance_test.py "帮我订个高铁票" [conv_id] --reply "不对，我要点外卖"

行为：
  1) 登录拿 token（账号 349878055@qq.com / jintao0341）
  2) 无 conv_id 时新建挂金涛会话；否则复用
  3) POST /api/v1/chat 发消息 → 轮询 /api/v1/task
  4) 出现 waiting_user（ask_user）→ 打印提问；若给了 --reply 自动喂回答并继续，
     否则打印提示等手动回复
"""
import argparse
import json
import time
import urllib.request

BASE = "http://140.143.144.28"   # nginx → 19000
EMAIL = "349878055@qq.com"
PASSWORD = "jintao0341"


def req(method: str, path: str, token: str = "", body: dict | None = None) -> dict:
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())


def login() -> str:
    out = req("POST", "/api/v1/auth/login", body={"email": EMAIL, "password": PASSWORD})
    if not out.get("ok"):
        raise SystemExit(f"登录失败: {out}")
    return out["access_token"]


def get_or_create_conv(token: str, conv_id: str = "") -> str:
    if conv_id:
        return conv_id
    out = req("POST", "/api/v1/conversations", token,
              body={"type": "skill",
                    "persona": {"person_id": "jintao", "person_name": "金涛",
                                "skills": ["glyy", "meituan_waimai", "tuniu", "njpkzyy"]}})
    cid = out["conversation"]["conversation_id"]
    print(f"[会话] 新建挂金涛会话: {cid}")
    return cid


def run_once(token: str, conv_id: str, message: str, replies: list[str] | None = None) -> dict:
    """发一条消息，轮询到 done/failed/cancelled，或 waiting_user。
    replies：连续 ask_user 的自动代答队列（按序弹出，用完即停）。返回最终 task。"""
    replies = list(replies or [])
    print(f"\n>>> 客户: {message}")
    req("POST", "/api/v1/chat", token,
        body={"message": message, "session_id": conv_id})
    last = {}
    for _ in range(150):           # 最长约 3.5 分钟
        time.sleep(1.5)
        last = req("GET", "/api/v1/task", token).get("task", {})
        status = last.get("status")
        if status == "waiting_user":
            ask = last.get("ask") or {}
            q = ask.get("question", "")
            aid = ask.get("ask_id", "")
            print(f"  [AI问] {q}")
            if replies:
                ans = replies.pop(0)
                print(f"  [测试代答] {ans}")
                req("POST", "/api/v1/chat", token,
                    body={"message": ans, "session_id": conv_id,
                          "ask_id": aid})
                continue
            print("  (等待真人在手机/下一步代答，脚本暂停)")
            return last
        if status in ("done", "failed", "cancelled", "idle"):
            break
    return last


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("message", help="发给金涛的消息")
    ap.add_argument("conv_id", nargs="?", default="", help="复用会话 id（缺省新建）")
    ap.add_argument("--reply", default="", help="遇 ask_user 自动代答的内容")
    args = ap.parse_args()

    token = login()
    conv = get_or_create_conv(token, args.conv_id)
    print(f"[账号] {EMAIL}  [会话] {conv}")

    if args.reply and ";;" in args.reply:
        # 两条消息（如场景 C：先订票，再翻盘）；每条消息后面可跟 / 分隔的连续代答
        parts = args.reply.split(";;")
        for p in parts:
            msg, _, ans = p.partition("/")
            run_once(token, conv, msg or args.message,
                     replies=[x for x in ans.split("|") if x] or None)
    else:
        run_once(token, conv, args.message,
                 replies=[x for x in args.reply.split("|") if x] or None)

    final = req("GET", "/api/v1/task", token).get("task", {})
    print("\n========== 任务终态 ==========")
    print(json.dumps(final, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
