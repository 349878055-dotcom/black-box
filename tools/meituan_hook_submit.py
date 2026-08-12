#!/usr/bin/env python3
"""美团 H5：hook fetch/XHR 捕获提交订单的请求与响应（判断 H5支付 / JSAPI / 报错）。"""
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

# 1) 注入 fetch + XHR hook（记录提交订单相关请求到 window.__net）
js = ("(function(){"
      "window.__net=[];"
      "var of=window.fetch;window.fetch=function(){"
      "var url=arguments[0];var opts=arguments[1]||{};"
      "if(String(url).indexOf('order')>=0||String(url).indexOf('submit')>=0||String(url).indexOf('pay')>=0||String(url).indexOf('payment')>=0){"
      "window.__net.push({type:'fetch',url:String(url),body:opts.body?String(opts.body).slice(0,500):''});}"
      "return of.apply(this,arguments);};"
      "var ox=XMLHttpRequest.prototype.open;var osend=XMLHttpRequest.prototype.send;"
      "XMLHttpRequest.prototype.open=function(m,u){this.__u=u;this.__m=m;return ox.apply(this,arguments);};"
      "XMLHttpRequest.prototype.send=function(b){var self=this;var u=self.__u||'';"
      "if(u.indexOf('order')>=0||u.indexOf('submit')>=0||u.indexOf('pay')>=0||u.indexOf('payment')>=0){"
      "self.addEventListener('load',function(){window.__net.push({type:'xhr',url:u,status:self.status,resp:String(self.responseText).slice(0,800)});});}"
      "return osend.apply(this,arguments);};"
      "return 'hook installed';})()")
print("HOOK:", eval_js(js)[:150])
time.sleep(1)

# 2) 点提交订单
js2 = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<40000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='提交订单'){e.click();return 'clicked';}}return 'notfound';})()")
print("点提交:", eval_js(js2)[:120])
time.sleep(6)

# 3) 读取捕获的网络请求
js3 = ("(function(){return JSON.stringify(window.__net||[]);})()")
print("NET:", eval_js(js3)[:2500])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_hook.py && cd /home/ubuntu/xiami && python3 /tmp/mt_hook.py"
    ok, out = _ssh(cmd, timeout=150)
    print(out.strip()[-2800:])

if __name__ == "__main__":
    main()
