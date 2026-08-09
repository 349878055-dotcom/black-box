"""njpkzyy_new · 登录模块（微信授权真人配合）。

登录 = 微信小程序授权：用户在小程序「南京市浦口区中医院」内授权产生
code/encrypted_data/iv（一次性、会过期），传入 → POST /api/session/wechat/ma
换 access_token（JWT）→ 手机端本地凭据库持久化（target=njpkzyy_new）。

⚠️ 需要真人配合：App 不能代做微信授权（operate_wechat 边界）。
铁律：一切请求走手机通道（云端组装蓝图 → 手机直连 → 回传 skill_result → 云端解析）。
"""
from __future__ import annotations

from ._base import HOSPITAL, ROLE


class LoginMixin:
    """登录：微信授权 → access_token（手机本地凭据库）。需 self.executor。"""

    async def wechat_login(self, code: str, encrypted_data: str = "", iv: str = "") -> dict:
        """微信小程序授权登录 → data.access_token（JWT）存手机本地凭据库。

        code/encrypted_data/iv 由用户在小程序授权产生（真人配合，一次性、会过期）。
        """
        if not self.executor:
            return {"ok": False, "error": "njpkzyy_new 未注入手机通道 executor，已停止执行（禁云端直连）"}
        body = {
            "app_id": "wxca05bc9d9f69226c",
            "code": code,
            "encrypted_data": encrypted_data,
            "grant_type": "wechat_ma",
            "hospital": HOSPITAL,
            "iv": iv,
            "role": ROLE,
        }
        bp = self._blueprint("/api/session/wechat/ma", body=body, bearer=False, method="POST")
        # 登录成功 → 手机把 access_token/refresh_token/expires_in 写入本地凭据库
        bp["store"] = {"kind": "token", "field": "data.access_token", "target": "njpkzyy_new",
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
        if j.get("code") == 0 and j.get("data"):
            return {"ok": True, "msg": "微信授权登录成功，token 已保存到手机本地凭据库"}
        return {"ok": False, "error": j.get("message") or j.get("dev_message")}
