#!/usr/bin/env python3
"""美团 H5：从 localStorage 找提交订单/支付相关缓存数据。"""
import sys, os, base64, time
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

# 导航到美团域（确保能读 localStorage）
url = "https://h5.waimai.meituan.com/waimai/mindex/home"
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "ua": "wechat", "timeout_ms": 20000}}, tok)
print("NAV:", b1[:100])
time.sleep(3)

# 读所有 localStorage key + 值（找订单/支付/pay/order/token/url）
js = ("(function(){var r=[];for(var i=0;i<localStorage.length;i++){"
      "var k=localStorage.key(i);var v=(localStorage.getItem(k)||'');"
      "if(/order|pay|submit|create|preview|token|url|wm_/i.test(k)||/order|pay|submit|preview|href|https/i.test(v.slice(0,200))){"
      "r.push(k+' = '+v.slice(0,400));}}return JSON.stringify(r);})()")
print("ORDER/PAY CACHE:", eval_js(js)[:2500])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_oc.py && cd /home/ubuntu/xiami && python3 /tmp/mt_oc.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-2800:])

if __name__ == "__main__":
    main()
