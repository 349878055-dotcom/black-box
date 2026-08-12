#!/usr/bin/env python3
"""美团 H5：注入网络 hook 捕获 submit/payment 请求与响应。"""
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

# 注入 hook（不含换行转义）
js = ("(function(){window.__net=[];"
      "var os=XMLHttpRequest.prototype.open;var oss=XMLHttpRequest.prototype.send;"
      "XMLHttpRequest.prototype.open=function(m,u){this.__u=u;this.__m=m;return os.apply(this,arguments);};"
      "XMLHttpRequest.prototype.send=function(b){var self=this;var u=self.__u||'';"
      "if(/submit|payment|pay|preview|createorder|confirm/i.test(u)){"
      "self.addEventListener('load',function(){window.__net.push('XHR '+self.__m+' '+u+' STATUS='+self.status+' RESP='+String(self.responseText).slice(0,1500));});}"
      "return oss.apply(this,arguments);};"
      "var of=window.fetch;window.fetch=function(){var u=String(arguments[0]);"
      "if(/submit|payment|pay|preview|createorder|confirm/i.test(u)){var o=arguments[1]||{};"
      "window.__net.push('FETCH '+u+' BODY='+String(o.body||'').slice(0,600));}"
      "return of.apply(this,arguments);};"
      "return 'hook installed '+document.URL;})()")

print(eval_js(js)[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_hn.py && cd /home/ubuntu/xiami && python3 /tmp/mt_hn.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-500:])

if __name__ == "__main__":
    main()
