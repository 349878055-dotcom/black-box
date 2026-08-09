"""njpkzyy_new 基础：常量 + 基础设施（蓝图生成 / 手机执行 / 解析 / 统一返回）。

后端：https://hzfw.njpkzyy.com:18086（南京市浦口区中医院 微信小程序，患者服务）
签名：sign = SHA1(MD5(appKey + timestamp + nonce))，appKey=1202patient（与手机端 glyy_sha1_md5 完全一致）
agent_id：普通接口用 6396cb2be4b0dc1899f48fe7；在线号/挂号类接口必须用 62da65d4e4b0e0a247890d84（用错返回「应用系统繁忙」）
认证：查询类公开接口免登录；登录态 = 微信授权登录 POST /api/session/wechat/ma → Bearer access_token（存手机本地凭据库）
UA  ：必须用微信 UA（抓包实测，缺了后端可能超时/拒绝）

Device-as-Proxy：云端组装蓝图 → 手机直连 → 回传 skill_result → 云端解析。
⚠️ 未注入 executor 直接报错（禁云端直连，与 glyy 同铁律）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse

logger = logging.getLogger("xiami.njpkzyy_new")

BASE = "https://hzfw.njpkzyy.com:18086"
APP_KEY = "1202patient"
AGENT_ID = "6396cb2be4b0dc1899f48fe7"            # 普通接口（公开查询）
ONLINE_AGENT_ID = "62da65d4e4b0e0a247890d84"     # 在线号/挂号类接口（抓包实测必须用）
ROLE = "patient"
HOSPITAL = "1202"
REFERER = "https://servicewechat.com/wxca05bc9d9f69226c/21/page-frame.html"
UA_WX = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger")

# ── 蓝图占位符（手机 SkillExecutor 本地替换）──
PH_TS = "{{timestamp}}"
PH_NONCE = "{{nonce}}"
PH_SIGN = "{{sign}}"
PH_TOKEN = "{{token}}"


class NjpkzyyNewBase:
    """njpkzyy_new 基础设施：蓝图生成 / 手机执行通道 / 响应解析 / 统一返回。"""

    def __init__(self, access_token: str | None = None, executor=None) -> None:
        # 手机通道执行函数（async (blueprint) -> {ok,status,headers,body,error}）
        # 由 registry.run 注入（绑定 bridge.send_skill_request）；必须注入，否则报错
        self.access_token = access_token or ""
        self.executor = executor

    def _blueprint(self, path: str, params: dict | None = None, body: dict | None = None,
                   bearer: bool = True, method: str = "GET",
                   agent_id: str | None = None) -> dict:
        """生成可在手机端执行的请求蓝图（sign 等由手机本地按 sign_type 计算）。

        agent_id：默认普通接口用 AGENT_ID；在线号/挂号类传 ONLINE_AGENT_ID。
        """
        headers = {
            "User-Agent": UA_WX,
            "appKey": APP_KEY,           # 手机端 computeSign 按此 key 取 appKey（须大写 K）
            "agent_id": agent_id or AGENT_ID,
            "role": ROLE,
            "timestamp": PH_TS, "nonce": PH_NONCE, "sign": PH_SIGN,
            "Content-Type": "application/json", "Accept": "*/*",
            "Referer": REFERER, "xweb_xhr": "1",
        }
        if bearer:
            headers["Authorization"] = "Bearer " + PH_TOKEN
        url = BASE + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        bp = {
            "skill": "njpkzyy_new",
            "request": {
                "method": method, "url": url, "headers": headers,
                "body": body, "sign_type": "glyy_sha1_md5",
            },
            "credential": {"kind": "bearer" if bearer else "none", "target": "njpkzyy_new"},
        }
        return bp

    def describe_request(self, method: str, **params) -> dict | None:
        """第 3 条：返回方法对应的请求蓝图（供第 2 条下发手机）。

        单请求方法 → 完整蓝图；复合方法（wechat_login/register_online…）→ None（云端编排）。
        """
        m = self._REQUEST_MAP.get(method)
        if not m:
            return None
        path_t, http, bearer, agent_id = m
        p = dict(params or {})
        try:
            path = path_t.format(**p)
        except KeyError:
            return None
        # 已用于路径的参数从 query 中剔除
        q = {k: v for k, v in p.items() if ("{" + k + "}") not in path_t}
        if http == "POST":
            return self._blueprint(path, body=q or None, bearer=bearer,
                                   method="POST", agent_id=agent_id)
        return self._blueprint(path, params=q or None, bearer=bearer,
                               method="GET", agent_id=agent_id)

    def parse_response(self, method: str, raw_body: str) -> dict:
        """第 3 条：云端解析手机回传的原始响应为结构化数据。"""
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
        """经手机执行通道执行蓝图（bridge.send_skill_request → skill_result）。"""
        last = None
        for i in range(retries):
            try:
                res = await self.executor(bp)
                if not isinstance(res, dict):
                    return {"ok": False, "error": "手机执行返回异常"}
                if not res.get("ok"):
                    err = str(res.get("error") or "手机执行失败")
                    logger.warning("[njpkzyy_new] 手机执行失败 status=%s error=%s url=%s",
                                   res.get("status"), err[:200],
                                   str(bp.get("request", {}).get("url", ""))[:100])
                    need = ("登录" in err or "token" in err.lower())
                    out = {"ok": False, "error": err, "status": res.get("status")}
                    if need:
                        out["need_login"] = True
                    return out
                body = str(res.get("body") or "")
                logger.info("[njpkzyy_new] 手机执行成功 status=%s body前250=%s",
                            res.get("status"), body[:250])
                parsed = self._parse_text(body)
                if isinstance(parsed, dict):
                    msg = str(parsed.get("message") or parsed.get("dev_message") or "")
                    code = parsed.get("code")
                    if (not parsed.get("code") == 0 and
                            ("token" in msg.lower() or "login" in msg.lower()
                             or "未登录" in msg or code in (30007, 401, 403))):
                        return {"ok": False, "need_login": True,
                                "error": "登录态失效或未登录，请重新微信授权登录",
                                "status": res.get("status")}
                return parsed
            except Exception as e:
                last = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}", "attempt": i + 1}
                await asyncio.sleep(2 * (i + 1))
        return last

    async def _get(self, path: str, params: dict | None = None, bearer: bool = True,
                   agent_id: str | None = None, timeout: int = 25, retries: int = 3) -> dict:
        """GET：仅走手机通道（禁云端直发）。未注入 executor 直接报错。"""
        if not self.executor:
            return {"ok": False, "error": "njpkzyy_new 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, bearer=bearer, method="GET", agent_id=agent_id)
        return await self._exec(bp, timeout, retries)

    async def _post(self, path: str, body: dict | None = None, params: dict | None = None,
                    bearer: bool = True, agent_id: str | None = None,
                    timeout: int = 25, retries: int = 3) -> dict:
        """POST：仅走手机通道（禁云端直发）。未注入 executor 直接报错。"""
        if not self.executor:
            return {"ok": False, "error": "njpkzyy_new 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, body=body, bearer=bearer,
                             method="POST", agent_id=agent_id)
        return await self._exec(bp, timeout, retries)

    def ok(self, j: dict) -> bool:
        return isinstance(j, dict) and j.get("code") in (0, "0")

    def _out(self, j: dict, default=None):
        """统一方法返回：手机执行失败(need_login/error) → 透传错误 dict；否则 data 或 default。"""
        if isinstance(j, dict) and (j.get("error") or j.get("need_login")):
            return j
        if self.ok(j):
            d = j.get("data")
            return d if d is not None else default
        return default
