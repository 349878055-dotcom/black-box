#!/usr/bin/env python3
"""美团 H5：诊断虾米 WebView 里美团的 localStorage/cookie 缓存状态。"""
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

# 导航到美团 H5（微信 UA）确保在美团域下能读 localStorage
url = "https://h5.waimai.meituan.com/waimai/mindex/home"
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "ua": "wechat", "timeout_ms": 20000}}, tok)
print("NAV:", b1[:100])
import time; time.sleep(3)

# 读美团域 localStorage 所有 key + 值（找缓存/购物车/用户状态）
js = ("(function(){var r={keys:[],cart:null};"
      "for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);var v=(localStorage.getItem(k)||'').slice(0,150);"
      "r.keys.push(k);"
      "if(k.toLowerCase().indexOf('cart')>=0||k.toLowerCase().indexOf('user')>=0||k.toLowerCase().indexOf('cancel')>=0||k.toLowerCase().indexOf('order')>=0)r.cart=k+' = '+v;}"
      "return JSON.stringify(r);})()")
print("LOCALSTORAGE:", eval_js(js)[:1200])

# 读 cookie（美团域）
js2 = ("(function(){return document.cookie.slice(0,600);})()")
print("COOKIE:", eval_js(js2)[:700])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_cd.py && cd /home/ubuntu/xiami && python3 /tmp/mt_cd.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-2000:])

if __name__ == "__main__":
    main()
