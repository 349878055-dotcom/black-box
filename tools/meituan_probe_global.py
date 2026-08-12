#!/usr/bin/env python3
"""探测美团 H5 页面全局数据对象（找店铺/poi 数据源）。"""
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

# 列 window 上所有对象 key + 是否有 store/state/data 含 poi
js = ("(function(){var keys=[];for(var k in window){"
      "try{var v=window[k];if(v&&typeof v==='object'&&typeof v!=='null'){"
      "var s=JSON.stringify(v);if(s&&(s.indexOf('poi_id')>=0||s.indexOf('poiId')>=0||s.indexOf('wm_poi')>=0)){"
      "keys.push(k+' (len='+s.length+')');}}}catch(e){}}"
      "return JSON.stringify(keys.slice(0,20));})()")

s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "eval", "params": {"js": js}}, tok)
print("GLOBAL KEYS:", b2[:1500])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_probe.py && cd /home/ubuntu/xiami && python3 /tmp/mt_probe.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1600:])

if __name__ == "__main__":
    main()
