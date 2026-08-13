"""njpkzyy · 公开查询 + 深链基础：常量 + 直连请求 + 签名 + 统一返回。

后端：https://hzfw.njpkzyy.com:18086（公开 HTTP API，普通 UA 可访问，实测 HTTP 200）
签名：sign = SHA1(MD5(appKey + timestamp + nonce))，appKey=1202patient
请求头：agent_id（普通接口=6396cb2be4b0dc1899f48fe7；在线号/支付渠道=62da65d4e4b0e0a247890d84）
认证：查询类公开免登录（无需 Bearer）

⚠️ 本包只交付「公开查询 + 深链直达挂号页」，不做登录/挂号代做：
   浦口登录=微信人脸实名核身（getPhoneNumber/人脸核身），客户虾米 App 非真微信拿不到，
   故不实现 wechat_login/register_online（见 contract.not_deliver）。
   查询改公开直连（requests），本地可跑，替代旧的「蓝图+手机通道」形态。
"""
from __future__ import annotations

import hashlib
import random
import time
import urllib.parse

import requests

BASE = "https://hzfw.njpkzyy.com:18086/api"
APP_KEY = "1202patient"
AGENT_ID = "6396cb2be4b0dc1899f48fe7"             # 普通公开接口
ONLINE_AGENT_ID = "62da65d4e4b0e0a247890d84"      # 在线号/支付渠道接口
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
TIMEOUT = 15


def _sign() -> tuple[str, str, str]:
    """sign = SHA1(MD5(appKey + timestamp + nonce))；返回 (timestamp, nonce, sign)。"""
    ts = str(int(time.time() * 1000))
    nonce = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=16))
    sign = hashlib.sha1(hashlib.md5((APP_KEY + ts + nonce).encode()).hexdigest().encode()).hexdigest()
    return ts, nonce, sign


class NjpkzyyBase:
    """公开查询基础设施：_get 直连（带签名头）+ _out 统一返回。"""

    def __init__(self, executor=None, **_kwargs) -> None:
        # njpkzyy 走云端直连（requests），不需要手机通道 executor；
        # 保留 __init__ 兼容 registry._get_instance 的 cls(executor=...) 实例化。
        self.executor = executor

    def _get(self, path: str, params: dict | None = None, agent_id: str | None = None) -> dict:
        ts, nonce, sign = _sign()
        headers = {
            "User-Agent": UA,
            "agent_id": agent_id or AGENT_ID,
            "appKey": APP_KEY,
            "role": "patient",
            "hospital": "1202",
            "timestamp": ts,
            "nonce": nonce,
            "sign": sign,
            "Accept": "*/*",
        }
        url = BASE + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        try:
            r = requests.get(url, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
        return self._parse(r)

    def _parse(self, r: requests.Response) -> dict:
        try:
            j = r.json()
        except ValueError:
            return {"ok": False, "status": r.status_code, "error": "响应非 JSON",
                    "raw": (r.text or "")[:200]}
        return {
            "ok": isinstance(j, dict) and j.get("code") in (0, "0"),
            "status": r.status_code,
            "data": j.get("data") if isinstance(j, dict) else j,
            "message": j.get("message") if isinstance(j, dict) else "",
        }

    def _out(self, res: dict, default=None):
        """统一出口：ok 时返回 data，失败返回 {ok:false, error}。"""
        if res.get("ok"):
            return res.get("data") if res.get("data") is not None else default
        return {"ok": False, "error": res.get("message") or res.get("error", "请求失败")}
