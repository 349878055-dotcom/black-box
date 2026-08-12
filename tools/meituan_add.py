#!/usr/bin/env python3
"""美团 H5 菜单页点加购。用法: python3 tools/meituan_add.py <菜品关键词> [spec关键词]"""
import sys, os, base64, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.deploy_agent_glyy import _ssh

REMOTE_PY = r'''
import urllib.request, json, sys, time

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

kw = sys.argv[1] if len(sys.argv) > 1 else "金奖美式"

# 找到含关键词的 spu 卡片，点击其 .sqt-menu-add-buttons 里的加购按钮
js = ("(function(){var a=document.querySelectorAll('dd[data-tag=spu]');"
      "for(var i=0;i<a.length;i++){var e=a[i];"
      "if((e.innerText||'').indexOf('" + kw + "')>=0){"
      "var btns=e.querySelector('.sqt-menu-add-buttons');"
      "if(!btns)btns=e;"
      "var clickable=btns.querySelector('[class*=plus],[aria-label],[class*=add],[class*=btn]');"
      "if(clickable){clickable.click();return 'clicked plus in '+kw;}else{btns.click();return 'clicked container '+kw;}}}"
      "return 'notfound '+kw;})()")

print("ADD:", eval_js(js)[:200])
time.sleep(3)

# 读页面（看是否弹规格选择/加入购物车）
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    print("URL:", res.get("url", ""))
    pt = res.get("page_text", "")
    print("文本末尾300:", pt[-300:])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "金奖美式"
    py = REMOTE_PY.replace('kw = sys.argv[1] if len(sys.argv) > 1 else "金奖美式"',
                           'kw = "%s"' % kw)
    b64 = base64.b64encode(py.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_add.py && cd /home/ubuntu/xiami && python3 /tmp/mt_add.py {kw}"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1200:])

if __name__ == "__main__":
    main()
