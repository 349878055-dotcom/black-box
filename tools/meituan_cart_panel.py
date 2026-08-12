#!/usr/bin/env python3
"""美团 H5：点击购物车图标展开浮层，读取购物车内容。"""
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

# 点击购物车图标（role=button, aria-label 含购物车）
js = ("(function(){var a=document.querySelectorAll('[role=button]');"
      "for(var i=0;i<a.length;i++){var e=a[i];var l=(e.getAttribute('aria-label')||'');"
      "if(l.indexOf('购物车')>=0){e.click();return 'clicked cart icon';}}return 'notfound';})()")

print("CLICK ICON:", eval_js(js)[:200])
time.sleep(3)

# 读取浮层/购物车内容
js2 = ("(function(){var r={};"
       "var icon=document.querySelector('[aria-label*=购物车]');if(icon)r.label=icon.getAttribute('aria-label');"
       "var panel=document.querySelector('[class*=cartPanel],[class*=cartpanel],[class*=cart-list],[class*=cartlist],[class*=popup],[class*=drawer]');"
       "if(panel)r.panel=panel.innerText.slice(0,400);"
       "return JSON.stringify(r);})()")
print("PANEL:", eval_js(js2)[:800])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_cp.py && cd /home/ubuntu/xiami && python3 /tmp/mt_cp.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1200:])

if __name__ == "__main__":
    main()
