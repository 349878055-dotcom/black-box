"""meituan_waimai 基础：常量 + 查询用手机通道（蓝图 / 执行 / 解析）。

路径 B：不持有登录态、不代支付。查询可走手机通道打公开/探路接口拿 poi_id；
操作交付在 deep_link.py（明文 scheme 拉起美团 App）。

探路来源：微信小程序 wxapkg（appid wxde8ac0a21135c07d），微信不能当交付。
⚠️ 未注入 executor 直接报错（禁云端直连）。查询接口不带 token。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse

logger = logging.getLogger("xiami.meituan_waimai")

BASE = "https://i.waimai.meituan.com"
SHANGGOU = "https://wx-shangou.meituan.com"
UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")


class MeituanWaimaiBase:
    """查询基础设施：蓝图生成 / 手机执行 / 响应解析。无登录凭据。"""

    def __init__(self, executor=None, **_kwargs) -> None:
        self.executor = executor

    def _blueprint(self, path: str, params: dict | None = None, body: dict | None = None,
                   bearer: bool = False, method: str = "GET", base: str | None = None,
                   extra_headers: dict | None = None) -> dict:
        headers = {
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Accept": "*/*",
        }
        if extra_headers:
            headers.update(extra_headers)
        url = (base or BASE) + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return {
            "skill": "meituan_waimai",
            "request": {
                "method": method, "url": url, "headers": headers, "body": body,
            },
            "credential": {"kind": "none", "target": "meituan_waimai"},
        }

    def describe_request(self, method: str, **params) -> dict | None:
        m = self._REQUEST_MAP.get(method)
        if not m:
            return None
        path_t, http, bearer, base = m
        p = dict(params or {})
        try:
            path = path_t.format(**p)
        except KeyError:
            return None
        q = {k: v for k, v in p.items() if ("{" + k + "}") not in path_t}
        if http == "POST":
            return self._blueprint(path, body=q or None, bearer=bearer,
                                   method="POST", base=base)
        return self._blueprint(path, params=q or None, bearer=bearer,
                               method="GET", base=base)

    def parse_response(self, method: str, raw_body: str) -> dict:
        try:
            j = json.loads(raw_body or "{}")
        except Exception:
            return {"ok": False, "error": "响应非 JSON", "raw": (raw_body or "")[:300]}
        return {"ok": self.ok(j), "code": j.get("code"), "data": j.get("data"),
                "message": j.get("message") or j.get("dev_message")}

    def _parse_text(self, text: str) -> dict:
        try:
            return json.loads(text)
        except Exception:
            return {"http": -1, "raw": text[:300]}

    async def _exec(self, bp: dict, timeout: int = 25, retries: int = 3) -> dict:
        last = None
        for i in range(retries):
            try:
                res = await self.executor(bp)
                if not isinstance(res, dict):
                    return {"ok": False, "error": "手机执行返回异常"}
                if not res.get("ok"):
                    err = str(res.get("error") or "手机执行失败")
                    logger.warning("[meituan_waimai] 手机执行失败 status=%s error=%s",
                                   res.get("status"), err[:200])
                    return {"ok": False, "error": err, "status": res.get("status")}
                body = str(res.get("body") or "")
                return self._parse_text(body)
            except Exception as e:
                last = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}", "attempt": i + 1}
                await asyncio.sleep(2 * (i + 1))
        return last

    async def _get(self, path: str, params: dict | None = None, bearer: bool = False,
                   base: str | None = None, timeout: int = 25, retries: int = 3,
                   extra_headers: dict | None = None) -> dict:
        if not self.executor:
            return {"ok": False, "error": "meituan_waimai 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, bearer=False, method="GET", base=base,
                             extra_headers=extra_headers)
        return await self._exec(bp, timeout, retries)

    async def _post(self, path: str, body: dict | None = None, params: dict | None = None,
                    bearer: bool = False, base: str | None = None,
                    timeout: int = 25, retries: int = 3,
                    extra_headers: dict | None = None) -> dict:
        if not self.executor:
            return {"ok": False, "error": "meituan_waimai 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, body=body, bearer=False,
                             method="POST", base=base, extra_headers=extra_headers)
        return await self._exec(bp, timeout, retries)

    def ok(self, j: dict) -> bool:
        return isinstance(j, dict) and j.get("code") in (0, "0")

    def _out(self, j: dict, default=None):
        if isinstance(j, dict) and j.get("error"):
            return j
        if self.ok(j):
            d = j.get("data")
            return d if d is not None else default
        return default
