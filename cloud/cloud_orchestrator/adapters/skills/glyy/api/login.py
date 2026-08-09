"""glyy · 登录模块（验证码真人配合）。

步骤：get_graphical_captcha（图形验证码）→ send_sms（发短信）→ login（登录，token 存手机本地凭据库）。
铁律：glyy 一切请求走手机通道（云端组装蓝图 → 手机直连 → 回传 skill_result → 云端解析）。
"""
from __future__ import annotations

import json
import urllib.parse

from ._base import (APP_KEY, BASE, BASIC_HOSPITAL, BASIC_SMS, PH_NONCE, PH_SIGN,
                    PH_TS, REFERER, ROLE, TENANT, UA_WX)


class LoginMixin:
    """登录：图形验证码 + 短信验证码 → access_token（手机本地凭据库）。需 self.executor。"""

    def _sms_blueprint(self, path: str, params: dict | None = None) -> dict:
        """图形验证码/发短信共用蓝图（Basic sms，无需登录态）。"""
        headers = {
            "User-Agent": UA_WX, "Authorization": BASIC_SMS,
            "appKey": APP_KEY, "role": ROLE, "tenant": TENANT,
            "timestamp": PH_TS, "nonce": PH_NONCE, "sign": PH_SIGN,
            "Content-Type": "application/json", "Accept": "*/*",
            "Referer": REFERER,
        }
        url = BASE + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return {
            "skill": "glyy",
            "request": {"method": "POST", "url": url, "headers": headers,
                        "body": None, "sign_type": "glyy_sha1_md5"},
            "credential": {"kind": "none", "target": "glyy"},
        }

    async def get_graphical_captcha(self, phone: str) -> dict:
        """步骤1：POST /sms/captcha?phone= → 图形验证码 base64（手机通道回传 → App 显示）。"""
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        import base64
        res = await self.executor(self._sms_blueprint("/sms/captcha", {"phone": phone}))
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                    "status": res.get("status")}
        j = self._parse_text(str(res.get("body") or ""))
        data = (j.get("data") or "") if isinstance(j, dict) else ""
        if isinstance(data, str) and data.startswith("data:image"):
            try:
                with open("/tmp/glyy_captcha.png", "wb") as f:
                    f.write(base64.b64decode(data.split(",", 1)[1]))
            except Exception:
                pass
            return {"ok": True, "image_base64": data,
                    "captcha_file": "/tmp/glyy_captcha.png"}
        msg = (j.get("message") or j.get("dev_message") or "图形验证码获取失败") if isinstance(j, dict) else "响应解析失败"
        return {"ok": False, "error": msg}

    async def send_sms(self, phone: str, gcode: str) -> dict:
        """步骤2：POST /sms?phone=&type=1&code=<图形验证码> → 给手机发短信验证码（手机通道）。"""
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        res = await self.executor(
            self._sms_blueprint("/sms", {"phone": phone, "type": "1", "code": gcode}))
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                    "status": res.get("status")}
        j = self._parse_text(str(res.get("body") or ""))
        if isinstance(j, dict) and j.get("code") == 0:
            return {"ok": True, "msg": "短信已发送"}
        msg = (j.get("message") or j.get("dev_message") or "发送短信失败") if isinstance(j, dict) else "响应解析失败"
        return {"ok": False, "error": msg, "code": (j.get("code") if isinstance(j, dict) else None)}

    async def login(self, phone: str, code: str) -> dict:
        """步骤3：POST /v4/session/phone?phone=&code=<短信验证码> + JSON body（Basic hospital）。

        token 由手机回写本地凭据库（第 4 条：云端不持有登录态）。仅走手机通道。
        """
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        headers = {
            "User-Agent": UA_WX, "Authorization": BASIC_HOSPITAL,
            "appKey": APP_KEY, "role": ROLE, "tenant": TENANT,
            "timestamp": PH_TS, "nonce": PH_NONCE, "sign": PH_SIGN,
            "Content-Type": "application/json", "Accept": "*/*",
        }
        url = (BASE + "/v4/session/phone?phone=" + urllib.parse.quote(phone)
               + "&code=" + urllib.parse.quote(code))
        bp = {
            "skill": "glyy",
            "request": {"method": "POST", "url": url, "headers": headers,
                        "body": {"phone": phone, "code": code},
                        "sign_type": "glyy_sha1_md5"},
            "credential": {"kind": "none", "target": "glyy"},
            # 登录成功 → 手机把 access_token/refresh_token/expires_in 写入本地凭据库（第 4 条）
            "store": {"kind": "token", "field": "data.access_token", "target": "glyy",
                      "extra": [
                          {"kind": "refresh_token", "field": "data.refresh_token"},
                          {"kind": "expires_in", "field": "data.expires_in"},
                      ]},
        }
        res = await self.executor(bp)
        if not isinstance(res, dict):
            return {"ok": False, "error": "手机执行返回异常"}
        if not res.get("ok"):
            return {"ok": False, "error": str(res.get("error") or "手机执行失败"),
                    "status": res.get("status")}
        j = self._parse_text(str(res.get("body") or ""))
        if j.get("code") == 0 and j.get("data"):
            return {"ok": True, "msg": "登录成功，token 已保存到手机本地凭据库"}
        return {"ok": False, "error": j.get("message") or j.get("dev_message")}
