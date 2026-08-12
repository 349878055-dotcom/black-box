#!/usr/bin/env python3
"""dump 美团 H5 底部结算栏完整 HTML（找去结算按钮）。"""
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

# 找含"起送"或总价的底部栏，dump outerHTML（找去结算/提交按钮）
js = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<50000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t.indexOf('起送')>=0&&t.length<100){"
      "return e.outerHTML.slice(0,2500);}}return 'none';})()")

print(eval_js(js)[:2600])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_dbb.py && cd /home/ubuntu/xiami && python3 /tmp/mt_dbb.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-2800:])

if __name__ == "__main__":
    main()
