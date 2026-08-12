#!/usr/bin/env python3
"""美团 H5 全自动下单测试（本地 adb + 云端 eval）。
流程: 回首页→进店→加购→加入购物车→去结算→读结算页。
用法: python3 tools/meituan_auto.py [店铺] [菜品]
"""
import sys, os, base64, time, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.deploy_agent_glyy import _ssh

DEVICE = "349878055@qq.com"

# 云端执行 eval/navigate/read 的模板
REMOTE_HELPER = r'''
import urllib.request, json, sys
API = "http://127.0.0.1:19000"
DEVICE = "349878055@qq.com"
def call(url, obj, tok=None):
    headers = {"Content-Type": "application/json"}
    if tok: headers["Authorization"] = "Bearer " + tok
    data = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
s, b = call(API + "/api/v1/auth/login", {"email": "349878055@qq.com", "password": "jintao0341"})
tok = json.loads(b).get("access_token", "")
action = sys.argv[1] if len(sys.argv) > 1 else "read"
if action == "eval":
    js = sys.argv[2]
    if js.startswith("__B64__"):
        import base64 as _b64
        js = _b64.b64decode(js.replace("__B64__", "")).decode("utf-8")
    s, b = call(API + "/api/v1/dev/browser", {"device_id": DEVICE, "cmd": "eval", "params": {"js": js}}, tok)
    print(b)
elif action == "nav":
    url = sys.argv[2]; ua = sys.argv[3] if len(sys.argv) > 3 else ""
    p = {"url": url, "timeout_ms": 25000}
    if ua: p["ua"] = ua
    s, b = call(API + "/api/v1/dev/browser", {"device_id": DEVICE, "cmd": "navigate", "params": p}, tok)
    print(b)
elif action == "read":
    s, b = call(API + "/api/v1/dev/browser", {"device_id": DEVICE, "cmd": "read", "params": {}}, tok)
    print(b)
'''

def cloud(action, *args):
    """在云端执行 helper（base64 传输避免转义）"""
    b64 = base64.b64encode(REMOTE_HELPER.encode()).decode()
    args_str = " ".join(f"'{a}'" for a in args)
    cmd = f"echo {b64} | base64 -d > /tmp/mt_helper.py && cd /home/ubuntu/xiami && python3 /tmp/mt_helper.py {action} {args_str}"
    ok, out = _ssh(cmd, timeout=60)
    return out

def eval_js(js):
    # 传 base64 避免特殊字符
    jb64 = base64.b64encode(js.encode()).decode()
    out = cloud("eval", f"__B64__{jb64}")
    return out

def read_page():
    out = cloud("read")
    try:
        # 提取 JSON 里的 res
        import re
        m = re.search(r'\{.*\}', out, re.S)
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}

def adb_tap(x, y):
    try:
        subprocess.run(["adb", "shell", "input", "tap", str(int(x)), str(int(y))], timeout=15)
        return True
    except Exception:
        return False

def get_pos(text, prefer_bottom=True):
    js = ("(function(){var kw='" + text + "';var best=null;var a=document.querySelectorAll('*');"
          "for(var i=0;i<a.length&&i<60000;i++){var e=a[i];var t=(e.innerText||'').trim();"
          "if(t===kw){var rect=e.getBoundingClientRect();if(rect.width>0&&rect.height>0){"
          "var y=rect.top+rect.height/2;" + ("if(!best||y>best.y)" if prefer_bottom else "if(!best||y<best.y)") +
          "best={x:rect.left+rect.width/2,y:y};}}}"
          "return best?Math.round(best.x)+','+Math.round(best.y):'nf';})()")
    try:
        out = eval_js(js)
        import re
        m = re.search(r'"result":"([^"]*)"', out)
        pos = m.group(1) if m else "nf"
        if pos == "nf": return None
        x, y = pos.split(",")
        return float(x), float(y)
    except Exception:
        return None

def adb_click_text(text, prefer_bottom=True):
    pos = get_pos(text, prefer_bottom)
    if not pos: return False
    return adb_tap(*pos)

def main():
    shop = sys.argv[1] if len(sys.argv) > 1 else "塔斯汀"
    dish = sys.argv[2] if len(sys.argv) > 2 else "徐福牛堡"
    log = []

    # 回首页 browser UA
    cloud("nav", "https://h5.waimai.meituan.com/waimai/mindex/home", "browser")
    time.sleep(5)
    print("回首页 ok"); log.append("回首页 ok")

    # 进店
    js_enter = ("(function(){var nodes=document.querySelectorAll('div,li,a,span');"
                "for(var i=0;i<nodes.length&&i<20000;i++){var e=nodes[i];"
                "if((e.innerText||'').indexOf('" + shop + "')>=0&&(e.innerText||'').length<80){"
                "var c=e;for(var k=0;k<4;k++){if(c.onclick||c.getAttribute('onclick')||c.tagName==='A'){try{c.click();return 'clicked';}catch(err){}}"
                "c=c.parentElement;if(!c)break;}}}return 'notfound';})()")
    out = eval_js(js_enter)
    print("进店:", out.strip()[:100]); log.append("进店")
    time.sleep(4)

    # 加购
    js_add = ("(function(){var a=document.querySelectorAll('dd[data-tag=spu]');"
              "for(var i=0;i<a.length;i++){var e=a[i];var t=(e.innerText||'');"
              "if(t.indexOf('" + dish + "')>=0){var b=e.querySelector('.sqt-menu-add-buttons,[class*=btnGroup]');if(!b)b=e;"
              "b.scrollIntoView({block:'center'});var rect=b.getBoundingClientRect();"
              "window.__addPos=Math.round(rect.left+rect.width/2)+','+Math.round(rect.top+rect.height/2);"
              "b.click();return 'clicked '+window.__addPos;}}return 'notfound';})()")
    out = eval_js(js_add)
    print("加购JS:", out.strip()[:120]); log.append("加购JS")
    time.sleep(3)

    # 若没弹加入购物车 → adb 点加购按钮
    rp = read_page()
    pt = str(rp.get("page_text", ""))
    if "加入购物车" not in pt:
        js_pos = "(function(){return window.__addPos||'nf';})()"
        out = eval_js(js_pos)
        import re
        m = re.search(r'"result":"([^"]*)"', out)
        pos = m.group(1) if m else "nf"
        if pos != "nf":
            x, y = pos.split(",")
            adb_tap(float(x), float(y))
            print("adb加购:", pos); log.append("adb加购")
            time.sleep(3)

    # 加入购物车（adb 真实点击）
    if adb_click_text("加入购物车"):
        print("加入购物车 ok"); log.append("加入购物车 ok")
    else:
        print("加入购物车 未找到"); log.append("加入购物车 未找到")
    time.sleep(3)

    # 去结算
    if adb_click_text("去结算"):
        print("去结算 ok"); log.append("去结算 ok")
    else:
        print("去结算 未找到"); log.append("去结算 未找到")
    time.sleep(4)

    # 读结算页
    r5 = read_page()
    pt = str(r5.get("page_text", ""))
    print("结算页前250:", pt[:250]); log.append("结算页: " + pt[:100])

    print("\n=== LOG ===")
    for l in log:
        print(" -", l)

if __name__ == "__main__":
    main()
