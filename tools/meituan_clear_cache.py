#!/usr/bin/env python3
"""美团 H5：清理虾米 WebView 里美团域的 localStorage 脏缓存（保留登录态）。"""
import sys, os, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.deploy_agent_glyy import _ssh

REMOTE_PY = r'''
import urllib.request, json, time

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

# 1) 确保在美团域
url = "https://h5.waimai.meituan.com/waimai/mindex/home"
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "ua": "wechat", "timeout_ms": 20000}}, tok)
print("NAV:", b1[:100])
time.sleep(3)

# 2) 删除脏缓存 key（购物车/订单/配送等，保留登录态相关）
js = ("(function(){var del=[];var keep=['__lxsdk__lxsdk_cuid','localId','addstore','pickedpoi','geopoi','param','login_back_home'];"
      "for(var i=localStorage.length-1;i>=0;i--){var k=localStorage.key(i);"
      "var isDirty=(k.indexOf('cached_cart')>=0||k.indexOf('cart')>=0||k.indexOf('order')>=0||k.indexOf('delivery')>=0||k.indexOf('oldOrder')>=0||k.indexOf('orderCreate')>=0||k.indexOf('dfp')>=0);"
      "if(isDirty){localStorage.removeItem(k);del.push(k);}}"
      "return JSON.stringify(del);})()")
print("DELETED:", eval_js(js)[:600])

# 3) 确认清理后剩余 key
js2 = ("(function(){var r=[];for(var i=0;i<localStorage.length;i++)r.push(localStorage.key(i));return JSON.stringify(r);})()")
print("REMAIN:", eval_js(js2)[:600])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_cc2.py && cd /home/ubuntu/xiami && python3 /tmp/mt_cc2.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1400:])

if __name__ == "__main__":
    main()
