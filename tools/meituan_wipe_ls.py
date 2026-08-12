#!/usr/bin/env python3
"""美团 H5：清空美团域 localStorage 全部（让美团重新生成 dfp/设备指纹 + 干净重载）。"""
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

# 1) 导航到美团域
url = "https://h5.waimai.meituan.com/waimai/mindex/home"
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "ua": "wechat", "timeout_ms": 20000}}, tok)
print("NAV:", b1[:100])
time.sleep(2)

# 2) 清空全部 localStorage（美团会重新生成 dfp/指纹）
js = ("(function(){var n=localStorage.length;localStorage.clear();return 'cleared '+n+' keys';})()")
print("CLEAR:", eval_js(js)[:200])

# 3) 重新导航让美团完全初始化（重新生成 dfp + 可能需要重新登录）
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "ua": "wechat", "timeout_ms": 25000}}, tok)
print("NAV2:", b2[:100])
time.sleep(5)

# 4) 读首页状态
s3, b3 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b3); res = d.get("res", {})
    print("URL:", res.get("url", ""))
    print("文本前150:", res.get("page_text", "")[:150])
except Exception as e:
    print("err", e, b3[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_wipe.py && cd /home/ubuntu/xiami && python3 /tmp/mt_wipe.py"
    ok, out = _ssh(cmd, timeout=150)
    print(out.strip()[-1100:])

if __name__ == "__main__":
    main()
