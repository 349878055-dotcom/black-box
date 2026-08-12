#!/usr/bin/env python3
"""美团 H5：点击购物车图标展开购物车浮层，再点去结算。"""
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

# 点击购物车图标（含 count=1 角标的容器，找 cart 相关且含点击能力的元素）
js = ("(function(){var a=document.querySelectorAll('[class*=cart],[class*=basket],[class*=shopcar]');"
      "for(var i=0;i<a.length&&i<2000;i++){var e=a[i];"
      "if(e.onclick||e.getAttribute('onclick')||e.tagName==='DIV'){"
      "try{e.click();return 'clicked cart:'+(e.className||'').slice(0,40);}catch(err){}}}"
      "return 'notfound';})()")

print("OPEN CART:", eval_js(js)[:200])
time.sleep(3)

# 读浮层文本（找去结算）
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    pt = res.get("page_text", "")
    # 找结算/购物车相关文本
    idx = pt.find("去结算")
    if idx < 0: idx = pt.find("结算")
    if idx < 0: idx = pt.find("已选")
    print("URL:", res.get("url", ""))
    print("结算上下文:", pt[max(0,idx-100):idx+150] if idx>=0 else "未找到, 末尾:"+pt[-200:])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_oc.py && cd /home/ubuntu/xiami && python3 /tmp/mt_oc.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1200:])

if __name__ == "__main__":
    main()
