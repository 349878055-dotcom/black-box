#!/usr/bin/env python3
"""美团 H5：注入 mock 定位（南京雨山美地 lat32.055946 lng118.607651），绕过真实GPS。"""
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

# 1) 先导航到 H5 首页（确保在美团域）
url = "https://h5.waimai.meituan.com/waimai/mindex/home"
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "timeout_ms": 20000}}, tok)
print("NAV:", b1[:100])
time.sleep(3)

# 2) 注入 mock geolocation（覆盖 navigator.geolocation，返回南京坐标）
js = ("(function(){"
      "var pos={coords:{latitude:32.055946,longitude:118.607651,accuracy:30,altitude:null,altitudeAccuracy:null,heading:null,speed:null},timestamp:Date.now()};"
      "if(navigator.geolocation){navigator.geolocation.getCurrentPosition=function(s,e,o){s&&s(pos);};"
      "navigator.geolocation.watchPosition=function(s,e,o){s&&s(pos);return 1;};}"
      "return 'mock geolocation injected';})()")
print("MOCK GPS:", eval_js(js)[:200])

# 3) 重新加载首页（让美团读到 mock 定位）
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "timeout_ms": 25000}}, tok)
print("NAV2:", b2[:100])
time.sleep(6)

# 4) 读首页是否显示店铺
s3, b3 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b3); res = d.get("res", {})
    pt = res.get("page_text", "")
    has_shop = ("华莱士" in pt or "塔斯汀" in pt or "挪瓦" in pt or "肯德基" in pt or "十足" in pt or "海底捞" in pt)
    print("URL:", res.get("url", ""))
    print("有店铺:", has_shop, "| 文本前200:", pt[:200])
except Exception as e:
    print("err", e, b3[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_gps.py && cd /home/ubuntu/xiami && python3 /tmp/mt_gps.py"
    ok, out = _ssh(cmd, timeout=180)
    print(out.strip()[-1200:])

if __name__ == "__main__":
    main()
