"""
主代理（个人助理5 · skill 消费版）— LLM 编排。

核心思路：不模拟点击，直接执行「skill（平台逆向 API）」拿真实数据。
工具：skill_list / skill_run / ask_user / web_search / done

事件循环安全（2026-08-07 修复死机）：
- LLM / 向量检索 / 博查搜索都是同步阻塞库，必须放线程池（asyncio.to_thread）
  ｜否则会卡死整个 uvicorn 事件循环 → App 轮询 task、WS 全断 → 表现为"死机"。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from .llm import LLMClient
from ..adapters import registry as adapters

logger = logging.getLogger("xiami.agent")

SYSTEM_PROMPT = """你是「生活助手」，帮用户解决日常生活里的大小事：订火车票/机票/酒店、景点门票、医院挂号、查信息、办事等。

办事方式 = 执行 skill（平台逆向 API，直接调 HTTP 接口，不是模拟点击/开网页）：
1. 系统已按你的话自动检索出「当前平台 + 最相关方法」给你（小纸条），
   **只在小纸条列出的方法里选**，不要用没列出的方法；若小纸条给了备选平台且客户意图
   明显是别的平台，再 skill_run 前用 skill_list 看看那个平台；
2. 用 skill_run(skill, method, params) 执行 skill 方法，拿真实数据，绝不编造；
3. 需要用户提供信息（验证码、手机号、确认等）→ 用 ask_user；
4. 查通用信息（新闻/政策/电话/价格）→ 用 web_search；
5. 需要精确当前时间（现在几点/上午下午/距某时刻还有多久/判断是否来得及）→
   用 get_current_time 工具拿云端准确时刻，不要自己猜时间；
6. **登录由系统自动处理，不需要 skill_run 登录方法**：
   若 skill_run 返回"需要登录"，系统会自动完成登录并重试，你只需照常继续业务；
   不要在对话里自行解释/编排登录步骤（登录中需用户输入的验证码，会由 App 直接弹出）；
7. 办完用 done 总结给用户。

平台规则（哪些方法能下单、需要登录等）以 skill_list / 小纸条里的方法描述为准，
按描述办事，不要自行发明平台不存在的下单步骤。

铁律：
- 图形验证码由 skill 方法获取，通过图片推送到 App 让用户看图输入（验证码真人配合）；
- 账号密码已由个人资料中心自动带入（skill_run 调登录方法时自动填），
  不要 ask_user 要账号密码；只有真的缺少（个人资料没存）才问；
- 登录态获取**优先「手机号+短信验证码」纯 skill 方式**（客户只收短信填码，最省事）；
  只有平台不支持手机验证码（如仅微信扫码/OAuth/一键登录）才引导客户在 App 内置浏览器
  完成登录并导出登录态到手机（客户点点点，云端不持有）；
