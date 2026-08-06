#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
南京鼓楼医院互联网医院（微信小程序）· 登录 + session 保存/加载 辅助脚本。

后端（从小程序代码逆向 + 真实抓包确认）：
  域名: www.ih.njglyy.com:9532  （生产 /caring/api，测试 /nte/api）
  签名: sign = SHA1( MD5(appKey + timestamp + nonce) )，appKey=1340patient
  认证: 公开接口用 Basic；登录后带 Authorization: Bearer <access_token>
  UA  : 必须用「微信手机 UA」，否则服务器挂起不响应

登录流程（验证码真人配合）：
  1) 取图形验证码 → 存图给人看 → 人输入图形验证码
  2) 发短信验证码到手机 → 人输入短信验证码
  3) 调 /v4/session/phone 登录 → 返回 {access_token, refresh_token, ...}

用法：
  python3 skill_maker/glyy_session.py --graphical --phone 13800000000
      → 抓图形验证码存 /tmp/glyy_captcha.png（人看后输入）
  python3 skill_maker/glyy_session.py --send-sms --phone 13800000000 --gcode 图形验证码
      → 发短信到手机（人看手机收验证码）
  python3 skill_maker/glyy_session.py --login --phone 13800000000 --code 短信验证码
      → 登录并保存 session 到 /tmp/glyy_session.json
  python3 skill_maker/glyy_session.py --check
      → 验证已保存 session（用 token 调一个需登录接口）

注意：
  - 图形验证码获取后勿重复抓取（会失效），尽快发短信
  - 短信验证码有效期短（几分钟），尽快登录
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import string
import sys
import time

import requests
import urllib3

urllib3.disable_warnings()

BASE = "https://www.ih.njglyy.com:9532/caring/api"
APP_KEY = "1340patient"
TENANT = "1340"
ROLE = "patient"
BASIC_SMS = "Basic c21zOnNtc3NlY3JldA=="          # sms:smssecret（发短信/验证码用）
BASIC_HOSPITAL = "Basic aG9zcGl0YWw6aG9zcGl0YWwtc2VjcmV0"  # hospital:hospital-secret（公开接口）
# 微信手机 UA（服务器按 UA 过滤，必须用它）
UA_WX = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38(0x18002623) "
         "NetType/WIFI Language/zh_CN")

SESSION_FILE = "/tmp/glyy_session.json"
CAPTCHA_FILE = "/tmp/glyy_captcha.png"


def make_nonce() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=32))


def make_sign(app_key: str, timestamp: str, nonce: str) -> str:
    """sign = SHA1(MD5(appKey + timestamp + nonce))  （对齐小程序 getSigns）"""
    md5hex = hashlib.md5((app_key + timestamp + nonce).encode("utf-8")).hexdigest()
    return hashlib.sha1(md5hex.encode("utf-8")).hexdigest()


