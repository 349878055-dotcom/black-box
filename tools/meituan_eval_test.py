#!/usr/bin/env python3
"""美团 H5 菜单页 eval 测试（在远程云端执行，因 API 在 140.143.144.28:19000）。
用法: python3 tools/meituan_eval_test.py <list|add|cart|dump>"""
import sys, os, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.deploy_agent_glyy import _ssh

DEVICE = "349878055@qq.com"

# 远程执行脚本（base64 传输避免转义）
REMOTE_PY = '''
import urllib.request, json, base64, sys

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
    # 直接传解码后的 JS（不包 eval()，避免页面 CSP 禁止 eval）。中文经 base64 传输保证编码。
    s, b = call(API + "/api/v1/dev/browser",
                {"device_id": DEVICE, "cmd": "eval", "params": {"js": js}}, tok)
    return b

action = sys.argv[1] if len(sys.argv) > 1 else "list"
if action == "add":
    # 遍历 spu 卡片找"韩式香辣风味拌饭"，点其加购按钮（避免内层引号嵌套）
    js = ("(function(){var a=document.querySelectorAll('dd[data-tag=spu]');"
          "for(var i=0;i<a.length;i++){var e=a[i];"
          "if((e.innerText||'').indexOf('韩式香辣风味拌饭')>=0){"
          "var plus=e.querySelector('.plus_mbYhg0');if(plus){plus.click();return 'clicked';}}}"
          "return 'notfound';})()")
    print("ADD:", eval_js(js)[:300])
elif action == "cart":
    js = ("(function(){var r={};var e=document.querySelector('[class*=cart]');"
          "if(e)r.cart=(e.innerText||'').slice(0,200);"
          "var b=document.querySelector('[class*=settle],[class*=submit]');"
          "if(b)r.settle=(b.innerText||'').slice(0,100);"
          "return JSON.stringify(r);})()")
    print("CART:", eval_js(js)[:400])
elif action == "dump":
    js = ("(function(){var out={};"
          "for(var k in window){if(k.toLowerCase().indexOf('store')>=0||k.toLowerCase().indexOf('state')>=0){"
          "try{var v=window[k];if(v&&typeof v==='object')out[k]=JSON.stringify(v).slice(0,300);}catch(e){}}}"
          "return JSON.stringify(out);})()")
    print("DUMP:", eval_js(js)[:1000])
else:
    js = ("(function(){var r=[];var a=document.querySelectorAll('dd[data-tag=spu]');"
          "for(var i=0;i<a.length&&i<20;i++){var e=a[i];var t=(e.innerText||'').split('\\n')[0]||'';"
          "var plus=e.querySelector('.plus_mbYhg0');"
          "r.push(t+(plus?' [可加购]':''));}return JSON.stringify(r);})()")
    print("SPUS:", eval_js(js)[:1500])
'''

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "list"
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_eval.py && cd /home/ubuntu/xiami && python3 /tmp/mt_eval.py {action}"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-2000:])

if __name__ == "__main__":
    main()
