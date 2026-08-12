#!/usr/bin/env python3
"""美团 H5：餐具弹层选"无需餐具"并确定。"""
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

# 1) 点"无需餐具"（弹层里，选环保选项）
js1 = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<30000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='无需餐具'){e.click();return 'clicked 无需餐具';}}return 'notfound';})()")
print("STEP1:", eval_js(js1)[:200])
time.sleep(1)

# 2) 点"确定"
js2 = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<30000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='确定'){e.click();return 'clicked 确定';}}return 'notfound';})()")
print("STEP2:", eval_js(js2)[:200])
time.sleep(3)

# 3) 读结算页（餐具应变为已选）
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b1); res = d.get("res", {})
    pt = res.get("page_text", "")
    idx = pt.find("餐具数量")
    print("餐具区:", pt[idx:idx+80] if idx>=0 else "未见")
    print("末80:", pt[-80:])
except Exception as e:
    print("err", e, b1[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_uo.py && cd /home/ubuntu/xiami && python3 /tmp/mt_uo.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-900:])

if __name__ == "__main__":
    main()
