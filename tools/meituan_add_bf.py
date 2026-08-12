#!/usr/bin/env python3
"""美团 H5：加购塔斯汀"徐福牛堡"，走到结算并提交，验证是否还报工程师太忙。"""
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

# 1) 点"徐福牛堡"加购
js = ("(function(){var a=document.querySelectorAll('dd[data-tag=spu]');"
      "for(var i=0;i<a.length;i++){var e=a[i];var t=(e.innerText||'');"
      "if(t.indexOf('徐福牛堡')>=0){"
      "var b=e.querySelector('.sqt-menu-add-buttons,[class*=btnGroup]');if(!b)b=e;b.click();return 'clicked 徐福牛堡';}}return 'notfound';})()")
print("STEP1 加购:", eval_js(js)[:200])
time.sleep(2)

# 2) 点"加入购物车"
js2 = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<30000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='加入购物车'){e.click();return 'clicked cartbtn';}}return 'notfound';})()")
print("STEP2 加入购物车:", eval_js(js2)[:200])
time.sleep(3)

# 3) 验证购物车
js3 = ("(function(){var e=document.querySelector('[aria-label*=购物车]');"
      "return e?e.getAttribute('aria-label'):'none';})()")
print("STEP3 购物车:", eval_js(js3)[:200])

# 4) 去结算
js4 = ("(function(){var a=document.querySelectorAll('[class*=cart],[class*=settle],[class*=go]');"
      "for(var i=0;i<a.length&&i<2000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t.indexOf('起送')>=0||t.indexOf('去结算')>=0){"
      "var c=e;for(var k=0;k<6;k++){if(c.onclick||c.getAttribute('onclick')||c.tagName==='BUTTON'||c.getAttribute('role')){c.click();return 'clicked 去结算';}c=c.parentElement;if(!c)break;}}}"
      "return 'notfound';})()")
print("STEP4 去结算:", eval_js(js4)[:200])
time.sleep(4)

# 5) 读结算页
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    print("URL:", res.get("url", ""))
    pt = res.get("page_text", "")
    print("文本前300:", pt[:300])
    print("末60:", pt[-60:])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_bf.py && cd /home/ubuntu/xiami && python3 /tmp/mt_bf.py"
    ok, out = _ssh(cmd, timeout=150)
    print(out.strip()[-1400:])

if __name__ == "__main__":
    main()
