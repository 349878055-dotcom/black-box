#!/usr/bin/env python3
"""美团 H5：点击"提交订单"，读取返回（判断是打烊/风控/其他）。"""
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

# 确认当前在结算页，点"提交订单"
js = ("(function(){var a=document.querySelectorAll('*');"
      "for(var i=0;i<a.length&&i<30000;i++){var e=a[i];var t=(e.innerText||'').trim();"
      "if(t==='提交订单'){e.click();return 'clicked submit';}}return 'notfound';})()")
print("SUBMIT:", eval_js(js)[:200])
time.sleep(4)

# 读取返回（成功→支付页；失败→错误提示）
s2, b2 = call(API + "/api/v1/dev/browser",
              {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
import json as J
try:
    d = J.loads(b2); res = d.get("res", {})
    print("URL:", res.get("url", ""))
    pt = res.get("page_text", "")
    print("文本前500:", pt[:500])
except Exception as e:
    print("err", e, b2[:200])
'''

def main():
    b64 = base64.b64encode(REMOTE_PY.encode()).decode()
    cmd = f"echo {b64} | base64 -d > /tmp/mt_sub.py && cd /home/ubuntu/xiami && python3 /tmp/mt_sub.py"
    ok, out = _ssh(cmd, timeout=120)
    print(out.strip()[-1400:])

if __name__ == "__main__":
    main()