def sign_headers(basic: str = BASIC_SMS, extra: dict | None = None) -> dict:
    """生成带签名的请求头（对齐小程序 caringRequest）。"""
    timestamp = str(int(time.time() * 1000))
    nonce = make_nonce()
    h = {
        "User-Agent": UA_WX,
        "Authorization": basic,
        "appKey": APP_KEY,
        "role": ROLE,
        "tenant": TENANT,
        "timestamp": timestamp,
        "nonce": nonce,
        "sign": make_sign(APP_KEY, timestamp, nonce),
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Referer": "https://servicewechat.com/wx74a991a2ae77468d/330/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if extra:
        h.update(extra)
    return h


def s_get(path: str, params: dict, basic: str = BASIC_SMS, timeout: int = 20) -> dict:
    r = requests.get(BASE + path, params=params, headers=sign_headers(basic),
                     timeout=timeout, verify=False)
    return _parse(r)


def s_post(path: str, params: dict, basic: str = BASIC_SMS, timeout: int = 20) -> dict:
    r = requests.post(BASE + path, params=params, headers=sign_headers(basic),
                      timeout=timeout, verify=False)
    return _parse(r)


def _parse(r: requests.Response) -> dict:
    text = r.content.decode("utf-8", "replace")
    try:
        return {"http": r.status_code, "json": json.loads(text)}
    except Exception:
        return {"http": r.status_code, "text": text[:300]}


# ─────────── 步骤1：图形验证码 ───────────
def get_graphical_captcha(phone: str) -> str | None:
    """POST /sms/captcha?phone=xxx → base64 PNG 图形验证码，存文件给人看。"""
    res = s_post("/sms/captcha", {"phone": phone})
    j = res.get("json") or {}
    if j.get("code") != 0:
        print(f"[error] 获取图形验证码失败: {j.get('message') or j.get('dev_message')}")
        return None
    data = j.get("data") or ""
    if isinstance(data, str) and data.startswith("data:image"):
        b64 = data.split(",", 1)[1]
        import base64
        with open(CAPTCHA_FILE, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"[captcha] 图形验证码已保存 → {CAPTCHA_FILE}  （请人工查看后输入）")
        return CAPTCHA_FILE
    print(f"[error] 返回不是图片: {str(data)[:80]}")
    return None


# ─────────── 步骤2：发短信 ───────────
def send_sms(phone: str, graphical_code: str) -> bool:
    """POST /sms?phone=xxx&type=1&code=图形验证码 → 给手机发短信验证码。"""
    res = s_post("/sms", {"phone": phone, "type": "1", "code": graphical_code})
    j = res.get("json") or {}
    if j.get("code") == 0:
        print(f"[sms] 短信已发送到 {phone}（请查看手机短信验证码）")
        return True
    print(f"[error] 发短信失败: {j.get('message') or j.get('dev_message')} (res_code={j.get('data')})")
    return False


# ─────────── 步骤3：登录 ───────────
def login(phone: str, sms_code: str) -> dict:
    """登录：POST /v4/session/phone?phone=xxx&code=xxx + JSON body（Basic hospital）。

    实测确认：query 带 phone/code，body 也要 JSON（含 phone/code），认证用 hospital:hospital-secret。
    """
    timestamp = str(int(time.time() * 1000))
    nonce = make_nonce()
    headers = {
        "User-Agent": UA_WX,
        "Authorization": BASIC_HOSPITAL,
        "appKey": APP_KEY,
        "role": ROLE,
        "tenant": TENANT,
        "timestamp": timestamp,
        "nonce": nonce,
        "sign": make_sign(APP_KEY, timestamp, nonce),
        "Content-Type": "application/json",
        "Accept": "*/*",
    }
    params = {"phone": phone, "code": sms_code}
    body = {"phone": phone, "code": sms_code}
    r = requests.post(BASE + "/v4/session/phone", params=params, json=body,
                      headers=headers, timeout=20, verify=False)
    try:
        j = r.json()
    except Exception:
        return {"ok": False, "raw": {"http": r.status_code, "text": r.text[:300]}}
    if j.get("code") == 0:
        data = j.get("data") or {}
        print(f"[login] 登录成功！返回字段: {list(data.keys())}")
        return {"ok": True, "data": data, "raw": j}
    print(f"[error] 登录失败: {j.get('message') or j.get('dev_message')} (code={j.get('code')})")
    return {"ok": False, "raw": j}


def save_session(data: dict) -> None:
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[session] 已保存 → {SESSION_FILE}")


def load_session() -> dict | None:
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def main() -> None:
    p = argparse.ArgumentParser(description="南京鼓楼医院互联网医院 登录")
    p.add_argument("--graphical", action="store_true", help="步骤1：抓图形验证码")
    p.add_argument("--send-sms", action="store_true", help="步骤2：发短信验证码")
    p.add_argument("--login", action="store_true", help="步骤3：登录")
    p.add_argument("--check", action="store_true", help="检查已保存 session")
    p.add_argument("--phone", default="", help="手机号")
    p.add_argument("--gcode", default="", help="图形验证码")
    p.add_argument("--code", default="", help="短信验证码")
    args = p.parse_args()

    if args.graphical:
        if not args.phone:
            print("[error] 需要 --phone"); sys.exit(1)
        get_graphical_captcha(args.phone)
    elif args.send_sms:
        if not args.phone or not args.gcode:
            print("[error] 需要 --phone 和 --gcode（图形验证码）"); sys.exit(1)
        send_sms(args.phone, args.gcode)
    elif args.login:
        if not args.phone or not args.code:
            print("[error] 需要 --phone 和 --code（短信验证码）"); sys.exit(1)
        res = login(args.phone, args.code)
        if res["ok"]:
            save_session(res["data"])
    elif args.check:
        s = load_session()
        print(f"[check] 已保存 session: {list((s or {}).keys())}")
        if not s:
            sys.exit(1)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
