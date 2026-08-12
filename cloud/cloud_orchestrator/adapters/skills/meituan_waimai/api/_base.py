"""meituan_waimai 基础：常量 + 基础设施（蓝图生成 / 手机执行 / 解析 / 统一返回）。

后端：
  - 业务主 API：https://i.waimai.meituan.com（微信小程序，appid wxde8ac0a21135c07d v1563）
  - 登录：https://passport.meituan.com（mobileloginapply / mobilelogin / refresh_token）
  - 风控：https://i.meituan.com（yoda 滑块/图形验证 captchaApi）

登录：手机号+验证码（operate_sms，真人配合收码）；token 存手机本地凭据库（target=meituan_waimai）。
风控：risk_app=216 / risk_platform=3 / fingerprint / uuid → ⚠️ 必须走手机通道（Device-as-Proxy），云端直连会被拦。

⚠️ 骨架说明（2026-08-11）：
  - 接口路径来自 wxapkg 解包（真实存在）；但**请求参数/请求头字段/签名待真机验证**。
  - 美团无 glyy 式 appKey 签名；token 与 deviceid 如何带（header/body、字段名）待真机抓包确认。
  - 方法先按「单请求 + **kwargs 透传」写，真机验证后再补全固定字段。

Device-as-Proxy：云端组装蓝图 → 手机直连 → 回传 skill_result → 云端解析。
⚠️ 未注入 executor 直接报错（禁云端直连，与 glyy/njpkzyy 同铁律）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse

logger = logging.getLogger("xiami.meituan_waimai")

BASE = "https://i.waimai.meituan.com"            # 业务主 API
LOGIN_BASE = "https://passport.meituan.com"      # 登录
APIMOBILE = "https://apimobile.meituan.com"      # 搜店/推荐（旧定位 group/v4/poi/search/miniprogram/{cityId}）
SHANGGOU = "https://wx-shangou.meituan.com"      # 搜店真实域名（quickbuy→/wxapp 前缀，2026-08-11 还原）
UA_WX = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger")

# ── 蓝图占位符（手机 SkillExecutor 本地替换）──
PH_TS = "{{timestamp}}"
PH_NONCE = "{{nonce}}"
PH_TOKEN = "{{token}}"
PH_DEVICEID = "{{deviceid}}"   # 设备指纹（待真机验证是否必填/字段名）


class MeituanWaimaiBase:
    """meituan_waimai 基础设施：蓝图生成 / 手机执行通道 / 响应解析 / 统一返回。"""

    def __init__(self, access_token: str | None = None, executor=None) -> None:
        # 手机通道执行函数（async (blueprint) -> {ok,status,headers,body,error}）
        # 由 registry.run 注入（绑定 bridge.send_skill_request）；必须注入，否则报错
        self.access_token = access_token or ""
        self.executor = executor

    def _blueprint(self, path: str, params: dict | None = None, body: dict | None = None,
                   bearer: bool = True, method: str = "GET", base: str | None = None,
                   extra_headers: dict | None = None) -> dict:
        """生成可在手机端执行的请求蓝图。

        ⚠️ 请求头字段（token 名/deviceid）待真机验证；先按占位符，手机端本地替换。
        extra_headers：额外请求头（如微信小程序 Referer 过风控）。
        """
        headers = {
            "User-Agent": UA_WX,
            "Content-Type": "application/json", "Accept": "*/*",
            # 风控/设备参数（待真机验证字段名与是否必填）
            "deviceid": PH_DEVICEID,
            "timestamp": PH_TS, "nonce": PH_NONCE,
        }
        if extra_headers:
            headers.update(extra_headers)
        if bearer:
            # ⚠️ 美团 token 字段名（token? Authorization?）待真机验证；先放 token
            headers["token"] = PH_TOKEN
        url = (base or BASE) + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        bp = {
            "skill": "meituan_waimai",
            "request": {
                "method": method, "url": url, "headers": headers,
                "body": body,
                # ⚠️ 美团无 glyy_sha1_md5 签名；sign_type 值待手机端真机验证（可能须手机端支持）
                "sign_type": "meituan",
            },
            "credential": {"kind": "bearer" if bearer else "none", "target": "meituan_waimai"},
        }
        return bp

    def describe_request(self, method: str, **params) -> dict | None:
        """返回方法对应的请求蓝图（供下发手机）。复合方法（login/submit_order…）→ None（云端编排）。"""
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
        """云端解析手机回传的原始响应为结构化数据。"""
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
                    logger.warning("[meituan_waimai] 手机执行失败 status=%s error=%s url=%s",
                                   res.get("status"), err[:200],
                                   str(bp.get("request", {}).get("url", ""))[:100])
                    need = ("登录" in err or "token" in err.lower() or "未登录" in err)
                    out = {"ok": False, "error": err, "status": res.get("status")}
                    if need:
                        out["need_login"] = True
                    return out
                body = str(res.get("body") or "")
                logger.info("[meituan_waimai] 手机执行成功 status=%s body前250=%s",
                            res.get("status"), body[:250])
                parsed = self._parse_text(body)
                if isinstance(parsed, dict):
                    msg = str(parsed.get("message") or parsed.get("msg") or "")
                    code = parsed.get("code")
                    if (("token" in msg.lower() or "login" in msg.lower()
                         or "未登录" in msg or code in (401, 403, 40003))):
                        return {"ok": False, "need_login": True,
                                "error": "登录态失效或未登录，请重新登录",
                                "status": res.get("status")}
                return parsed
            except Exception as e:
                last = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}", "attempt": i + 1}
                await asyncio.sleep(2 * (i + 1))
        return last

    async def _get(self, path: str, params: dict | None = None, bearer: bool = True,
                   base: str | None = None, timeout: int = 25, retries: int = 3,
                   extra_headers: dict | None = None) -> dict:
        """GET：仅走手机通道（禁云端直发）。"""
        if not self.executor:
            return {"ok": False, "error": "meituan_waimai 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, bearer=bearer, method="GET", base=base,
                             extra_headers=extra_headers)
        return await self._exec(bp, timeout, retries)

    async def _post(self, path: str, body: dict | None = None, params: dict | None = None,
                    bearer: bool = True, base: str | None = None,
                    timeout: int = 25, retries: int = 3,
                    extra_headers: dict | None = None) -> dict:
        """POST：仅走手机通道（禁云端直发）。"""
        if not self.executor:
            return {"ok": False, "error": "meituan_waimai 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, body=body, bearer=bearer,
                             method="POST", base=base, extra_headers=extra_headers)
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
