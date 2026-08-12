#!/usr/bin/env python3
"""美团 H5：手动写入位置数据（雨山美地 lat/lng），绕过定位授权显示店铺。"""
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

# 导航到 H5 首页
url = "https://h5.waimai.meituan.com/waimai/mindex/home"
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "timeout_ms": 20000}}, tok)
print("NAV:", b1[:100])
time.sleep(3)

# 写入位置数据（雨山美地：lat 32.055946, lng 118.607651）—— 对齐之前 localStorage 里的 pickedpoi/geopoi/param
js = ("(function(){"
      "var poi={lat:32.055946,lng:118.607651,geotype:2,poi:'雨山美地',address:null};"
      "localStorage.setItem('pickedpoi',JSON.stringify(poi));"
      "localStorage.setItem('geopoi',JSON.stringify({lat:32.055946,lng:118.607651,geotype:2,poi:'雨山美地'}));"
      "localStorage.setItem('param',JSON.stringify({pickedPOI:poi,initialLat:32.055946,initialLng:118.607651,addressName:'雨山美地',address:null,geoPOI:poi,lat:32.055946,lng:118.607651,geotype:2}));"
      "return 'location set';})()")
print("SET LOC:", eval_js(js)[:200])
time.sleep(2)

# 重新加载首页
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "timeout_ms": 20000}}, tok)
time.sleep(5)
s3, b3 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b3); res = d.get("res", {})
    pt = res.get("page_text", "")
    has_shop = ("华莱士" in pt or "塔斯汀" in pt or "挪瓦" in pt or "肯德基" in pt or "十足" in pt)
    print("URL:", res.get("url", ""))
    print("有店铺:", has_shop, "| 文本:", pt[:150])
except Exception as e:
    print("err", e, b3[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_loc.py && cd /home/ubuntu/xiami && python3 /tmp/mt_loc.py"
    ok, out = _ssh(cmd, timeout=150)
    print(out.strip()[-900:])

if __name__ == "__main__":
    main()
