#!/usr/bin/env python3
"""读取美团 H5 页面底部栏（购物车/结算按钮）。"""
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

# 读底部固定栏所有可点元素 + 文本
js = ("(function(){var r={els:[],texts:[]};"
      "var fixed=document.querySelectorAll('[class*=fixed],[class*=bottom],[class*=footer],[class*=cart],[class*=settle]');"
      "for(var i=0;i<fixed.length&&i<200;i++){var e=fixed[i];"
      "var t=(e.innerText||'').trim();if(t&&t.length<200&&t.length>0)r.texts.push(t.slice(0,100));"
      "if((e.onclick||e.getAttribute('onclick'))&&t)r.els.push(t.slice(0,40));}"
      "return JSON.stringify(r);})()")

print(eval_js(js)[:1500])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_bottom.py && cd /home/ubuntu/xiami && python3 /tmp/mt_bottom.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1600:])

if __name__ == "__main__":
    main()
