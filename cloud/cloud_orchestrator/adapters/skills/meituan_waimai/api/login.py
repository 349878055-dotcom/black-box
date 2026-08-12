"""meituan_waimai · 登录模块（手机号+验证码，真人配合收码）。

步骤：login_apply（POST /api/v3/account/mobileloginapply 发短信验证码，可能先过 yoda 滑块/图形验证）
     → login（POST /api/v3/account/mobilelogin 手机号+验证码登录）→ token 存手机本地凭据库。
备选：refresh_token（POST /refresh_token 续期，⚠️ 探测 404 待真机确认路径）。

实测（2026-08-11 云端直连探测）：
  - passport.meituan.com 登录接口**云端可直连**（HTTP 200，非 403）——登录可能不用走手机通道
  - 返回结构 = **{"error": {"code", "message", "type"}}**（失败），如 mobileloginapply 空号 →
    {"error":{"code":101012,"message":"请输入正确的手机号","type":"user_err_mobile_inval"}}
  - 登录参数方向：mobile + 验证码 + 可能 ticket（票据）；验证码前可能过滑块/图形
  - ⚠️ 请求体字段（verifyCode/ticket/风控）待真机验证；先透传 **kwargs

铁律：默认走手机通道（云端组装蓝图 → 手机直连 → 回传 skill_result → 云端解析）；解析兼容 error 结构。
"""
from __future__ import annotations

from ._base import LOGIN_BASE


class LoginMixin:
    """登录：手机号+验证码 → token（手机本地凭据库）。需 self.executor / self._blueprint / self._parse_text。"""

    async def login_apply(self, mobile: str, **kwargs) -> dict:
        """步骤1：POST passport.meituan.com/api/v3/account/mobileloginapply 发短信验证码。

        ⚠️ 可能需先过 yoda 滑块/图形验证（captcha 参数待真机验证）；返回可能含验证码票据（ticket）。
        """
        if not self.executor:
            return {"ok": False, "error": "meituan_waimai 未注入手机通道 executor，已停止执行（禁云端直连）"}
        body = {"mobile": mobile, **kwargs}
        bp = self._blueprint("/api/v3/account/mobileloginapply", body=body, bearer=False,
                             method="POST", base=LOGIN_BASE)
        res = await self.executor(bp)
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                    "status": res.get("status")}
        j = self._parse_text(str(res.get("body") or ""))
        # passport 失败结构：{"error": {code, message, type}}
        if isinstance(j, dict) and isinstance(j.get("error"), dict):
            e = j["error"]
            return {"ok": False, "error": e.get("message") or str(e), "code": e.get("code")}
        # 成功/其它结构待真机验证（可能含验证码票据 ticket / 是否需滑块）
        return {"ok": True, "msg": "验证码请求已处理（可能需滑块/图形验证）", "data": j}

    async def login(self, mobile: str, verify_code: str = "", **kwargs) -> dict:
        """步骤2：POST passport.meituan.com/api/v3/account/mobilelogin 手机号+验证码登录。

        登录成功 → 手机把 access_token/refresh_token/expires_in 写入本地凭据库（target=meituan_waimai）。
        """
        if not self.executor:
            return {"ok": False, "error": "meituan_waimai 未注入手机通道 executor，已停止执行（禁云端直连）"}
        body = {"mobile": mobile, "verifyCode": verify_code, **kwargs}
        bp = self._blueprint("/api/v3/account/mobilelogin", body=body, bearer=False,
                             method="POST", base=LOGIN_BASE)
        bp["store"] = {"kind": "token", "field": "data.access_token", "target": "meituan_waimai",
                       "extra": [
                           {"kind": "refresh_token", "field": "data.refresh_token"},
                           {"kind": "expires_in", "field": "data.expires_in"},
                       ]}
        res = await self.executor(bp)
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                    "status": res.get("status")}
        j = self._parse_text(str(res.get("body") or ""))
        # passport 失败结构：{"error": {code, message, type}}
        if isinstance(j, dict) and isinstance(j.get("error"), dict):
            e = j["error"]
            return {"ok": False, "error": e.get("message") or str(e), "code": e.get("code")}
        # 成功结构待真机验证（可能 data.access_token 或 success 字段）；token 由手机凭据库 store 保存
        return {"ok": True, "msg": "登录成功（待真机确认 token 字段）", "data": j}

    async def refresh_token(self, **kwargs) -> dict:
        """续期：POST passport.meituan.com/refresh_token（body 含 refresh_token，待真机验证字段名）。"""
        if not self.executor:
            return {"ok": False, "error": "meituan_waimai 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint("/refresh_token", body=dict(kwargs), bearer=False,
                             method="POST", base=LOGIN_BASE)
        res = await self.executor(bp)
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        return {"ok": bool(res.get("ok")), "data": res.get("body") or res.get("error")}
