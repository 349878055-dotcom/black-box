#!/usr/bin/env python3
"""Chrome CDP 操作美团 H5（无第三方依赖，手写 WebSocket 客户端）。
用法:
  python3 tools/cdp_meituan.py mockloc     # mock 南京定位(32.055946,118.607651)并重载
  python3 tools/cdp_meituan.py read        # 读当前页面文本
  python3 tools/cdp_meituan.py js "<expr>" # 执行 JS 并返回
  python3 tools/cdp_meituan.py netwatch    # 监听网络请求 20s
"""
import sys, json, time, os, struct, hashlib, base64, socket, urllib.request

CDP = "http://127.0.0.1:9222"

def get_page():
    req = urllib.request.urlopen(CDP + "/json")
    pages = json.loads(req.read().decode())
    for p in pages:
        if p.get("type") == "page" and ("waimai" in p.get("url","") or "meituan" in p.get("url","")):
            return p
    for p in pages:
        if p.get("type") == "page":
            return p
    return None

class WS:
    def __init__(self, url):
        u = url.replace("ws://", "http://")
        # 解析 host:port/path
        from urllib.parse import urlparse
        pu = urlparse(url)
        host, port = pu.hostname, pu.port or 80
        path = pu.path or "/"
        self.sock = socket.create_connection((host, port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        hand = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(hand.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.sock.recv(4096)
        if b"101" not in resp.split(b"\r\n",1)[0]:
            raise RuntimeError("WS handshake failed: " + resp[:200].decode())
        self.msgid = 0
    def _send_frame(self, payload, opcode=1):
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126); header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127); header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)
    def _recv_frame(self):
        h = self.sock.recv(2)
        if len(h) < 2: raise RuntimeError("recv closed")
        opcode = h[0] & 0x0F
        n = h[1] & 0x7F
        if n == 126: n = struct.unpack(">H", self.sock.recv(2))[0]
        elif n == 127: n = struct.unpack(">Q", self.sock.recv(8))[0]
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk: break
            data += chunk
        return opcode, data.decode("utf-8", "replace")
    def send(self, method, params=None):
        self.msgid += 1
        msg = json.dumps({"id": self.msgid, "method": method, "params": params or {}})
        self._send_frame(msg.encode())
        # 读直到拿到对应 id
        while True:
            op, data = self._recv_frame()
            if op == 8: raise RuntimeError("closed")
            try:
                obj = json.loads(data)
            except Exception:
                continue
            if obj.get("id") == self.msgid:
                if "error" in obj:
                    raise RuntimeError(json.dumps(obj["error"]))
                return obj.get("result", {})
    def close(self):
        try: self._send_frame(b"", 8)
        except Exception: pass
        try: self.sock.close()
        except Exception: pass

def main():
    page = get_page()
    if not page:
        print("NO PAGE"); return
    ws = WS(page["webSocketDebuggerUrl"])
    action = sys.argv[1] if len(sys.argv) > 1 else "read"

    if action == "mockloc":
        ws.send("Emulation.setGeolocationOverride", {"latitude": 32.055946, "longitude": 118.607651, "accuracy": 30})
        print("geolocation mock set")
        ws.send("Page.reload", {"ignoreCache": True})
        time.sleep(6)
        r = ws.send("Runtime.evaluate", {"expression": "document.body.innerText.slice(0,400)", "returnByValue": True})
        print("PAGE TEXT:", r.get("result", {}).get("value", "")[:400])
    elif action == "read":
        r = ws.send("Runtime.evaluate", {"expression": "document.body.innerText.slice(0,500)", "returnByValue": True})
        print("URL:", page["url"])
        print("TEXT:", r.get("result", {}).get("value", "")[:500])
    elif action == "js":
        expr = sys.argv[2]
        r = ws.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        print("RESULT:", json.dumps(r.get("result", {}), ensure_ascii=False)[:800])
    elif action == "netwatch":
        ws.send("Network.enable")
        seen = set()
        t0 = time.time()
        while time.time() - t0 < 20:
            try:
                op, data = ws._recv_frame()
            except Exception:
                break
            if "requestWillBeSent" in data:
                try:
                    obj = json.loads(data)
                    url = obj.get("params", {}).get("request", {}).get("url", "")
                    if url and url not in seen and ("meituan" in url or "waimai" in url):
                        seen.add(url)
                        method = obj.get("params", {}).get("request", {}).get("method", "")
                        print(f"[{method}] {url[:150]}")
                except Exception:
                    pass
    ws.close()

if __name__ == "__main__":
    main()
