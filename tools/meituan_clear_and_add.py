#!/usr/bin/env python3
"""美团 H5：清空购物车 + 重新加购普通商品（生椰拿铁¥13.9）。"""
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

# 1) 导航回菜单页（重新加载，清购物车 UI 状态）
url = "https://h5.waimai.meituan.com/waimai/mindex/menu?poi_id_str=7i9ZEJ79LWZaWfoofywaugI&source=shoplist"
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "ua": "wechat", "timeout_ms": 25000}}, tok)
print("NAV:", b1[:120])
time.sleep(4)

# 2) 点击"生椰拿铁"（¥13.9 普通商品）加购按钮
js = ("(function(){var a=document.querySelectorAll('dd[data-tag=spu]');"
      "for(var i=0;i<a.length;i++){var e=a[i];var t=(e.innerText||'');"
      "if(t.indexOf('生椰拿铁')>=0){"
      "var b=e.querySelector('.sqt-menu-add-buttons,[class*=btnGroup]');if(!b)b=e;"
      "b.click();return 'clicked 生椰拿铁';}}return 'notfound';})()")
print("ADD 生椰拿铁:", eval_js(js)[:200])
time.sleep(2)

# 3) 点"加入购物车"
js2 = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<30000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='加入购物车'){e.click();return 'clicked cartbtn';}}return 'notfound';})()")
print("ADD CART:", eval_js(js2)[:200])
time.sleep(3)

# 4) 验证购物车
js3 = ("(function(){var e=document.querySelector('[aria-label*=购物车]');"
      "return e?e.getAttribute('aria-label'):'none';})()")
print("CART:", eval_js(js3)[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_ca.py && cd /home/ubuntu/xiami && python3 /tmp/mt_ca.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-900:])

if __name__ == "__main__":
    main()
