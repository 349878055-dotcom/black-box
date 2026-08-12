#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键在虾米 App 手机内置浏览器打开 glyy 登录页（验证码登录 tab）。

关键：必须走 App 原生 navigate（execCmd('navigate')），原生会
「切浏览器界面 + loadUrl」，手机上才能看到可操作的浏览器界面；
不能只 CDP Page.navigate（那只加载页面、不切原生界面）。

用法：
  python3 tools/glyy_open_login.py          # 打开并切到验证码登录 tab
  python3 tools/glyy_open_login.py --pass   # 打开并切到密码登录 tab

真实站点（与微信小程序同一后端，H5 前端）：
  https://www.ih.njglyy.com:9532/caring/front/ps-patient-front/
登录接口（纯 API，不依赖微信）：
  POST /caring/api/sms/captcha?phone=       图形验证码
  POST /caring/api/sms?phone=&type=1&code=  发短信验证码
  POST /caring/api/v4/session/phone?phone=&code= 登录（token 存手机 CredentialStore）
"""
import json
import sys
import time

import websocket

GLYY_URL = "https://www.ih.njglyy.com:9532/caring/front/ps-patient-front/"
MODE = "1" if "--pass" not in sys.argv else "2"  # 1=验证码登录 2=密码登录

# 虾米 App 重启后 WebView 调试 socket 名会变（@webview_devtools_remote_<pid>），
# 页面 id 也随之变 → 动态从 CDP 枚举里找 ui.html 页面，不再写死。
def _ui_page_ws():
    import urllib.request
    for _ in range(10):
        try:
            pages = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5))
            for p in pages:
                if "ui.html" in p.get("url", ""):
                    return p["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("未找到 App 主界面 ui.html 页面，请确认虾米 App 在前台且 CDP(9222) 已转发")


def main():
    print(f"[1/3] 连接 App 主界面 (CDP) 并触发原生 navigate …")
    WS = _ui_page_ws()
    ws = websocket.create_connection(WS, timeout=95)
    params = {
        "url": GLYY_URL,
        "ua": "wechat",
        "login_skill": "glyy",
        "referer": "https://servicewechat.com/wx74a991a2ae77468d/330/page-frame.html",
        "timeout_ms": 90000,
    }
    expr = ("(async () => { "
            "const params = " + json.dumps(params, ensure_ascii=False) + "; "
            "const res = await execCmd('navigate', params); "
            "return JSON.stringify(res); })()")
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
    deadline = time.time() + 90
    result = None
    while time.time() < deadline:
        try:
            msg = json.loads(ws.recv())
        except Exception:
            break
        if msg.get("id") == 1:
            result = msg
            break
    if result is None:
        print("导航超时未回执")
    else:
        r = result.get("result", {})
        val = (r.get("result") or {}).get("value") if isinstance(r.get("result"), dict) else None
        print("导航回执:", val or "已下发（加载中）")
    ws.close()

    print("[2/3] 等待页面加载完成 …")
    time.sleep(8)

    print(f"[3/3] 处理弹窗 + 切到 {'验证码' if MODE=='1' else '密码'}登录 tab …")
    import urllib.request
    pages = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5))
    bw = [p for p in pages if "ih.njglyy" in p.get("url", "")]
    if not bw:
        print("未找到浏览器页，请确认已触发 navigate")
        return
    WS = bw[0]["webSocketDebuggerUrl"]
    ws = websocket.create_connection(WS, timeout=40)
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))
    while True:
        if json.loads(ws.recv()).get("id") == 1:
            break
    expr = """
    (async () => {
      window.confirm = () => true; window.alert = () => {};
      const app = document.querySelector('#app');
      let root = app && (app.__vue__ || null);
      if (!root) { for (const el of document.querySelectorAll('*')) { if (el.__vue__) { root = el.__vue__; break; } } }
      function findLogin(comp, depth) {
        if (!comp || depth > 15) return null;
        const d = comp.$data || {};
        if ('loginWay' in d) return comp;
        for (const c of (comp.$children || [])) { const r = findLogin(c, depth+1); if (r) return r; }
        return null;
      }
      const login = root ? findLogin(root, 0) : null;
      if (login) { login.$data.loginWay = '%s'; return 'switched to ' + login.$data.loginWay; }
      return 'login component not found';
    })()
    """ % MODE
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == 2:
            print("切换结果:", m.get("result", {}).get("result", {}).get("value"))
            break
    time.sleep(2)
    # 关键保护：切 loginWay 可能触发路由跳 #/verification（空路由渲染 null）→ 回退到 #/ 根路由
    chk = """
    (async () => {
      return JSON.stringify({url: location.href, appHtml: document.querySelector('#app') ? document.querySelector('#app').innerHTML.slice(0,40) : ''});
    })()
    """
    ws.send(json.dumps({"id": 6, "method": "Runtime.evaluate",
                        "params": {"expression": chk, "returnByValue": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == 6:
            break
    if "verification" in json.dumps(m.get("result", {})):
        print("检测到 verification 空路由 → 回退 #/ 根路由")
        ws.send(json.dumps({"id": 7, "method": "Page.navigate",
                            "params": {"url": "https://www.ih.njglyy.com:9532/caring/front/ps-patient-front/#/"}}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == 7:
                break
        time.sleep(12)
        # 回退后再切一次 loginWay
        ws.send(json.dumps({"id": 8, "method": "Runtime.evaluate",
                            "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == 8:
                print("重切:", m.get("result", {}).get("result", {}).get("value"))
                break
        time.sleep(2)
    # 移除 Vant 遮罩/弹窗（否则挡住表单，点不到）
    rm_expr = """
    (async () => {
      document.querySelectorAll('.van-overlay, .van-dialog').forEach(el => el.remove());
      return JSON.stringify({overlayGone: !document.querySelector('.van-overlay')});
    })()
    """
    ws.send(json.dumps({"id": 5, "method": "Runtime.evaluate",
                        "params": {"expression": rm_expr, "awaitPromise": True, "returnByValue": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == 5:
            break
    time.sleep(1)
    # 自动填手机号 + 关弹窗（--phone 指定，默认 18913300200）
    import re as _re
    phone = "18913300200"
    for a in sys.argv:
        if a.startswith("--phone="):
            phone = a.split("=", 1)[1]
    fill_expr = """
    (async () => {
      window.confirm = () => true; window.alert = () => {};
      document.querySelectorAll('button').forEach(b=>{ if(b.textContent.trim()==='确认'){ b.click(); } });
      const input = document.querySelector('input[type=tel], input[placeholder*=手机]');
      let filled = '';
      if (input) {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        setter.call(input, '%s');
        input.dispatchEvent(new Event('input', {bubbles:true}));
        input.dispatchEvent(new Event('change', {bubbles:true}));
        filled = input.value;
      }
      return JSON.stringify({filled, hasInput: !!input});
    })()
    """ % phone
    ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate",
                        "params": {"expression": fill_expr, "awaitPromise": True, "returnByValue": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == 3:
            print("填手机号:", m.get("result", {}).get("result", {}).get("value"))
            break
    time.sleep(1)
    ws.send(json.dumps({"id": 4, "method": "Runtime.evaluate",
                        "params": {"expression": "JSON.stringify({url:location.href,text:document.body?document.body.innerText.slice(0,180):''})",
                                   "returnByValue": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == 4:
            print("页面状态:", m.get("result", {}).get("result", {}).get("value"))
            break
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == 3:
            print("页面状态:", m.get("result", {}).get("result", {}).get("value"))
            break
    ws.close()
    print("\n完成：手机屏幕应显示 glyy「手机验证码登录」页，手机号已自动填入。")
    print("  下一步：在手机上点「获取手机验证码」→ 收短信 → 填码 → 登录。")
    print("  提示：可用 --phone=手机号 指定其它号码；--pass 切到密码登录 tab。")


if __name__ == "__main__":
    main()
