"""glyy 基础：常量 + 基础设施（蓝图生成 / 手机执行 / 解析 / 统一返回）。

后端：https://www.ih.njglyy.com:9532/caring/api
签名：sign = SHA1(MD5(appKey + timestamp + nonce))，appKey=1340patient
认证：公开接口 Basic；登录后带 Authorization: Bearer <access_token>
cUA  ：保留微信手机 UA（兼容老站风控；实测公开接口带/不带 UA 均正常返回，非硬性要求）

Device-as-Proxy：云端组装蓝图 → 手机直连 → 回传 skill_result → 云端解析。
⚠️ 2026-08-06 已删除「云端直发降级」：未注入 executor 直接报错（铁律：glyy 禁云端直连）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse

logger = logging.getLogger("xiami.glyy")

BASE = "https://www.ih.njglyy.com:9532/caring/api"
APP_KEY = "1340patient"
TENANT = "1340"
ROLE = "patient"
BASIC_SMS = "Basic c21zOnNtc3NlY3JldA=="          # sms:smssecret（发短信/验证码用）
BASIC_HOSPITAL = "Basic aG9zcGl0YWw6aG9zcGl0YWwtc2VjcmV0"  # hospital:hospital-secret（公开接口）
UA_WX = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38(0x18002623) "
         "NetType/WIFI Language/zh_CN")
REFERER = "https://servicewechat.com/wx74a991a2ae77468d/330/page-frame.html"

# ── 蓝图占位符（手机 SkillExecutor 本地替换）──
# 必须先于 REFRESH_CFG 定义（模块级求值顺序），否则加载报 NameError
PH_TS = "{{timestamp}}"
PH_NONCE = "{{nonce}}"
PH_SIGN = "{{sign}}"
PH_TOKEN = "{{token}}"

# 静默续期配置（随「需登录蓝图」下发手机，App 只按此执行，不内置平台细节）
REFRESH_CFG = {
    "method": "PUT",
    "url": BASE + "/v4/session?refresh_token={{refresh_token}}",
    "headers": {
        "User-Agent": UA_WX,
        "appKey": APP_KEY, "role": ROLE, "tenant": TENANT,
        "timestamp": PH_TS, "nonce": PH_NONCE, "sign": PH_SIGN,
        "Content-Type": "application/json", "Accept": "*/*",
        "Referer": REFERER,
    },
    "sign_type": "sha1_md5",
    "sign_content": "{{appKey}}{{timestamp}}{{nonce}}",
    "insecure_tls": True,
}

# 挂号固定参数（抓包实测）
RES_SRC = 801          # 来源
BUSINESS_TYPE_EXPERT = 2   # 专家号
BUSINESS_TYPE_NORMAL = 1   # 普通号
SOURCE = "wx_tinyapp"


class GlyyBase:
    """glyy 基础设施：蓝图生成 / 手机执行通道 / 响应解析 / 统一返回。"""

    # 单请求方法映射：method -> (path_template, http_method, 需要bearer)
    _REQUEST_MAP: dict[str, tuple] = {
        # B 查号源（公开）
        "list_depts": ("/public/dept", "GET", False),
        "list_doctors": ("/public/schedule/dept/doctor/{dept_code}", "GET", False),
        "get_available_dates": ("/public/v3/schedule/dept/{dept_code}/check", "GET", False),
        "get_schedule": ("/public/v3/schedule/dept/{dept_code}", "GET", False),
        "online_depts": ("/public/expert/dept", "GET", False),
        "expert_cloud_depts": ("/public/expert/cloud/dept", "GET", False),
        "online_search": ("/public/search/online", "GET", False),
        "judge_revisit": ("/public/online/judgeRevisit", "GET", False),
        "online_doctor_schedule": ("/public/schedule/doctor/online", "GET", False),
        "re_clinic_schedule": ("/public/re_clinic/getScheduleByDocId", "GET", False),
        # D 我的就诊（需登录）
        "list_orders": ("/public/orders", "GET", True),
        "cancel_reservation": ("/public/v3/reservation/cancel", "POST", True),
        "list_reports": ("/public/report/{kind}", "GET", True),
        "clinic_no_paid": ("/public/clinic/no_paid", "GET", True),
        "visit_records": ("/public/visit/record", "POST", True),
        # E 病历/处方/缴费（需登录）
        "get_recipe": ("/public/trans/visRecipe/findRecipeByVisitId", "GET", True),
        "get_recipe_detail": ("/public/trans/visRecipe/getRecipeDetail", "GET", True),
        "clinic_no_paid_detail": ("/public/clinic/no_paid_detail", "GET", True),
        "visit_patient_record": ("/public/trans/visPatientRecord/findByVisitId", "GET", True),
        "medical_pay": ("/public/order/medical_pay", "GET", True),
        # C 挂号（需登录，⚠️ 真挂号）
        "register": ("/public/v3/register", "POST", True),
    }

    def __init__(self, token: str | None = None, executor=None) -> None:
        # 手机通道执行函数（async (blueprint) -> {ok,status,headers,body,error}）
        # 由 registry.run 注入（绑定 bridge.send_skill_request）；必须注入，否则报错
        self.token = token or ""
        self.executor = executor

    def _blueprint(self, path: str, params: dict | None = None, body: dict | None = None,
                   bearer: bool = True, method: str = "GET") -> dict:
        """生成可在手机端执行的请求蓝图（sign 等由手机本地按 sign_type 计算）。"""
        headers = {
            "User-Agent": UA_WX, "appKey": APP_KEY, "role": ROLE, "tenant": TENANT,
            "timestamp": PH_TS, "nonce": PH_NONCE, "sign": PH_SIGN,
            "Content-Type": "application/json", "Accept": "*/*", "Referer": REFERER,
        }
        if bearer:
            headers["Authorization"] = "Bearer " + PH_TOKEN
        url = BASE + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        bp = {
            "skill": "glyy",
            "request": {
                "method": method, "url": url, "headers": headers,
                "body": body, "sign_type": "sha1_md5",
                "sign_content": "{{appKey}}{{timestamp}}{{nonce}}",
                "insecure_tls": True,
            },
            "credential": {"kind": "bearer" if bearer else "none", "target": "glyy"},
        }
        # 需要登录的请求：手机端发现 token 快过期时自动用 refresh_token 静默续期。
        # 续期接口配置随蓝图下发（REFRESH_CFG），App 只执行，不内置平台细节
        if bearer:
            bp["auto_refresh"] = True
            bp["refresh"] = REFRESH_CFG
        return bp

    def describe_request(self, method: str, **params) -> dict | None:
        """第 3 条：返回方法对应的请求蓝图（供第 2 条下发手机）。

        单请求方法 → 完整蓝图；复合方法（login/get_patient…）→ None（云端编排）。
        """
        m = self._REQUEST_MAP.get(method)
        if not m:
            return None
        path_t, http, bearer = m
        p = dict(params or {})
        try:
            path = path_t.format(**p)
        except KeyError:
            return None
        # 已用于路径的参数从 query 中剔除
        q = {k: v for k, v in p.items() if ("{" + k + "}") not in path_t}
        if http == "POST":
            return self._blueprint(path, body=q or None, bearer=bearer, method="POST")
        return self._blueprint(path, params=q or None, bearer=bearer, method="GET")

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
                    logger.warning("[glyy] 手机执行失败 status=%s error=%s url=%s",
                                   res.get("status"), err[:200], str(bp.get("request", {}).get("url", ""))[:100])
                    # 登录相关错误（缺 token / 登录态失效）→ 标记 need_login 供主代理自动登录
                    need = ("登录" in err or "token" in err.lower())
                    out = {"ok": False, "error": err, "status": res.get("status")}
                    if need:
                        out["need_login"] = True
                    return out
                body = str(res.get("body") or "")
                logger.info("[glyy] 手机执行成功 status=%s body前250=%s",
                            res.get("status"), body[:250])
                parsed = self._parse_text(body)
                # 登录态失效/未登录 → 标记 need_login（供主代理自动触发登录）
                if isinstance(parsed, dict):
                    msg = str(parsed.get("message") or parsed.get("dev_message") or "")
                    code = parsed.get("code")
                    if (not parsed.get("code") == 0 and
                            ("token" in msg.lower() or "login" in msg.lower()
                             or "未登录" in msg or code in (30007, 401, 403))):
                        return {"ok": False, "need_login": True,
                                "error": "登录态失效或未登录，请重新登录",
                                "status": res.get("status")}
                return parsed
            except Exception as e:
                last = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}", "attempt": i + 1}
                await asyncio.sleep(2 * (i + 1))
        return last

    async def _get(self, path: str, params: dict | None = None, bearer: bool = True,
                   timeout: int = 25, retries: int = 3) -> dict:
        """GET：仅走手机通道（禁云端直发）。未注入 executor 直接报错。"""
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, bearer=bearer, method="GET")
        return await self._exec(bp, timeout, retries)

    async def _post(self, path: str, body: dict | None = None, params: dict | None = None,
                    bearer: bool = True, timeout: int = 25, retries: int = 3) -> dict:
        """POST：仅走手机通道（禁云端直发）。未注入 executor 直接报错。"""
        if not self.executor:
            return {"ok": False, "error": "glyy 未注入手机通道 executor，已停止执行（禁云端直连）"}
        bp = self._blueprint(path, params=params, body=body, bearer=bearer, method="POST")
        return await self._exec(bp, timeout, retries)

    def ok(self, j: dict) -> bool:
        return isinstance(j, dict) and j.get("code") == 0

    def _out(self, j: dict, default=None):
        """统一方法返回：ok 时返回 data；失败(need_login/error) 透传错误 dict；
        业务失败(code!=0) 也透传 {ok:false, code, message}，不吞成 default（让 AI 能读到失败原因）。"""
        if isinstance(j, dict) and (j.get("error") or j.get("need_login")):
            return j
        if self.ok(j):
            d = j.get("data")
            return d if d is not None else default
        if isinstance(j, dict):
            # 业务失败：把服务器原因透传，供 AI 诊断（原来 return default 把原因吞掉）
            msg = str(j.get("message") or j.get("dev_message") or "业务处理失败")
            return {"ok": False, "code": j.get("code"), "message": msg}
        return default
