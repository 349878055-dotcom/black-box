"""njpkzyy · 公开查询 + 深链基础：常量 + 手机通道 + 签名占位符 + 统一返回。

后端：https://hzfw.njpkzyy.com:18086（公开 HTTP API，普通 UA 可访问）
签名：sign = SHA1(MD5(appKey + timestamp + nonce))，appKey=1202patient
      由手机 SkillExecutor 按 sign_type=sha1_md5 本地计算，云端只放占位符。
请求头：agent_id（普通接口=6396cb2be4b0dc1899f48fe7；在线号/支付渠道=62da65d4e4b0e0a247890d84）
认证：查询类公开免登录（无需 Bearer）

⚠️ 本包只交付「公开查询 + 深链直达挂号页」，不做登录/挂号代做。
   查询也走手机通道（禁云端直连）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse

logger = logging.getLogger("xiami.njpkzyy")

BASE = "https://hzfw.njpkzyy.com:18086/api"
APP_KEY = "1202patient"
AGENT_ID = "6396cb2be4b0dc1899f48fe7"             # 普通公开接口
ONLINE_AGENT_ID = "62da65d4e4b0e0a247890d84"      # 在线号/支付渠道接口
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
TIMEOUT = 25

PH_TS = "{{timestamp}}"
PH_NONCE = "{{nonce}}"
PH_SIGN = "{{sign}}"


class NjpkzyyBase:
    """公开查询基础设施：组蓝图 → 手机直连 → 解析统一返回。"""

    def __init__(self, executor=None, **_kwargs) -> None:
        self.executor = executor

    def _blueprint(self, path: str, params: dict | None = None,
                   agent_id: str | None = None) -> dict:
        headers = {
            "User-Agent": UA,
            "agent_id": agent_id or AGENT_ID,
            "appKey": APP_KEY,
            "role": "patient",
            "hospital": "1202",
            "timestamp": PH_TS,
            "nonce": PH_NONCE,
            "sign": PH_SIGN,
            "Accept": "*/*",
        }
        url = BASE + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return {
            "skill": "njpkzyy",
            "request": {
                "method": "GET",
                "url": url,
                "headers": headers,
                "body": None,
                "sign_type": "sha1_md5",
                "sign_content": "{{appKey}}{{timestamp}}{{nonce}}",
            },
            "credential": {"kind": "none", "target": "njpkzyy"},
        }

    async def _get(self, path: str, params: dict | None = None, agent_id: str | None = None,
                   retries: int = 3, timeout: int = TIMEOUT) -> dict:
        if not self.executor:
            return {"ok": False, "error": "njpkzyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, agent_id=agent_id)
        last = None
        for i in range(retries):
            try:
                res = await self.executor(bp)
                if not isinstance(res, dict):
                    return {"ok": False, "error": "手机执行返回异常"}
                if not res.get("ok"):
                    err = str(res.get("error") or "手机执行失败")
                    logger.warning("[njpkzyy] 手机执行失败 status=%s error=%s",
                                   res.get("status"), err[:200])
                    return {"ok": False, "error": err, "status": res.get("status")}
                return self._parse_text(str(res.get("body") or ""), res.get("status"))
            except Exception as e:
                last = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
                if i < retries - 1:
                    await asyncio.sleep(2 * (i + 1))
        return last

    def _parse_text(self, text: str, status=None) -> dict:
        try:
            j = json.loads(text or "{}")
        except ValueError:
            return {"ok": False, "status": status, "error": "响应非 JSON",
                    "raw": (text or "")[:200]}
        return {
            "ok": isinstance(j, dict) and j.get("code") in (0, "0"),
            "status": status,
            "data": j.get("data") if isinstance(j, dict) else j,
            "message": j.get("message") if isinstance(j, dict) else "",
        }

    def _out(self, res: dict, default=None):
        """统一出口：ok 时返回 data，失败返回 {ok:false, error}。"""
        if res.get("ok"):
            return res.get("data") if res.get("data") is not None else default
        return {"ok": False, "error": res.get("message") or res.get("error", "请求失败")}
