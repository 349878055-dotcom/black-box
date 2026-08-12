#!/usr/bin/env python3
"""美团 H5：列出当前页面所有可见按钮/结算按钮。"""
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

# 所有含"结算/提交/选好了/确认/去"的可见元素文本
js = ("(function(){var r=[];var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<40000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t&&t.length<30&&(t.indexOf('结算')>=0||t.indexOf('提交')>=0||t.indexOf('选好了')>=0||t.indexOf('去')>=0||t.indexOf('¥')>=0)){"
      "var rect=e.getBoundingClientRect();"
      "if(rect.width>0&&rect.height>0)r.push(t);}}"
      "return JSON.stringify([...new Set(r)].slice(0,40));})()")

print(eval_js(js)[:1200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_vb.py && cd /home/ubuntu/xiami && python3 /tmp/mt_vb.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1300:])

if __name__ == "__main__":
    main()
