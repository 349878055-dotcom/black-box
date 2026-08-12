#!/usr/bin/env python3
"""美团 H5：捕获首页聚合接口的请求与响应（定位"网络不给力"原因）。"""
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

# 导航首页
url = "https://h5.waimai.meituan.com/waimai/mindex/home"
s1, b1 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "navigate", "params": {"url": url, "ua": "browser", "timeout_ms": 25000}}, tok)
print("NAV:", b1[:80])
time.sleep(4)

# 注入 hook 捕获所有 XHR 响应（首页聚合/店铺）
js = ("(function(){window.__n2=[];"
      "var os=XMLHttpRequest.prototype.open;var oss=XMLHttpRequest.prototype.send;"
      "XMLHttpRequest.prototype.open=function(m,u){this.__u=u;this.__m=m;return os.apply(this,arguments);};"
      "XMLHttpRequest.prototype.send=function(b){var self=this;var u=self.__u||'';var m=self.__m||'';"
      "if(m==='POST'||/home|aggregate|poi|index/i.test(u)){"
      "self.addEventListener('load',function(){window.__n2.push(m+' '+u+' => '+self.status+' : '+String(self.responseText).slice(0,400));});}"
      "return oss.apply(this,arguments);};return 'hook ok';})()")
print("HOOK:", eval_js(js)[:120])
time.sleep(5)

# 读捕获
js2 = "(function(){return JSON.stringify(window.__n2||[]);})()"
print("NET:", eval_js(js2)[:3000])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_hn2.py && cd /home/ubuntu/xiami && python3 /tmp/mt_hn2.py"
    ok, out = _ssh(cmd, timeout=150)
    print(out.strip()[-3300:])

if __name__ == "__main__":
    main()
