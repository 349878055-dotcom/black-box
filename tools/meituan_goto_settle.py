#!/usr/bin/env python3
"""美团 H5：点击底部购物车/去结算，进入结算页。"""
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

# 找含"去结算"或"结算"或"选好了"或"¥"的按钮并点击（底部结算栏）
js = ("(function(){var found='';"
      "var btns=document.querySelectorAll('button,[class*=settle],[class*=submit],[class*=go],[class*=cart],[class*=pay],[role=button]');"
      "for(var i=0;i<btns.length&&i<3000;i++){var e=btns[i];var t=(e.innerText||'').trim();"
      "if((t.indexOf('去结算')>=0||t.indexOf('结算')>=0||t.indexOf('选好了')>=0||t==='选好了'||t.indexOf('¥')>=0)&&t.length<30){"
      "try{e.click();return 'clicked:'+t;}catch(err){}}}"
      "return 'notfound:'+btns.length;})()")

print("SETTLE:", eval_js(js)[:200])
time.sleep(4)

# 读结果（是否进入结算页）
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    print("URL:", res.get("url", ""))
    print("文本前400:", res.get("page_text", "")[:400])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_gs.py && cd /home/ubuntu/xiami && python3 /tmp/mt_gs.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1400:])

if __name__ == "__main__":
    main()
