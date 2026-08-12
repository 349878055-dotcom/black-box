#!/usr/bin/env python3
"""美团 H5：注入全量网络 hook（捕获所有 XHR/fetch，定位提交订单实际请求）。"""
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

def eval_js(js):
    s, b = call(API + "/api/v1/dev/browser",
                {"device_id": DEVICE, "cmd": "eval", "params": {"js": js}}, tok)
    return b

# 全量 hook：捕获所有 XHR（POST 优先），记录 URL + status + 响应前 800 字符
js = ("(function(){window.__all=[];"
      "var os=XMLHttpRequest.prototype.open;var oss=XMLHttpRequest.prototype.send;"
      "XMLHttpRequest.prototype.open=function(m,u){this.__u=u;this.__m=m;return os.apply(this,arguments);};"
      "XMLHttpRequest.prototype.send=function(b){var self=this;var u=self.__u||'';var m=self.__m||'';"
      "if(m==='POST'||/order|pay|submit|token|yoda|risk/i.test(u)){"
      "self.addEventListener('load',function(){window.__all.push(m+' '+u+' => '+self.status+' : '+String(self.responseText).slice(0,800));});}"
      "return oss.apply(this,arguments);};"
      "return 'all hook installed '+window.__all.length;})()")

print(eval_js(js)[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_ha.py && cd /home/ubuntu/xiami && python3 /tmp/mt_ha.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-500:])

if __name__ == "__main__":
    main()
