#!/usr/bin/env python3
"""美团 H5：完整加购流程（点加购→弹规格→点加入购物车→验证），直到购物车有货。"""
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

# 1) 点击"金奖美式"（¥9.9）的加购按钮（用 dispatchEvent 完整鼠标事件，模拟真实点击）
js_click = ("(function(){var a=document.querySelectorAll('dd[data-tag=spu]');"
      "for(var i=0;i<a.length;i++){var e=a[i];var t=(e.innerText||'');"
      "if(t.indexOf('金奖美式')>=0&&t.indexOf('9.9')>=0){"
      "var b=e.querySelector('.sqt-menu-add-buttons,[class*=btnGroup]');"
      "if(!b)b=e;var r=b.getBoundingClientRect();var x=r.left+r.width/2,y=r.top+r.height/2;"
      "var opts={bubbles:true,cancelable:true,clientX:x,clientY:y,view:window,button:0};"
      "b.dispatchEvent(new PointerEvent('pointerdown',opts));b.dispatchEvent(new MouseEvent('mousedown',opts));"
      "b.dispatchEvent(new PointerEvent('pointerup',opts));b.dispatchEvent(new MouseEvent('mouseup',opts));b.dispatchEvent(new MouseEvent('click',opts));"
      "return 'clicked add';}}}return 'notfound';})()")
print("STEP1 点加购:", eval_js(js_click)[:200])
time.sleep(2)

# 2) 点击"加入购物车"
js_cart = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<30000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='加入购物车'){var r=e.getBoundingClientRect();var x=r.left+r.width/2,y=r.top+r.height/2;"
      "var opts={bubbles:true,cancelable:true,clientX:x,clientY:y,view:window,button:0};"
      "e.dispatchEvent(new PointerEvent('pointerdown',opts));e.dispatchEvent(new MouseEvent('mousedown',opts));"
      "e.dispatchEvent(new PointerEvent('pointerup',opts));e.dispatchEvent(new MouseEvent('mouseup',opts));e.dispatchEvent(new MouseEvent('click',opts));"
      "return 'clicked cartbtn';}}}return 'notfound';})()")
print("STEP2 加入购物车:", eval_js(js_cart)[:200])
time.sleep(3)

# 3) 验证购物车
js_check = ("(function(){var e=document.querySelector('[aria-label*=购物车]');"
      "return e?e.getAttribute('aria-label'):'none';})()")
print("STEP3 购物车:", eval_js(js_check)[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_fa.py && cd /home/ubuntu/xiami && python3 /tmp/mt_fa.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-900:])

if __name__ == "__main__":
    main()
