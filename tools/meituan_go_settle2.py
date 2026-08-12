#!/usr/bin/env python3
"""美团 H5：点购物车栏去结算，进结算页。"""
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

# 点购物车栏（含"起送"的底部栏，购物车有货时它是结算入口）
js = ("(function(){var a=document.querySelectorAll('[class*=cart],[class*=settle],[class*=go]');"
      "for(var i=0;i<a.length&&i<2000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t.indexOf('起送')>=0||t.indexOf('去结算')>=0){"
      "var c=e;for(var k=0;k<6;k++){if(c.onclick||c.getAttribute('onclick')||c.tagName==='BUTTON'||c.getAttribute('role')){c.click();return 'clicked:'+t.slice(0,20);}c=c.parentElement;if(!c)break;}}}"
      "return 'notfound';})()")
print("SETTLE:", eval_js(js)[:200])
time.sleep(4)

# 读取结算页
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    print("URL:", res.get("url", ""))
    pt = res.get("page_text", "")
    print("文本前300:", pt[:300])
    print("文本末80:", pt[-80:])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_gs2.py && cd /home/ubuntu/xiami && python3 /tmp/mt_gs2.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1200:])

if __name__ == "__main__":
    main()
