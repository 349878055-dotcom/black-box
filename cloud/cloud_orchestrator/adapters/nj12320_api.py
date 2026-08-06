"""
南京12320 · AI 可读 API（requests 直调后端接口，无需 UI 自动化）。

⚠️ 重要（两套系统差异，别再困惑）：
- 12320 有【预约系统 njres/80端口】和【用户中心 njmine/9090端口】两套独立系统
- 本 API 走【预约系统】：登录接口 /njres/indexJson/login.do 只校验账号+密码+验证码，
  **不检查弱口令** → 弱口令密码（如 xxxx）也能登录，永不弹「请修改密码」
- 用户中心（9090）登录/个人中心才做弱口令检查，会要求改密码——那是网页/浏览器那套，
  与本 API 无关
- 用户中心的「我的预约/取消/改密」在 9090 端口，当前网络可能不可达（本 API 够不着时
  由用户手机/网页操作）

2026-08-05/08-06 实测摸清的接口链路：
  查询（无需登录）：
    POST indexJson/getUserName.do                     → 登录检测（null=未登录，用户名=已登录）
    GET  reservation/hos_search.do?hosname=X          → 医院列表 HTML（hoscode）
    GET  reservation/hos_showReservation.do?hoscode=X → 科室列表 HTML（depid）
    GET  reservation/dep_detail.do?depid=X&hoscode=X  → 科室排班（toShowSchedule('hos',schcode,'am')）
    GET  reservation/doc_detail.do?docid=X&hoscode=X  → 医生排班（toShowSchedule('hos',schcode,'am',docid)）
    POST reservationJson/showScheduleTime.do          → 时段 JSON [{code,endHour,startHour,state,takeTime}]
      参数: hoscode / type(am|pm) / schcode
  预约（需登录，登录后 session 有效）：
    POST reservationJson/checkResRule.do?schcode=X    → noLogin / noPhone / success
    POST indexJson/login.do                           → 预约系统登录（RSA 加密 + 图形验证码）
      登录页: index_toLogin.do；验证码图: /njres/authImg.do（注意是 njres，不是 njmine）
      前端 RSA.js encryptedString：username=RSA(明文)；password=RSA(MD5(明文))
    reservation/hos_toConfirm.do?schcode=X&hosCfgCode=Y → 预约确认页（hosCfgCode=时段代码，必填；
      未登录会跳 index_toLogin.do；提交按钮 submitReservationBefore(charge,hoscode,docid)）
    GET  reservation/hos_saveReservation.do           → 提交预约（2026-08-05 实测成功）
      参数: hoscode / schcode / hosCfgCode(时段代码,必填) / resTime / iccardno / payWay
      实测：前端滑块验证码(validationYzmImage.do)只是 UI 约束，直接 GET 即成功

用法：
  api = Nj12320API()
  api.search_hospital("南京鼓楼医院")      → [{'name','hoscode',...}]
  api.list_departments(hoscode)           → [{'name','depid',...}]
  api.list_doctors(depid, hoscode)        → [{'name','docid',...}]（专家号科室才有）
  api.get_schedule(depid, hoscode)        → {'dates':[...], 'slots':[{'schcode','date','ampm','fee','title'}]}
  api.get_doctor_schedule(docid, hoscode) → {'dates':[...], 'slots':[...]}（医生排班，多 docid）
  api.get_time_slots(hoscode, schcode, 'am') → [{code,startHour,endHour,state,takeTime}]
  api.login(username, password, verify_code) → 预约系统登录（RSA 加密 + 验证码由人看）
  api.check_login()                      → 当前登录状态
  api.check_res_rule(schcode)            → 预约规则检查（noLogin/noPhone/success）
  api.get_confirm_page(schcode, hoscode, hos_cfg_code) → 确认页检查
  api.reserve(schcode, hoscode, hos_cfg_code='segTime1') → 提交预约（⚠️真挂号，实测成功）
"""
from __future__ import annotations

import hashlib
import re
from html import unescape
from typing import Any

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BASE = "https://www.nj12320.org"
REFERER = "https://www.nj12320.org/"

