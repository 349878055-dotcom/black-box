#!/usr/bin/env python3
"""美团 H5 结算页：检查必选项 + 点提交订单，读返回（区分 H5支付 / JSAPI / 报错）。"""
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

# 1) 检查结算页必选项（餐具数量/发票/备注是否必选）
js = ("(function(){var r={};var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<40000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='餐具数量'||t==='必选'||t==='请选择'||t==='提交订单'){"
      "if(!r[t]){r[t]=1;}}}return JSON.stringify(r);})()")
print("必选项检查:", eval_js(js)[:300])

# 2) 点"提交订单"
js2 = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<40000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='提交订单'){e.click();return 'clicked submit';}}return 'notfound';})()")
print("点提交:", eval_js(js2)[:200])
time.sleep(5)

# 3) 读提交后的页面（成功→支付页；失败→报错）
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    print("URL:", res.get("url", ""))
    pt = res.get("page_text", "")
    print("文本前500:", pt[:500])
    print("文本末100:", pt[-100:])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_sp2.py && cd /home/ubuntu/xiami && python3 /tmp/mt_sp2.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1600:])

if __name__ == "__main__":
    main()
