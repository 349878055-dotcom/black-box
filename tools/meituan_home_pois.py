#!/usr/bin/env python3
"""提取美团 H5 首页店铺列表的 poi_id（在远程执行，经 base64 传输避免转义）。"""
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

# 提取店铺：找所有带 href 且 href 含 poi 的元素 + 文本
js = ("(function(){var out=[];var seen={};"
      "var a=document.querySelectorAll('a,[class*=poi],[data-poi],[data-id]');"
      "for(var i=0;i<a.length&&i<3000;i++){var e=a[i];"
      "var h=e.getAttribute?e.getAttribute('href'):'';"
      "var t=(e.innerText||'').trim().split(String.fromCharCode(10))[0]||'';"
      "if(!t)continue;"
      "if(h&&h.indexOf('poi')>=0&&!seen[h]){seen[h]=1;out.push(t+' | '+h.slice(0,120));}"
      "var id=e.getAttribute?e.getAttribute('data-id'):'';"
      "if(id&&!seen['id:'+id]){seen['id:'+id]=1;out.push(t+' | data-id='+id);}"
      "}return JSON.stringify(out.slice(0,40));})()")

s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "eval", "params": {"js": js}}, tok)
print(b2[:3000])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_home.py && cd /home/ubuntu/xiami && python3 /tmp/mt_home.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-3200:])

if __name__ == "__main__":
    main()
