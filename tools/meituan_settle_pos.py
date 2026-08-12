#!/usr/bin/env python3
"""美团 H5：读底部结算按钮坐标（购物车有货后）。"""
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

# 找底部含"去结算/起送/¥"的可点结算栏坐标
js = ("(function(){var r=[];"
      "var a=document.querySelectorAll('[class*=cartContainer],[class*=cart_],[class*=settle],[class*=go]');"
      "for(var i=0;i<a.length&&i<1000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t&&t.length<100&&(t.indexOf('起送')>=0||t.indexOf('去结算')>=0||t.indexOf('¥')>=0)){"
      "var rect=e.getBoundingClientRect();if(rect.width>0)r.push({t:t.slice(0,30),x:Math.round(rect.left+rect.width/2),y:Math.round(rect.top+rect.height/2)});}}"
      "return JSON.stringify(r.slice(0,10));})()")
print(eval_js(js)[:800])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_sp.py && cd /home/ubuntu/xiami && python3 /tmp/mt_sp.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-900:])

if __name__ == "__main__":
    main()
