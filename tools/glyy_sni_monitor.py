#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
监听电脑微信访问 glyy 的 TLS SNI 域名（找真实登录页 URL）。
用法（需 root 读 pcap）：
  sudo python3 tools/glyy_sni_monitor.py /tmp/glyy_capture.pcap
持续监控：循环解析 pcap 中的 ClientHello SNI，过滤 glyy/微信相关域名。
"""
import struct
import sys
import time

PCAP = sys.argv[1] if len(sys.argv) > 1 else "/tmp/glyy_capture.pcap"

# 关注的关键词
KEYWORDS = ("njglyy", "ih.njglyy", "servicewechat", "wx74a991a2ae77468d",
            "weixin", "qq.com", "glyy")


def parse_pcap_sni(path):
    """解析 pcap 文件，提取所有 TLS ClientHello 的 SNI 域名。"""
    seen = {}
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception as e:
        print(f"读取失败: {e}")
        return seen
    if len(data) < 24:
        return seen
    magic = data[:4]
    endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    # pcap header: magic(4) ver(2+2) thiszone(4) sigfigs(4) snaplen(4) linktype(4)
    if magic in (b"\xd4\xc3\xb2\xa1", b"\xd4\xc3\xb2\xa1".swapcase() if False else b"\x4d\x3c\xb2\xa1"):
        pass
    try:
        linktype = struct.unpack(endian + "I", data[20:24])[0]
    except Exception:
        linktype = 1  # Ethernet
    pos = 24
    while pos + 16 <= len(data):
        try:
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack(
                endian + "IIII", data[pos:pos + 16])
        except Exception:
            break
        pos += 16
        if pos + incl_len > len(data):
            break
        pkt = data[pos:pos + incl_len]
        pos += incl_len
        # 解析链路层
        offset = 0
        if linktype == 1:  # Ethernet
            offset = 14
        elif linktype == 101:  # Raw IP
            offset = 0
        elif linktype == 113:  # Linux cooked v1
            offset = 16
        elif linktype == 276:  # Linux cooked v2
            offset = 20
        if len(pkt) <= offset:
            continue
        # IP 头
        ip = pkt[offset:]
        if len(ip) < 20:
            continue
        ip_ver = ip[0] >> 4
        if ip_ver == 4:
            ihl = (ip[0] & 0x0F) * 4
            proto = ip[9]
            tcp_off = offset + ihl
        elif ip_ver == 6:
            proto = ip[6]
            tcp_off = offset + 40
        else:
            continue
        if proto != 6:  # TCP
            continue
        tcp = pkt[tcp_off:]
        if len(tcp) < 20:
            continue
        data_off = ((tcp[12] >> 4) & 0x0F) * 4
        payload = tcp[data_off:]
        # TLS record: content_type(1) version(2) length(2) ...
        if len(payload) < 5:
            continue
        # 需要 tcp 层之后才是 TLS；若 tcp 头后面直接是 TLS 记录
        if payload[0] == 0x16:  # Handshake
            # handshake: type(1) len(3) ...
            if len(payload) < 9:
                continue
            hs_type = payload[5]
            if hs_type != 0x01:  # ClientHello
                continue
            # ClientHello: client_version(2) random(32) session_id...
            body = payload[9:]
            try:
                i = 0
                sid_len = body[32]
                i = 32 + 1 + sid_len
                cs_len = struct.unpack(">H", body[i:i + 2])[0]
                i += 2 + cs_len
                comp_len = body[i]
                i += 1 + comp_len
                ext_len = struct.unpack(">H", body[i:i + 2])[0]
                i += 2
                end = i + ext_len
                while i + 4 <= end:
                    ext_type = struct.unpack(">H", body[i:i + 2])[0]
                    ext_len2 = struct.unpack(">H", body[i + 2:i + 4])[0]
                    ext_data = body[i + 4:i + 4 + ext_len2]
                    if ext_type == 0:  # server_name
                        if len(ext_data) >= 5:
                            name_len = struct.unpack(">H", ext_data[3:5])[0]
                            name = ext_data[5:5 + name_len].decode("utf-8", "replace")
                            seen.setdefault(name, 0)
                            seen[name] += 1
                    i += 4 + ext_len2
            except Exception:
                pass
    return seen


def main():
    print(f"监控 SNI: {PCAP}")
    last_size = 0
    printed = set()
    while True:
        try:
            import os
            sz = os.path.getsize(PCAP)
        except Exception:
            sz = 0
        if sz != last_size:
            last_size = sz
            sni = parse_pcap_sni(PCAP)
            for domain, cnt in sorted(sni.items()):
                low = domain.lower()
                if any(k in low for k in KEYWORDS) and domain not in printed:
                    printed.add(domain)
                    print(f"[SNI] {domain} (count={cnt})", flush=True)
            # 打印所有新域名（调试）
            for domain in sni:
                if domain not in printed and ("." in domain):
                    printed.add(domain)
                    if any(k in domain.lower() for k in KEYWORDS):
                        print(f"[SNI][相关] {domain}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