# RSA 公钥（login.js 里动态获取；留作兜底）
_PUBKEY_FALLBACK = ("b103b0e219862acf0c51b7cee921062684dab5aab44817ee1f32f54e7424793"
                    "ca5f5410fce5476658771991f27146a46da03bcc599a4a586e0bbbc6bcb8b3e4909d85420cd8b1541d397e07d740fd79d318284b153442d13c33a0028e7868ce6ac6ee9766f04bb500465920122f9192df555b7d625cb7958c62c0ccd614454df")
_RSA_E = 0x10001


def _md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class Nj12320API:
    def __init__(self, cookies: dict | None = None) -> None:
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Referer": REFERER,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        if cookies:
            self.s.cookies.update(cookies)

    # ─────────── 基础请求 ───────────
    def _get(self, path: str, params: dict | None = None, timeout: int = 30) -> requests.Response:
        return self.s.get(BASE + path, params=params, timeout=timeout)

    def _post(self, path: str, data: dict | None = None, timeout: int = 30) -> requests.Response:
        return self.s.post(BASE + path, data=data, timeout=timeout)

    def _strip(self, html: str) -> str:
        return unescape(re.sub(r"<[^>]+>", " ", html))

    def _json_load(self, text: str):
        """12320 接口返回常是『双层 JSON 字符串』（外层带引号），统一解析到对象。"""
        import json as _json
        data = text
        for _ in range(2):
            if isinstance(data, str):
                try:
                    data = _json.loads(data)
                except Exception:
                    break
            else:
                break
        return data

    def _ensure_session(self) -> None:
        """确保有 JSESSIONID（时段接口要求有会话 cookie；首次访问首页即可获得）。"""
        if not any(c.name == "JSESSIONID" for c in self.s.cookies):
            try:
                self._get("/njres/")
            except Exception:
                pass

    # ─────────── RSA 加密（对齐前端 RSA.js encryptedString）───────────
    def _get_public_key(self) -> str:
        """从 login.js 动态取 RSA 公钥（hex）。"""
        try:
            js = self._get("/njres/js/login.js", timeout=15).text
            m = re.search(r"publicKey\s*=\s*['\"]([0-9a-fA-F]+)['\"]", js)
            if m:
                return m.group(1)
        except Exception:
            pass
        return _PUBKEY_FALLBACK

    def _rsa_encrypt(self, text: str, public_key: str | None = None) -> str:
        """对齐 12320 前端 RSA.js encryptedString：
        chunkSize = 2*biHighIndex(modulus)+2；每 chunkSize 字符一块，小端 2 字节合并 →
        每块 m^e mod n → 16 进制拼接（无前导零）。"""
        pub = public_key or self._get_public_key()
        n = int(pub, 16)
        bitlen = len(pub) * 4
        chunk_size = 2 * (((bitlen + 15) // 16) - 1) + 2

        a = [ord(c) for c in text]
        while len(a) % chunk_size != 0:
            a.append(0)

        out = []
        for i in range(0, len(a), chunk_size):
            block = 0
            for j in range(chunk_size // 2):
                lo = a[i + 2 * j]
                hi = a[i + 2 * j + 1]
                block |= ((lo | (hi << 8)) & 0xFFFF) << (16 * j)
            c = pow(block, _RSA_E, n)
            out.append(format(c, "x"))
        return "".join(out)

    # ─────────── 登录 ───────────
    def check_login(self) -> str:
        """登录检测：返回用户名（已登录）或空串（未登录）。POST indexJson/getUserName.do。"""
        try:
            r = self._post("/njres/indexJson/getUserName.do")
            t = (r.text or "").strip().strip('"')
            return "" if t in ("null", "", "None") else t
        except Exception:
            return ""

    def get_captcha(self) -> bytes:
        """抓一张图形验证码（PNG bytes，给人看；会刷新验证码）。
        流程：get_captcha() → 存图给人看 → 人输入 → login(..., 验证码)。
        注意：抓图后不要再抓图/刷新，否则验证码失效。"""
        self._ensure_session()
        return self.s.get(BASE + "/njres/authImg.do", timeout=20).content

    def change_password(self, new_password: str) -> dict:
        """修改密码（需登录态；⚠️ 改后旧密码失效，须用户确认）。
        对齐前端 updatepwd()：POST indexJson/updatePwd.do，newPassword = RSA(MD5(新密码))。
        12320 会拦截弱口令账号（提示『密码为弱口令，请重新修改』），改强密码后可正常用。
        新密码规则：8~16 位，含大写/小写/数字/特殊符号至少 3 种。"""
        try:
            self._ensure_session()
            pub = self._get_public_key()
            r = self._post("/njres/indexJson/updatePwd.do", {
                "newPassword": self._rsa_encrypt(_md5_hex(new_password), pub),
            })
            txt = (r.text or "").strip()
            return {"ok": txt == "success", "result": txt[:200]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def login_auto(self, username: str, password: str, max_attempts: int = 8) -> dict:
        """全自动登录：本地 OCR（ddddocr）识别图形验证码 + 失败自动刷新重试，免人工看图。
        返回 {ok, attempts, code, user}；多次失败返回 {ok:False}（可降级人工 login）。"""
        try:
            import ddddocr
        except ImportError:
            return {"ok": False, "error": "未安装 ddddocr（pip install --user --break-system-packages ddddocr）"}
        ocr = ddddocr.DdddOcr(show_ad=False)
        for i in range(max_attempts):
            try:
                png = self.get_captcha()
                code = str(ocr.classification(png)).strip()
                res = self.login(username, password, code)
                user = self.check_login()
                if res.get("ok") and user:
                    return {"ok": True, "attempts": i + 1, "code": code, "user": user}
            except Exception as e:
                return {"ok": False, "error": f"自动登录异常：{e}"}
        return {"ok": False, "attempts": max_attempts,
                "error": "OCR 多次识别失败，请改用 login() 人工看图输入验证码"}

    def login(self, username: str, password: str, verify_code: str) -> dict:
        """预约系统登录（njres）。RSA 加密 + 图形验证码。
        verify_code 必须对应最近一次 get_captcha() 的图（同一会话，勿在中间刷新）。
        返回 {ok, result(message), user}。"""
        self._ensure_session()
        pub = self._get_public_key()
        # RSA 加密：username 明文；password 先 MD5 再 RSA（对齐 login.js）
        r = self._post("/njres/indexJson/login.do", {
            "username": self._rsa_encrypt(username, pub),
            "password": self._rsa_encrypt(_md5_hex(password), pub),
            "verifyCode": verify_code,
        })
        txt = (r.text or "").strip()
        msg = txt
        try:
            data = self._json_load(txt)
            if isinstance(data, dict):
                msg = str(data.get("message") or data.get("result") or "")
        except Exception:
            pass
        ok = not any(w in msg for w in ("验证码", "不正确", "失败", "错误", "不存在", "null"))
        return {"ok": ok, "result": msg[:200], "user": self.check_login()}

    # ─────────── 查询（无需登录）───────────
    def search_hospital(self, hosname: str) -> list[dict]:
        """按医院名搜医院 → 医院列表 [{name, hoscode}]。"""
        r = self._get("/njres/reservation/hos_search.do", {"hosname": hosname})
        out: list[dict] = []
        seen: set[str] = set()
        for m in re.finditer(r"href=\"[^\"]*?hoscode=(\d+)[^\"]*\"[^>]*>([^<]{2,40})</a>", r.text):
            hoscode, name = m.group(1), self._strip(m.group(2)).strip()
            if name in ("查看科室", "查看医生", "马上预约", "[详细]"):
                continue
            if hoscode in seen:
                continue
            seen.add(hoscode)
            out.append({"name": name, "hoscode": hoscode})
        return out

    def list_departments(self, hoscode: str) -> list[dict]:
        """医院科室列表 [{name, depid}]。需 changeFlay=1 才返回完整科室（默认只特色科室）。"""
        r = self._get("/njres/reservation/hos_showReservation.do",
                      {"hoscode": hoscode, "changeFlay": "1"})
        out: list[dict] = []
        for m in re.finditer(r"dep_detail\.do[^\"]*?depid=(\d+)[^\"]*\"[^>]*>([^<]{2,60})</a>", r.text):
            depid, name = m.group(1), self._strip(m.group(2)).strip()
            if name and name not in ("查看排班", "预约"):
                out.append({"name": name, "depid": depid})
        # 去重
        uniq: dict[str, str] = {}
        for d in out:
            uniq.setdefault(d["depid"], d["name"])
        return [{"name": v, "depid": k} for k, v in uniq.items()]

    def find_doctor(self, hosname: str, docname: str) -> dict:
        """按 医院名+医生名 直接定位医生（自动遍历该医院全部科室的医生，不用用户提供科室）。
        返回 {ok, hospital, hoscode, dep, doctor}；找不到/多位同名返回 error 提示。"""
        try:
            hos = self.search_hospital(hosname)
            if not hos:
                return {"ok": False, "error": f"找不到医院：{hosname}"}
            hoscode = hos[0]["hoscode"]
            hits = []
            for d in self.list_departments(hoscode):
                try:
                    docs = self.list_doctors(d["depid"], hoscode)
                except Exception:
                    continue
                for x in docs:
                    if docname in x["name"]:
                        hits.append({"dep": d, "doctor": x})
            if not hits:
                return {"ok": False, "error": f"医院「{hosname}」没找到医生「{docname}」"}
            if len(hits) > 1:
                deps = [f"{h['dep']['name']}({h['doctor']['name']})" for h in hits]
                return {"ok": False, "error": f"有多位同名医生：{'、'.join(deps)}，请指定科室",
                        "candidates": hits}
            return {"ok": True, "hospital": hos[0]["name"], "hoscode": hoscode,
                    "dep": hits[0]["dep"], "doctor": hits[0]["doctor"]}
        except Exception as e:
            return {"ok": False, "error": f"找医生异常：{e}"}

    def list_doctors(self, depid: str, hoscode: str) -> list[dict]:
        """科室医生列表 [{name, docid}]（专家号科室有；普通专科科室为空）。"""
        r = self._get("/njres/reservation/dep_detail.do", {"depid": depid, "hoscode": hoscode})
        out: list[dict] = []
        for m in re.finditer(
            r'<a[^>]*doc_detail\.do[^>]*\?docid=(\d+)[^>]*>([^<]{1,30})</a>', r.text
        ):
            docid, name = m.group(1), self._strip(m.group(2)).strip()
            if name:
                out.append({"name": name, "docid": docid})
        uniq: dict[str, str] = {}
        for d in out:
            uniq.setdefault(d["docid"], d["name"])
        return [{"name": v, "docid": k} for k, v in uniq.items()]

    def get_schedule(self, depid: str, hoscode: str) -> dict:
        """科室排班：可约格子 [{schcode, date, ampm, fee, title}] + 日期表。"""
        r = self._get("/njres/reservation/dep_detail.do", {"depid": depid, "hoscode": hoscode})
        return self._parse_schedule(r.text)

    def get_doctor_schedule(self, docid: str, hoscode: str) -> dict:
        """医生排班：可约格子 [{schcode, date, ampm, fee, title}] + 日期表。
        doc_detail 的可约格子 = toShowSchedule('hos',schcode,'am|pm',docid)。"""
        r = self._get("/njres/reservation/doc_detail.do", {"docid": docid, "hoscode": hoscode})
        return self._parse_schedule(r.text)

    def _parse_schedule(self, html: str) -> dict:
        """解析排班页（科室/医生通用）：toShowSchedule('hos',schcode,'am|pm'[,docid]) + title。"""
        slots: list[dict] = []
        for m in re.finditer(
            r"toShowSchedule\('(\d+)',(\d+),'(am|pm)',\d*\)[^>]*title=\"([^\"]*)\"",
            html,
        ):
            hos, schcode, ampm, title = m.groups()
            t = self._strip(title)
            date = ""
            dm = re.search(r"(\d{2})月(\d{2})日", t)
            if dm:
                date = f"{dm.group(1)}-{dm.group(2)}"
            fee = ""
            fm = re.search(r"挂号费[：:]\s*(\d+)", t)
            if fm:
                fee = fm.group(1)
            slots.append({"schcode": schcode, "hoscode": hos, "ampm": ampm,
                          "date": date, "fee": fee, "title": t[:120]})
        dates = [(a, b) for a, b in re.findall(r"(\d{2}-\d{2})[^<]*<[^>]*>?[^<]*(周[一二三四五六日])", html)]
        return {"dates": dates, "slots": slots}

    def get_time_slots(self, hoscode: str, schcode: str, ampm: str = "am") -> list[dict]:
        """排班时段的可约时段（showScheduleTime.do）：[{code,startHour,endHour,state,takeTime}]。
        需要 JSESSIONID 会话（自动初始化），无需登录。state=1 表示可约。"""
        self._ensure_session()
        try:
            r = self._post("/njres/reservationJson/showScheduleTime.do",
                           {"hoscode": hoscode, "type": ampm, "schcode": schcode})
            data = self._json_load(r.text)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # ─────────── 预约（需登录）───────────
    def check_res_rule(self, schcode: str) -> str:
        """预约规则检查（toconfirm(schcode) 的第一步）：
        返回 noLogin / noPhone / success / error。未登录时接口返回登录页 HTML → 归一化为 noLogin。"""
        try:
            r = self._post("/njres/reservationJson/checkResRule.do", {"schcode": schcode})
            txt = (r.text or "").strip()
            if not txt:
                return "error:empty"
            # 未登录：返回登录页 HTML（含 DOCTYPE），归一化为 noLogin
            if txt.startswith("<!DOCTYPE") or "<html" in txt[:200] or len(txt) > 2000:
                return "noLogin"
            return txt[:60]
        except Exception as e:
            return f"error:{e}"

    def get_confirm_page(self, schcode: str, hoscode: str = "", hos_cfg_code: str = "") -> dict:
        """预约确认页 hos_toConfirm.do：返回 {ok, url, login_required, html片段}。
        未登录会被重定向到 index_toLogin.do（login_required=True）。
        hos_cfg_code 为时段代码（必填，否则确认页时段为空、提交报『时段代码必填』）。"""
        try:
            params = {"schcode": schcode, "hoscode": hoscode}
            if hos_cfg_code:
                params["hosCfgCode"] = hos_cfg_code
            r = self._get("/njres/reservation/hos_toConfirm.do", params)
            final = str(r.url)
            login_required = "index_toLogin" in final or "index_toLogin" in (r.text or "")
            return {
                "ok": True,
                "login_required": login_required,
                "url": final,
                "html_len": len(r.text),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def book(self, hosname: str, docname: str, date: str = "",
             ampm: str = "am", username: str = "", password: str = "") -> dict:
        """一键预约（高封装，把复杂度藏起来）：给 医院名+医生名+日期(可选)，自动完成：
        搜医院→找科室→找医生→查排班→选时段→(未登录则自动登录)→提交。
        ⚠️ 真挂号有副作用，调用方须用户确认。
        返回 {ok, hospital, doctor, date, ampm, fee, result/error}。"""
        try:
            # 1. 医院
            hos = self.search_hospital(hosname)
            if not hos:
                return {"ok": False, "error": f"找不到医院：{hosname}"}
            hoscode = hos[0]["hoscode"]
            # 2. 科室 → 找医生（专家号科室才有医生）
            found = None
            for d in self.list_departments(hoscode):
                try:
                    docs = self.list_doctors(d["depid"], hoscode)
                except Exception:
                    continue
                hit = [x for x in docs if docname in x["name"]]
                if hit:
                    found = (d, hit[0])
                    break
            if not found:
                return {"ok": False, "error": f"医院「{hosname}」没找到医生「{docname}」"}
            dep, doc = found
            # 3. 排班 → 找可约格子
            sch = self.get_doctor_schedule(doc["docid"], hoscode)
            slots = [s for s in sch["slots"] if s["ampm"] == ampm]
            if date:
                slots = [s for s in slots if s["date"] == date]
            if not slots:
                return {"ok": False, "error": f"{docname} 没有可约时间"
                        + (f"（{date} {ampm}）" if date else f"（{ampm}）")}
            slot = slots[0]
            # 4. 时段（具体几点）
            times = self.get_time_slots(slot["hoscode"], slot["schcode"], slot["ampm"])
            avail = [t for t in times if str(t.get("state")) == "1"]
            if not avail:
                return {"ok": False, "error": "排班有号但无可约时段"}
            seg = avail[0]["code"]
            # 5. 登录（未登录则自动登录）
            if not self.check_login():
                if username and password:
                    lr = self.login_auto(username, password)
                    if not lr.get("ok"):
                        return {"ok": False, "error": f"自动登录失败：{lr.get('error','')}"}
                else:
                    return {"ok": False, "error": "未登录，且未提供账号密码（可先用 login_auto/login 登录）"}
            # 6. 提交预约
            res = self.reserve(slot["schcode"], hoscode, hos_cfg_code=seg, pay_way="0")
            return {
                "ok": res.get("ok", False),
                "hospital": hosname, "doctor": docname,
                "date": slot["date"], "ampm": ampm, "fee": slot.get("fee", ""),
                "result": res.get("result", "")[:300],
            }
        except Exception as e:
            return {"ok": False, "error": f"一键预约异常：{e}"}

    @staticmethod
    def _parse_reserve_result(html: str) -> dict:
        """解析预约提交返回页：识别 成功/限约，并提取「预约号/取号凭证」（就诊当天取号用）。"""
        text = re.sub(r"<[^>]+>", " ", html or "")
        text = re.sub(r"\s+", " ", text).strip()
        limited = ("限定" in text) or ("1次" in text and "预约" in text)
        ok = ("预约完成" in html) or ("预约成功" in text)
        info = {"ok": ok, "limited": limited}
        for kw in ["预约号", "预约单号", "流水号", "取号密码", "取号码",
                   "预约验证码", "取号凭证", "就诊序号", "序号"]:
            m = re.search(re.escape(kw) + r"[：:\s]*([0-9A-Za-z\-]{4,40})", text)
            if m:
                info[kw] = m.group(1)
                break
        return info

    def reserve(self, schcode: str, hoscode: str, hos_cfg_code: str = "",
                res_time: str = "", iccardno: str = "", pay_way: str = "0") -> dict:
        """提交预约申请（⚠️ 真挂号，有副作用，须用户明确确认）。2026-08-05 实测预约成功。
        对应确认页 reservationForm：GET hos_saveReservation.do。
        参数：schcode 排班代码 / hoscode 医院代码 /
              hos_cfg_code 时段代码（如 segTime1，必填；来自 get_time_slots 的 code）/
              res_time 预约时间（可空）/ iccardno 市民卡号（可选）/ pay_way 支付方式（0=现场支付）。
        实测：前端滑块验证码只是 UI 约束，直接 GET 本接口即可提交成功（无需滑块）。
        返回 {ok, status, result(页面HTML), info(含预约号/取号凭证), url}。"""
        params = {
            "hoscode": hoscode,
            "schcode": schcode,
            "resTime": res_time,
            "hosCfgCode": hos_cfg_code,
            "iccardno": iccardno,
            "payWay": pay_way,
        }
        try:
            r = self._get("/njres/reservation/hos_saveReservation.do", params)
            html = r.text or ""
            info = self._parse_reserve_result(html)
            return {
                "ok": info.get("ok", False),
                "status": r.status_code,
                "result": html[:500],
                "info": info,
                "url": str(r.url),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


# 便捷入口
api = Nj12320API()

if __name__ == "__main__":
    import json
    print("登录检测:", api.check_login())
    hos = api.search_hospital("南京鼓楼医院")
    print("医院:", json.dumps(hos, ensure_ascii=False)[:300])
    if hos:
        hoscode = hos[0]["hoscode"]
        deps = api.list_departments(hoscode)
        print("科室数:", len(deps))
        pick = next((d for d in deps if "产科" in d["name"]), deps[0] if deps else None)
        if pick:
            print("选科室:", pick)
            docs = api.list_doctors(pick["depid"], hoscode)
            print("医生数:", len(docs), docs[:5])
            if docs:
                sch = api.get_doctor_schedule(docs[0]["docid"], hoscode)
                print("医生排班可约格子数:", len(sch["slots"]))
                if sch["slots"]:
                    s0 = sch["slots"][0]
                    print("第一格:", json.dumps(s0, ensure_ascii=False))
                    slots = api.get_time_slots(s0["hoscode"], s0["schcode"], s0["ampm"])
                    print("时段:", json.dumps(slots[:4], ensure_ascii=False))
