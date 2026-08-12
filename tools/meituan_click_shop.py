#!/usr/bin/env python3
"""点击美团 H5 首页的指定店铺，进店拿 poi_id。用法: python3 tools/meituan_click_shop.py <店铺关键词>"""
import sys, os, base64
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

kw = sys.argv[1] if len(sys.argv) > 1 else "挪瓦"

# 1) 找含关键词的店铺卡片元素并点击（找文本最近的可点祖先）
js = ("(function(){var kw='" + kw + "';"
      "var nodes=document.querySelectorAll('div,li,a,span');"
      "for(var i=0;i<nodes.length&&i<20000;i++){var e=nodes[i];"
      "if((e.innerText||'').indexOf(kw)>=0&&(e.innerText||'').length<80){"
      "var c=e;for(var k=0;k<4;k++){if(c.onclick||c.getAttribute('onclick')||c.tagName==='A'||c.getAttribute('data-')!==null){"
      "try{c.click();return 'clicked '+c.tagName+':'+(c.innerText||'').slice(0,30);}catch(err){}}"
      "c=c.parentElement;if(!c)break;}}}"
      "return 'notfound';})()")

print("CLICK:", eval_js(js)[:200])
time.sleep(3)

# 2) 读取进店后 URL
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    print("URL:", res.get("url", ""))
    print("文本前150:", res.get("page_text", "")[:150])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "挪瓦"
    # 把 kw 替换进 REMOTE_PY 的默认值
    py = REMOTE_PY.replace('sys.argv[1] if len(sys.argv) > 1 else "挪瓦"',
                           '"%s"' % kw)
    b64 = base64.b64encode(py.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_click.py && cd /home/ubuntu/xiami && python3 /tmp/mt_click.py {kw}"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1400:])

if __name__ == "__main__":
    main()
