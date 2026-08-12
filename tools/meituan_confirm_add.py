#!/usr/bin/env python3
"""美团 H5 规格弹层点击"加入购物车"。"""
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

# 点击"加入购物车"按钮
js = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<20000;i++){var e=a[i];"
      "var t=(e.innerText||'').trim();"
      "if(t==='加入购物车'||t.indexOf('加入购物车')>=0){"
      "if(e.tagName==='BUTTON'||e.onclick||e.getAttribute('onclick')){e.click();return 'clicked cartbtn';}"
      "var c=e;for(var k=0;k<4;k++){if(c.onclick||c.tagName==='BUTTON'||c.getAttribute('onclick')){c.click();return 'clicked ancestor';}c=c.parentElement;if(!c)break;}}}"
      "return 'notfound';})()")

print("CONFIRM:", eval_js(js)[:200])
time.sleep(3)

# 读取页面（看是否加入购物车成功 - 底部出现购物车栏）
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    pt = res.get("page_text", "")
    print("URL:", res.get("url", ""))
    print("文本末尾400:", pt[-400:])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_confirm.py && cd /home/ubuntu/xiami && python3 /tmp/mt_confirm.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1200:])

if __name__ == "__main__":
    main()
