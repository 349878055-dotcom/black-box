#!/usr/bin/env python3
"""读取美团 H5 底部购物车栏（数量/金额）。"""
import sys, os, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.deploy_agent_glyy import _ssh

REMOTE_PY = r'''
import urllib.request, json

API = "http://127.0.0.1:19000"
DEVICE = "349878055@qq.com"

def call(url, obj, tok=None):
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = "Bearer " + tok
    data = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

s, b = call(API + "/api/v1/auth/login", {"email": "349878055@qq.com", "password": "jintao0341"})
tok = json.loads(b).get("access_token", "")

def eval_js(js):
    s, b = call(API + "/api/v1/dev/browser",
                {"device_id": DEVICE, "cmd": "eval", "params": {"js": js}}, tok)
    return b

# 读底部购物车栏 / 购物车面板
js = ("(function(){var r={};"
      "var cart=document.querySelector('[class*=cart-bar],[class*=cartBar],[class*=bottom-bar],[class*=cartpanel]');"
      "if(cart)r.cartBar=cart.innerText.slice(0,300);"
      "var badge=document.querySelector('[class*=cart-count],[class*=badge],[class*=num]');"
      "if(badge)r.count=badge.innerText;"
      "var total=document.querySelector('[class*=total],[class*=price]');"
      "if(total)r.total=total.innerText.slice(0,100);"
      "return JSON.stringify(r);})()")

print(eval_js(js)[:800])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_cart.py && cd /home/ubuntu/xiami && python3 /tmp/mt_cart.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-900:])

if __name__ == "__main__":
    main()
