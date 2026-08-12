#!/usr/bin/env python3
"""美团 H5：打开购物车浮层，清空购物车。"""
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

# 1) 导航回菜单页
url = "https://h5.waimai.meituan.com/waimai/mindex/menu?poi_id_str=7i9ZEJ79LWZaWfoofywaugI&source=shoplist"
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "ua": "wechat", "timeout_ms": 25000}}, tok)
print("NAV:", b1[:120])
time.sleep(4)

# 2) 打开购物车浮层（点购物车图标）
js = ("(function(){var a=document.querySelectorAll('[role=button]');"
      "for(var i=0;i<a.length;i++){var e=a[i];var l=(e.getAttribute('aria-label')||'');"
      "if(l.indexOf('购物车')>=0){e.click();return 'opened';}}return 'notfound';})()")
print("OPEN:", eval_js(js)[:150])
time.sleep(2)

# 3) 找"清空"按钮并点击
js2 = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<30000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='清空'||t.indexOf('清空购物车')>=0){e.click();return 'clicked 清空';}}return 'notfound';})()")
print("CLEAR:", eval_js(js2)[:150])
time.sleep(2)

# 4) 确认购物车空
js3 = ("(function(){var e=document.querySelector('[aria-label*=购物车]');"
      "return e?e.getAttribute('aria-label'):'none';})()")
print("CART AFTER:", eval_js(js3)[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_cc.py && cd /home/ubuntu/xiami && python3 /tmp/mt_cc.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-900:])

if __name__ == "__main__":
    main()
