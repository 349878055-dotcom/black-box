#!/usr/bin/env python3
"""列出美团 H5 当前菜单页的可加购菜品 + spu id。用法: python3 tools/meituan_spus.py [关键词]"""
import sys, os, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.deploy_agent_glyy import _ssh

REMOTE_PY = r'''
import urllib.request, json, sys

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

# 统计 spu 卡片 + 加购按钮数量
js1 = ("(function(){var a=document.querySelectorAll('dd[data-tag=spu]');"
       "var plus=document.querySelectorAll('.plus_mbYhg0,[class*=plus],[aria-label*=加]');"
       "return 'spus='+a.length+', plus_btns='+plus.length;})()")
print("STATS:", eval_js(js1)[:300])

# 提取 spu 卡片：id + 名称 + 是否有加购按钮 + 价格
js2 = ("(function(){var r=[];var a=document.querySelectorAll('dd[data-tag=spu]');"
       "for(var i=0;i<a.length&&i<30;i++){var e=a[i];"
       "var t=(e.innerText||'').split(String.fromCharCode(10))[0]||'';"
       "var id=e.getAttribute('data-id')||e.id||'';"
       "var plus=!!e.querySelector('.plus_mbYhg0,[class*=plus]');"
       "var price=(e.querySelector('[class*=price]')||{}).innerText||'';"
       "r.push(t+' | id='+id+' | plus='+plus+' | '+price.replace(String.fromCharCode(10),' ').slice(0,20));}"
       "return JSON.stringify(r);})()")
print("SPUS:", eval_js(js2)[:1800])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_spus.py && cd /home/ubuntu/xiami && python3 /tmp/mt_spus.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-2200:])

if __name__ == "__main__":
    main()
