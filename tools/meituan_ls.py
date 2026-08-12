#!/usr/bin/env python3
"""读美团 H5 localStorage，提取 poi 数据。"""
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

# 读 localStorage 里含 poi 的 key + 值片段
js = ("(function(){var r=[];for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);"
      "var v=localStorage.getItem(k)||'';"
      "if(v.indexOf('poi')>=0||k.indexOf('poi')>=0){r.push(k+' = '+v.slice(0,400));}}"
      "return JSON.stringify(r);})()")

s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "eval", "params": {"js": js}}, tok)
print(b2[:3000])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_ls.py && cd /home/ubuntu/xiami && python3 /tmp/mt_ls.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-3200:])

if __name__ == "__main__":
    main()
