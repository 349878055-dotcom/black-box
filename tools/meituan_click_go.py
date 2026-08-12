#!/usr/bin/env python3
"""美团 H5：实时定位并点击"去结算/提交订单"按钮（不依赖旧坐标）。用法: go|submit"""
import sys, os, base64, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.deploy_agent_glyy import _ssh

REMOTE_PY = r'''
import urllib.request, json, time, sys

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

target = sys.argv[1] if len(sys.argv) > 1 else "go"

# 实时定位 + 用 elementFromPoint + 完整鼠标事件点击
js = ("(function(){var kw='" + target + "';"
      "var map={go:'去结算',submit:'提交订单'};var targetText=map[kw]||kw;"
      "var best=null;var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<50000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t===targetText){var rect=e.getBoundingClientRect();if(rect.width>0&&rect.height>0){"
      "var y=rect.top+rect.height/2;if(!best||y>best.y)best={x:rect.left+rect.width/2,y:y};}}}"
      "if(!best)return 'notfound:'+targetText;"
      "var el=document.elementFromPoint(best.x,best.y);if(!el)return 'noel';"
      "var opts={bubbles:true,cancelable:true,clientX:best.x,clientY:best.y,view:window,button:0};"
      "el.dispatchEvent(new PointerEvent('pointerdown',opts));"
      "el.dispatchEvent(new MouseEvent('mousedown',opts));"
      "el.dispatchEvent(new PointerEvent('pointerup',opts));"
      "el.dispatchEvent(new MouseEvent('mouseup',opts));"
      "el.dispatchEvent(new MouseEvent('click',opts));"
      "return 'clicked '+targetText+' at '+Math.round(best.x)+','+Math.round(best.y)+' el='+el.tagName;})()")
print("CLICK:", eval_js(js)[:250])
time.sleep(4)

# 读结果
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    print("URL:", res.get("url", ""))
    pt = res.get("page_text", "")
    print("文本前250:", pt[:250])
    print("文本末60:", pt[-60:])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "go"
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_cg.py && cd /home/ubuntu/xiami && python3 /tmp/mt_cg.py {target}"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1400:])

if __name__ == "__main__":
    main()
