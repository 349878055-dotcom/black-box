#!/usr/bin/env python3
"""美团 H5：精确捕获提交订单(submit/pay)的请求URL+响应。"""
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

# 清空 + 重新注入精确 hook（只抓 submit/pay/payment/preview 请求，且记录完整）
js = ("(function(){window.__net=[];"
      "var os=XMLHttpRequest.prototype.open;var oss=XMLHttpRequest.prototype.send;"
      "XMLHttpRequest.prototype.open=function(m,u){this.__u=u;this.__m=m;return os.apply(this,arguments);};"
      "XMLHttpRequest.prototype.send=function(b){var self=this;var u=self.__u||'';"
      "if(/submit|payment|pay|preview|confirm|createorder/i.test(u)){"
      "self.addEventListener('load',function(){window.__net.push('XHR '+self.__m+' '+u+' \\nSTATUS='+self.status+' \\nRESP='+String(self.responseText).slice(0,1200));});}"
      "return oss.apply(this,arguments);};"
      "var of=window.fetch;window.fetch=function(){var u=String(arguments[0]);"
      "if(/submit|payment|pay|preview|confirm|createorder/i.test(u)){var opts=arguments[1]||{};"
      "window.__net.push('FETCH '+u+' \\nBODY='+String(opts.body||'').slice(0,500));}"
      "return of.apply(this,arguments);};return 'hook ok';})()")
print("HOOK:", eval_js(js)[:120])
time.sleep(1)

# 点提交（用坐标 y 最大）
js2 = ("(function(){var best=null;var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<50000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='提交订单'){var rect=e.getBoundingClientRect();if(rect.width>0&&rect.height>0){"
      "var y=rect.top+rect.height/2;if(!best||y>best.y)best={x:Math.round(rect.left+rect.width/2),y:Math.round(y)};}}}"
      "if(best){var ev=new MouseEvent('click',{bubbles:true,cancelable:true,clientX:best.x,clientY:best.y});"
      "var el=document.elementFromPoint(best.x,best.y);if(el){el.dispatchEvent(ev);return 'clicked '+best.x+','+best.y;}}"
      "return 'notfound';})()")
print("点提交:", eval_js(js2)[:150])
time.sleep(6)

# 读取捕获
js3 = "(function(){return JSON.stringify(window.__net||[]);})()"
print("NET:", eval_js(js3)[:3500])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_cap.py && cd /home/ubuntu/xiami && python3 /tmp/mt_cap.py"
    ok, out = _ssh(cmd, timeout=150)
    print(out.strip()[-3800:])

if __name__ == "__main__":
    main()
