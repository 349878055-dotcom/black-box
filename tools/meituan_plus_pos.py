#!/usr/bin/env python3
"""美团 H5：找"金奖美式"加购按钮的屏幕坐标（供 adb 真实点击）。"""
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

# 找"金奖美式"（¥9.9 那款）的加购按钮坐标
js = ("(function(){var r=[];var a=document.querySelectorAll('dd[data-tag=spu]');"
      "for(var i=0;i<a.length;i++){var e=a[i];var t=(e.innerText||'');"
      "if(t.indexOf('金奖美式')>=0&&t.indexOf('¥9.9')>=0){"
      "var b=e.querySelector('.sqt-menu-add-buttons,[class*=btnGroup],[class*=add]');"
      "if(b){var rect=b.getBoundingClientRect();r.push({x:Math.round(rect.left+rect.width/2),y:Math.round(rect.top+rect.height/2),cls:(b.className||'').slice(0,40)});}}}"
      "return JSON.stringify(r);})()")

print(eval_js(js)[:600])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_pp.py && cd /home/ubuntu/xiami && python3 /tmp/mt_pp.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-700:])

if __name__ == "__main__":
    main()