- 真提交（下单/挂号/注册/支付）有副作用，提交前必须 ask_user 明确确认；
- 老站不稳定（403/慢）是常态，一次失败可换参数重试一次，再失败如实说明。"""


def _tool(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required or []},
    }}


TOOL_SPECS = [
    _tool("skill_list", "列出已接入的 skill（平台逆向 API）及可用方法（含是否需要登录）", {}),
    _tool("skill_run", "执行 skill 方法办理业务（返回结构化数据）",
          {"skill": {"type": "string", "description": "skill 标识（平台），如 glyy"},
           "method": {"type": "string", "description": "方法名（见 skill_list）"},
           "params": {"type": "object", "description": "方法参数"}},
          ["skill", "method"]),
    _tool("ask_user", "向用户提问/收集信息（账号密码、图形验证码、手机号、确认等）",
          {"question": {"type": "string"}}, ["question"]),
    _tool("web_search", "联网搜索通用信息（博查）", {"query": {"type": "string"}}, ["query"]),
    _tool("get_current_time", "获取当前精确时间（云端服务器时钟，含日期、星期、几点几分）。当需要判断现在几点/上午下午/距离某时刻还有多久等精确时刻时调用", {}),
    _tool("done", "办理完成，把最终结果回复给用户", {"reply": {"type": "string"}}, ["reply"]),
]

MAX_STEPS = 14


class Agent:
    """主代理：一次对话 = LLM + 工具循环，返回最终回复文本。"""

    def __init__(self, ask_user_fn: Callable[[str], Awaitable[str]] | None = None,
                 device_id: str = "") -> None:
        self.llm = LLMClient()
        self.ask_user_fn = ask_user_fn
        self.device_id = device_id or ""
        self.current_skill: str | None = None   # 会话内锁定的平台（小纸条机制）
        self._pending_image: str | None = None  # skill_run 返回的验证码图片（base64），下一次 ask_user 带上

    async def handle(self, text: str, history: list[dict] | None = None) -> str:
        """处理一条用户消息。history 为多轮对话记忆（[{role, content}]，只含 user/assistant 文本）。"""
        # 时间解析预处理：相对时间（今天/明天/这两天/周几）→ 具体日期，确定性注入上下文，
        # 避免 LLM 反问"这两天是哪两天"（date_utils 规则化解析，不依赖 LLM 猜）。
        # 云时间：date_utils 内部用 datetime.date.today()（云端服务器时钟，部署到腾讯云即云时间），
        # 未匹配到相对时间时也注入「今天」基准，让 LLM 自行兜底推算（不再返回空串）。
        time_note = ""
        try:
            from .date_utils import summarize
            time_note = summarize(text)
        except Exception as e:
            logger.warning("时间解析失败: %s", e)
            # 兜底：date_utils 异常时仍注入今日基准，保证 LLM 有"今天是几号"
            try:
                import datetime
                time_note = (f"【时间解析】今天是{datetime.date.today().isoformat()}"
                             f"（云端服务器日期）。")
            except Exception:
                pass
        # 当前时刻（几点/上午下午）按需注入：命中时间敏感词才带，避免每轮噪音/过时
        try:
            from .date_utils import clock_note
            clock_part = clock_note(text)
            if clock_part:
                time_note = "\n".join(x for x in (time_note, clock_part) if x)
        except Exception as e:
            logger.warning("当前时刻注入失败: %s", e)
        # 小纸条机制：先按用户这句话做两级检索，注入最相关平台+方法
        # （向量编码/模型加载是同步阻塞，放线程池，避免卡死事件循环）
        user_content = text
        try:
            note = await asyncio.to_thread(self._make_note, text)
        except Exception as e:
            logger.warning("小纸条检索异常: %s", e)
            note = None
        if note:
            try:
                note = await asyncio.to_thread(self._apply_debounce, note, text)
            except Exception as e:
                logger.warning("小纸条防抖异常: %s", e)
            parts = [f"【检索提示（只在这些方法里选）】\n{note.get('note')}"]
            if time_note:
                parts.append(time_note)
            parts.append(f"【用户原话】\n{text}")
            user_content = "\n\n".join(parts)
            self.current_skill = note.get("current_skill") or self.current_skill
        elif time_note:
            user_content = f"{time_note}\n【用户原话】\n{text}"
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        # 多轮记忆：最近若干轮 user/assistant 文本（ask_user 的提问/回答也记录在内）
        for h in (history or [])[-8:]:
            role = h.get("role")
            content = h.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": str(content)[:2000]})
        messages.append({"role": "user", "content": user_content})
        for _ in range(MAX_STEPS):
            # LLM 是同步阻塞调用（httpx.Client），放线程池执行，避免卡死事件循环
            out = await asyncio.to_thread(self.llm.chat_tools, messages, TOOL_SPECS)
            messages.append(out["message"])
            if not out["tool_calls"]:
                return out["text"] or "（无回复）"
            for tc in out["tool_calls"]:
                result = await self._run_tool(tc["name"], tc.get("arguments") or {})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False)[:20000],
                })
        return "处理步骤过多，已停止；请再描述一次你的需求。"

    # ─────────── 工具执行 ───────────
    async def _run_tool(self, name: str, args: dict) -> dict:
        args = args or {}
        try:
            if name == "skill_list":
                return {"ok": True, "data": self._skill_list_payload()}
            if name == "skill_run":
                self._fill_credentials(args)
                skill = str(args.get("skill", ""))
                method = str(args.get("method", ""))
                params = args.get("params") or {}
                # 自动触发登录：方法需要登录且未登录 → 自动走登录流程后重试（最多 2 次）
                for attempt in range(2):
                    result = await adapters.run(skill, method, params,
                                                device_id=self.device_id)
                    if isinstance(result, dict) and result.get("need_login"):
                        logger.info("检测到 %s 需要登录（第 %d 次）", skill, attempt + 1)
                        # 方案②：手机端全权处理登录（skill 声明了 login 配置的平台，如途牛）——
                        # 云端不编排登录，直接重试一次；手机端 SkillExecutor 在收到带 login 配置的
                        # 请求时会自动检测登录信号/无session → LoginCoordinator 登录 → 自动重试成功。
                        if self._skill_has_login(skill):
                            logger.info("%s 登录由手机端处理（login 配置），云端重试", skill)
                            if attempt == 0:
                                continue
                            result = dict(result)
                            result["note"] = f"需要先登录 {skill}（手机端未完成登录：{result.get('error', '')}）"
                            break
                        # 无 login 配置（如 glyy）→ 云端编排登录
                        ok = await self._ensure_login(skill)
                        if not ok:
                            result = dict(result)
                            result["note"] = f"需要先登录 {skill}（{result.get('error', '')}）"
                            break
                        continue
                    break
                # 若 skill 返回了验证码图片（base64），暂存给下一次 ask_user 推送 App
                data = result.get("data") if isinstance(result, dict) else None
                if isinstance(data, dict) and data.get("image_base64"):
                    self._pending_image = data["image_base64"]
                    logger.info("已捕获验证码图片，等待 ask_user 推送 App")
                # 第 5 条：下单/挂号成功返回 pay_url → 推送手机打开系统浏览器支付
                # （App 内零收款，支付全流程在第三方收银台完成）
                pay_url = ""
                if isinstance(data, dict):
                    pay_url = str(data.get("pay_url") or "")
                if pay_url and self.device_id:
                    try:
                        from ..channel.bridge import bridge
                        # 支付跳内置浏览器（与登录一致），避免弹系统「用哪个应用打开」选择框；
                        # 收银台/支付宝 H5 在内置浏览器内完成，App 内零收款。
                        await bridge.send_cmd(self.device_id, "navigate", {"url": pay_url})
                        result = dict(result)
                        result["note"] = "已在内置浏览器打开支付页面，支付完成后请用户回 App 告知"
                    except Exception as e:
                        logger.warning("推送支付页面失败: %s", e)
                return result
            if name == "ask_user":
                image = self._pending_image
                self._pending_image = None   # 用一次后清掉
                ans = await self._ask(str(args.get("question", "")), image)
                return {"ok": True, "answer": ans}
            if name == "get_current_time":
                # 云时间：返回云端服务器当前完整时刻（含日期/星期/几点几分），
                # 供 LLM 判断"现在几点/上午下午/距离某时刻还有多久"
                try:
                    import datetime
                    now = datetime.datetime.now()
                    wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
                    return {
                        "ok": True,
                        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "date": now.strftime("%Y-%m-%d"),
                        "time": now.strftime("%H:%M"),
                        "weekday": wd,
                        "note": f"当前为{wd} {now.strftime('%H:%M')}（云端服务器时间）",
                    }
                except Exception as e:
                    return {"ok": False, "error": f"获取当前时间失败：{e}"}
            if name == "web_search":
                return await self._web_search(str(args.get("query", "")))
            if name == "done":
                return {"ok": True, "done": True, "reply": args.get("reply", "")}
            return {"ok": False, "error": f"未知工具：{name}"}
        except Exception as e:
            logger.warning("tool %s 异常: %s", name, e)
            return {"ok": False, "error": f"{name} 异常：{e}"}

    def _skill_has_login(self, skill: str) -> bool:
        """该 skill 是否声明了 login 配置（方案②：手机端全权登录的平台）。"""
        try:
            from ..adapters.registry import ADAPTERS
            cfg = ADAPTERS.get(skill) or {}
            lg = cfg.get("login") or {}
            return bool(lg.get("method"))
        except Exception:
            return False

    # ─────────── 自动触发登录（skill_run 返回 need_login 时）───────────
    async def _ensure_login(self, skill: str) -> bool:
        """按 skill 触发登录：glyy 走验证码登录；tuniu 引导 M 站网页登录（真人配合滑块+短信，cookie 存手机）。"""
        if skill == "glyy":
            return await self._login_glyy()
        if skill == "tuniu":
            return await self._login_tuniu()
        return False

    async def _login_glyy(self, phone: str = "") -> bool:
        """glyy 自动登录：图形验证码→短信码→login（全部走手机通道，token 手机回写）。

        铁律（用户 2026-08-06）：glyy 一切请求走手机通道（云端组装蓝图→手机直连→回传解析），
        禁止云端 requests/curl 直连 glyy。
        """
        if not phone:
            phone = (await self._ask("登录鼓楼医院需要手机号，请输入您的手机号")).strip()
        if not phone:
            return False
        try:
            from ..adapters.registry import _make_executor
            from ..adapters.glyy_api import GlyyAPI
            # 图形码/短信/login 统一走手机通道（device_id 在线时注入 executor）
            api = GlyyAPI(executor=_make_executor(self.device_id)) if self.device_id else GlyyAPI()
            # 1. 图形验证码（手机直连，图片 base64 推送 App 让用户看）
            r = await api.get_graphical_captcha(phone)
            img = ""
            if isinstance(r, dict):
                img = str(r.get("image_base64") or "")
                if not img and isinstance(r.get("data"), dict):
                    img = str(r["data"].get("image_base64") or "")
            logger.info("glyy 图形码获取结果 ok=%s img长度=%d keys=%s",
                        bool(r.get("ok")), len(img), list((r or {}).keys())[:8])
            if not img:
                logger.warning("glyy 获取图形验证码失败: %s", r)
                await self._ask(f"图形验证码获取失败：{(r or {}).get('error') or '手机通道未响应'}。请确认 App 在线后重试。")
                return False
            gcode = (await self._ask("请查看上方验证码图片，输入图形验证码", img)).strip()
            if not gcode:
                return False
            # 2. 发送短信验证码（手机通道）
            r2 = await api.send_sms(phone=phone, gcode=gcode)
            if not r2.get("ok"):
                msg = str(r2.get("error") or "发送失败")
                logger.warning("glyy 发送短信失败: %s", msg)
                # 图形验证码错误（code=30023）→ 提示重新获取；短信未过验证码环节直接返回
                if str(r2.get("code")) == "30023":
                    await self._ask("图形验证码输入错误，请重新开始登录。")
                return False
            # 3. 短信验证码 → login（手机执行 + store 回写 token 到手机）
            code = (await self._ask("短信已发送，请尽快输入收到的短信验证码（验证码有效期很短）")).strip()
            if not code:
                return False
            r3 = await adapters.run("glyy", "login", {"phone": phone, "code": code},
                                    device_id=self.device_id)
            logger.info("glyy 登录结果: %s", r3)
            if not r3.get("ok"):
                err = str((r3.get("data") or {}).get("error") or r3.get("error") or "登录失败")
                # code=30004 → 手机号或验证码有误（多半是验证码过期/填错）→ 让用户重试登录
                await self._ask(f"登录失败：{err}。短信验证码有效期很短，请收到后尽快输入；"
                                f"若已过期，请说「重新登录鼓楼医院」。")
                return False
            return True
        except Exception as e:
            logger.warning("glyy 自动登录异常: %s", e)
            return False

    async def _login_tuniu(self, phone: str = "") -> bool:
        """途牛 M 站登录引导：自动弹内置浏览器打开登录页 → 真人滑块+短信 → 自动导出 cookie。

        登录态 = cookie（isLogined/ssoUser/muser/TUNIUmuser/tuniuuser_id）。
        流程（云端不持有登录态，全程手机本地）：
          1) send_cmd("navigate") → App 自动切到内置浏览器并打开 m.tuniu.com/user/login；
          2) 用户真人操作：输手机号 → 拖腾讯滑块（必现不可跳过）→ 输短信验证码；
          3) 用户回复「已登录」→ 云端 send_cmd("export_cookies") → App 自动导出 cookie 存手机凭据库；
          4) 之后 submit_order 由手机 SkillExecutor 自动补 Cookie 头（credential kind=cookie）。
        """
        try:
            from ..channel.bridge import bridge
            # 1) 自动弹出内置浏览器打开途牛登录页（点点点 → 直接跳浏览器）
            if self.device_id:
                try:
                    await bridge.send_cmd(self.device_id, "navigate",
                                          {"url": "https://m.tuniu.com/user/login"})
                except Exception as e:
                    logger.warning("途牛 navigate 打开登录页失败: %s", e)
            # 2) 引导真人操作（滑块必现，只能网页拖）
            await self._ask(
                "已在内置浏览器打开途牛登录页：\n"
                "1. 输入手机号（个人资料里的手机号）\n"
                "2. 拖动滑块通过人机验证\n"
                "3. 输入短信验证码完成登录\n"
                "完成后回复「已登录」，我会自动保存登录态继续下单。"
            )
            # 3) 用户说「已登录」→ 自动导出 cookie 存手机凭据库
            if self.device_id:
                try:
                    res = await bridge.send_cmd(self.device_id, "export_cookies",
                                                {"domain": "https://m.tuniu.com"})
                    logger.info("途牛 export_cookies: %s", str(res)[:200])
                except Exception as e:
                    logger.warning("途牛 export_cookies 失败: %s", e)
            return True
        except Exception as e:
            logger.warning("途牛 M 站登录引导异常: %s", e)
            return False

    # ─────────── 小纸条机制 ───────────
    def _make_note(self, text: str) -> dict | None:
        """两级检索 → 小纸条。模型不可用时返回 None（降级全量）。"""
        try:
            from ..retrieval.index import get_index
            idx = get_index()
            if idx is None:
                return None
            return idx.make_note(text, current_skill=self.current_skill)
        except Exception as e:
            logger.warning("向量检索小纸条生成失败（降级全量）: %s", e)
            return None

    def _apply_debounce(self, note: dict, user_text: str) -> dict:
        """防抖：检索 top-1 偏离当前平台时，连续 2 次才真正切换（避免客户一句话没说完就乱跳）。"""
        top_skill = note.get("top_skill") or ""
        if not self.current_skill:
            return note                     # 首次：直接锁定
        if top_skill == self.current_skill:
            self._drift_count = 0           # 回到当前平台 → 清零
            return note
        # top-1 偏离当前平台
        self._drift_count = getattr(self, "_drift_count", 0) + 1
        if self._drift_count >= 2:          # 连续 2 次偏离 → 切换
            self._drift_count = 0
            return note
        # 未达阈值 → 沿用当前平台，用原话在该平台内检索方法
        try:
            from ..retrieval.index import get_index
            idx = get_index()
            if idx is not None:
                kept = idx.make_note_for(self.current_skill, user_text)
                if kept:
                    return kept
        except Exception:
            pass
        return note

    def _skill_list_payload(self) -> list:
        """skill_list 返回：优先返回「当前小纸条」（当前平台方法），否则全量。

        system_only 方法（登录 4 步等）对 LLM 不可见——登录由 _ensure_login 代码编排，
        AI 只需调业务方法，收到 need_login 后系统自动登录重试，不让 AI 自行调用登录方法。
        """
        # 若当前已锁定平台 → 只返回该平台详情（含备选），避免一次给太多
        if self.current_skill:
            try:
                from ..adapters.registry import ADAPTERS
                cfg = ADAPTERS.get(self.current_skill)
                if cfg:
                    methods = [{"name": m, **info} for m, info in cfg["methods"].items()
                               if not info.get("system_only")]
                    if cfg.get("web_methods"):
                        methods += [{"name": m, **info} for m, info in cfg["web_methods"].items()
                                    if not info.get("system_only")]
                    return [{"skill": self.current_skill, "name": cfg["name"],
                             "flow": cfg.get("flow", []), "methods": methods,
                             "capability": cfg.get("capability", ""),
                             "capability_note": cfg.get("capability_note", "")}]
            except Exception:
                pass
        return adapters.list_skills()

    def _fill_credentials(self, args: dict) -> None:
        """登录/预约时自动从用户 profile（个人资料中心）取账号，免用户提供。
        只补 book 方法；用户 params 已带或 profile 没有则不覆盖。"""
        method = str(args.get("method") or "")
        if method not in ("book",):
            return
        params = dict(args.get("params") or {})
        if params.get("username") and params.get("password"):
            return
        try:
            from ..store.users import users

            u = users.get(self.device_id)
            prof = dict((u.profile or {}) if u else {})
            user = str(prof.get("username") or "")
            pwd = str(prof.get("password") or "")
            if user and pwd:
                params.setdefault("username", user)
                params.setdefault("password", pwd)
                args["params"] = params
                logger.info("已从个人资料自动带入账号 %s 用于 %s", user, method)
        except Exception:
            pass

    async def _ask(self, question: str, image: str | None = None) -> str:
        """问用户。image 为可选验证码图片（base64），推送到 App 显示给用户看。"""
        if self.ask_user_fn:
            try:
                if image:
                    try:
                        return str(await self.ask_user_fn(question, image)).strip()
                    except TypeError:
                        pass   # 旧签名不带 image，降级为只问文字
                return str(await self.ask_user_fn(question)).strip()
            except Exception as e:
                logger.warning("ask_user 异常: %s", e)
        return ""

    async def _web_search(self, query: str) -> dict:
        from ..config import get as cfg_get

        key = cfg_get("bocha_api_key")
        if not key:
            return {"ok": False, "error": "博查 API key 未配置（cloud/config.json 的 bocha.api_key）"}
        try:
            import httpx

            # 同步 httpx 会阻塞事件循环 → 用 async client（与死机修复一致）
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.bochaai.com/v1/web-search",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"query": query, "summary": True, "count": 5},
                )
            data = r.json()
            pages = []
            for item in (data.get("data", {}).get("webPages", {}).get("value") or []):
                pages.append({
                    "title": item.get("name", "")[:80],
                    "url": item.get("url", ""),
                    "summary": (item.get("summary") or "")[:300],
                })
            return {"ok": True, "query": query, "pages": pages[:5],
                    "answer": (data.get("data", {}).get("answer") or "")[:500]}
        except Exception as e:
            return {"ok": False, "error": f"搜索失败：{e}"}
