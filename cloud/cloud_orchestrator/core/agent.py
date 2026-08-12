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
import re
from typing import Any, Awaitable, Callable

from .llm import LLMClient
from ..adapters import registry as adapters

logger = logging.getLogger("xiami.agent")

SYSTEM_PROMPT = """你是「生活助手」，帮用户解决日常生活里的大小事：订火车票/机票/酒店、景点门票、医院挂号、查信息、办事等。

办事方式 = 执行才艺（平台能力，直接调 HTTP 接口，不是模拟点击/开网页）：
1. 系统已按你的话自动检索出「当前平台 + 最相关方法」给你（小纸条），
   **只在小纸条列出的方法里选**，不要用没列出的方法；若小纸条给了备选平台且客户意图
   明显是别的平台，再 skill_run 前用 skill_list 看看那个平台；
2. 用 skill_run(skill, method, params) 执行才艺方法，拿真实数据，绝不编造；
3. 需要用户提供信息（验证码、手机号、确认等）→ 用 ask_user；
4. 查通用信息（新闻/政策/电话/价格）→ 用 web_search；
5. 需要精确当前时间（现在几点/上午下午/距某时刻还有多久/判断是否来得及）→
   用 get_current_time 工具拿云端准确时刻，不要自己猜时间；
6. **登录由系统自动处理（短信验证码，纯 API，无网页）**：
   - 用户要求「登录某平台」或要做需登录的操作 → 先 skill_run 该平台一个**需登录**的业务方法
     （如 glyy 的 visit_records / list_orders / get_patient 等）；系统检测到"需要登录"会
     自动走「手机号+短信验证码」登录（图形码/短信码由 App 弹出让用户配合输入），
     登录成功自动重试原业务；
   - **严禁自称"已发送验证码 / 已登录"**（你只是触发方法，真正发短信/登录是系统做的，
     你没真发）；拿到的结果若提示需要登录，就如实转达、让用户按 App 弹窗输入；
   - 不要在对话里自行解释/编排登录步骤；
7. 办完用 done 总结给用户。

平台规则（哪些方法能下单、需要登录等）以 skill_list / 小纸条里的方法描述为准，
按描述办事，不要自行发明平台不存在的下单步骤。

铁律：
- 图形验证码由才艺方法获取，通过图片推送到 App 让用户看图输入（验证码真人配合）；
- 账号密码已由个人资料中心自动带入（skill_run 调登录方法时自动填），
  不要 ask_user 要账号密码；只有真的缺少（个人资料没存）才问；
- 登录态获取**优先「手机号+短信验证码」纯才艺方式**（客户只收短信填码，最省事）；
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
    _tool("skill_list", "列出已接入的才艺（平台能力）及可用方法（含是否需要登录）", {}),
    _tool("skill_run", "执行才艺方法办理业务（返回结构化数据）",
          {"skill": {"type": "string", "description": "才艺标识（平台），如 glyy"},
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
        # 登录意图直通（2026-08-11：LLM 对"登录X"常幻觉"已发验证码"，
        # 这里绕过 LLM 直接触发系统登录编排，保证"登录鼓楼医院"可靠走纯 API 短信登录）
        try:
            direct_skill, direct_phone = self._direct_login(text)
            if direct_skill:
                logger.info("检测到明确登录意图 skill=%s phone=%s，直通系统登录编排",
                            direct_skill, direct_phone or "-")
                ok = await self._ensure_login(direct_skill, direct_phone)
                name = {"glyy": "鼓楼医院", "tuniu": "途牛"}.get(direct_skill, direct_skill)
                return (f"已开始为你登录{name}（纯短信验证码，无网页）。" if ok
                        else f"{name}登录未完成，请稍后重试或换网络。")
        except Exception as e:
            logger.warning("登录直通异常: %s", e)
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
                skill = str(args.get("skill", ""))
                method = str(args.get("method", ""))
                params = args.get("params") or {}
                # 前置依赖自动补齐（原子化 + 前置依赖）：requires 参数缺失时，
                # 代码自动现调源头方法拿真实编码填入，LLM 无需抄编号（导诊台机制）
                self._fill_misses = []   # 记录「提供了名字但匹配不到」的项
                params = await self._fill_requires(skill, method, params)
                # 匹配不上名字 → 明确返回错误给 AI，不继续瞎调（宁可报错也不挂错）
                if getattr(self, "_fill_misses", []):
                    return {"ok": False, "skill": skill, "method": method,
                            "error": "；".join(self._fill_misses)[:500],
                            "note": "请确认名称是否正确，或询问用户后重试"}
                # 自动触发登录：方法需要登录且未登录 → 云端通用登录器登录后自动重试（最多 2 次）
                for attempt in range(2):
                    result = await adapters.run(skill, method, params,
                                                device_id=self.device_id)
                    if isinstance(result, dict) and result.get("need_login"):
                        logger.info("检测到 %s 需要登录（第 %d 次）", skill, attempt + 1)
                        # 登录统一由云端 login_flow 编排（skill 在 contract.json 声明 login 配置）：
                        # 撞出未登录 → 隐藏内部错误 → 系统登录 → 自动重试原业务，
                        # 不把 token 失效/未登录等内部细节原样暴露给客户。
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

    # ─────────── 自动触发登录（skill_run 返回 need_login 时）───────────
    def _direct_login(self, text: str) -> tuple[str, str]:
        """检测明确登录意图：返回 (skill, 消息中手机号)。命中才直通，避免误触发普通对话。"""
        t = (text or "").strip()
        if "登录" not in t and "登" not in t:
            return "", ""
        phone = ""
        m = re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", t)
        if m:
            phone = m.group(0)
        low = t.lower()
        if "glyy" in low or "鼓楼" in t:
            return "glyy", phone
        if "tuniu" in low or "途牛" in t:
            return "tuniu", phone
        if "meituan" in low or "美团" in t or "外卖" in t:
            return "meituan_waimai", phone
        return "", ""

    async def _ensure_login(self, skill: str, phone: str = "") -> bool:
        """按 skill 声明的 login 配置触发登录（云端通用 login_flow，登录态存手机本地）。

        每个 skill 在 contract.json/register.py 声明 login 配置（method 区分登录方式）：
          sms_verify — 短信验证码纯 API（手机号→图形码→短信码→login，走手机通道）
          browser   — 内置浏览器真人登录（navigate→真人操作→导出登录态）
        登录编排逻辑统一在 core/login_flow.py，agent 不再为每个 skill 硬编码 _login_xxx。
        """
        try:
            from ..adapters.registry import ADAPTERS
            from .login_flow import run_login
            cfg = ADAPTERS.get(skill) or {}
            login_cfg = cfg.get("login") or {}
            if not login_cfg:
                logger.warning("skill %s 未声明 login 配置，无法自动登录", skill)
                return False
            return await run_login(skill, login_cfg, self.device_id, self._ask, phone)
        except Exception as e:
            logger.warning("登录编排异常 skill=%s: %s", skill, e)
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

    async def _fill_requires(self, skill: str, method: str, params: dict,
                             _seen: set | None = None) -> dict:
        """前置依赖自动补齐（原子化 + 前置依赖，导诊台机制）。

        方法在 contract.json 声明了 requires（某参数来自源头方法的返回字段）且参数缺失时，
        代码自动现调源头方法拿真实编码填入，LLM 无需抄编号。
        - match：用本方法已给参数（如医生名/科室名）在源头返回里精确匹配对应编码，
          避免「取第一个」导致挂错人/挂错科室/挂错时间。
        - pass_params：调源头方法时透传本方法的相关参数（如 train_num/date 传给 train_booking_info）。
        属执行层兜底：不新增方法、不改变原子性（不是聚合方法）。
        递归补齐源头方法自身的前置依赖（防多层依赖：list_depts → list_dept_doctors → register_online）。
        """
        params = dict(params or {})
        _seen = _seen or set()
        try:
            from ..adapters.registry import ADAPTERS
            cfg = ADAPTERS.get(skill)
            if not cfg:
                return params
            minfo = (cfg.get("methods") or {}).get(method)
            reqs = (minfo.get("requires") or []) if minfo else []
            for r in reqs:
                if not isinstance(r, dict):
                    continue
                param = r.get("param", "")
                if not param or params.get(param) not in (None, "", []):
                    continue
                from_m = r.get("from", "")
                field = r.get("field", "")
                if not from_m:
                    continue
                # 循环保护：仅当源头方法自身也有 requires（可能引发 A→B→A）才拦截；
                # 无 requires 的源头（如 resolve_city_code）可被不同参数多次调用（dep/arr）
                from ..adapters.registry import ADAPTERS as _AD
                _src_minfo = ((_AD.get(skill) or {}).get("methods") or {}).get(from_m) or {}
                _src_reqs = _src_minfo.get("requires") or []
                key = (skill, from_m)
                if _src_reqs and key in _seen:
                    continue
                new_seen = (_seen | {key}) if _src_reqs else _seen
                # 组装源头方法参数：递归补其前置依赖 + 按 pass_params 透传本方法已给参数
                src_params = await self._fill_requires(skill, from_m, {}, new_seen)
                pass_map = r.get("pass_params") or {}
                if isinstance(pass_map, dict):
                    for src_k, my_k in pass_map.items():
                        if params.get(my_k) not in (None, "", []):
                            src_params[src_k] = params[my_k]
                src = await adapters.run(skill, from_m, src_params, device_id=self.device_id)
                if not (isinstance(src, dict) and src.get("ok")):
                    logger.info("[fill_requires] %s.%s 源头 %s 失败，跳过自动补 %s",
                                skill, method, from_m, param)
                    continue
                # 按 match（用本方法已给参数精确匹配源头记录）取值，避免「取第一个」挂错
                val = self._extract_value(src.get("data"), field,
                                          r.get("match") or {}, params)
                if val not in (None, "", [], {}):
                    params[param] = val
                    logger.info("[fill_requires] %s.%s 自动补 %s=%s",
                                skill, method, param, str(val)[:50])
                elif r.get("match"):
                    # 提供了名字但没匹配到 → 记录明确错误（返回给 AI 让 TA 确认名字）
                    want_desc = "、".join(
                        f"{mk}={params.get(mv, '')}" for mk, mv in (r.get("match") or {}).items()
                        if params.get(mv) not in (None, "", []))
                    if want_desc:
                        msg = (f"自动补全失败：{method} 需要参数 {param}（来自 {from_m} 的 {field}），"
                               f"按你提供的信息「{want_desc}」在 {from_m} 结果中未找到匹配项")
                        self._fill_misses = getattr(self, "_fill_misses", [])
                        if msg not in self._fill_misses:
                            self._fill_misses.append(msg)
                        logger.info("[fill_requires] %s", msg)
        except Exception as e:
            logger.warning("[fill_requires] 异常: %s", e)
        return params

    def _extract_value(self, data, field: str, match: dict, params: dict):
        """从源头返回里取 field 的值。

        match: {源字段: 本方法参数名} —— 用本方法已给参数值在源头结果里精确匹配记录后取 field，
        解决「取第一个会挂错人/挂错科室」的问题。缺匹配键或匹配不到 → 返回 None（安全，不编造）。
        会递归进 data 的所有 list/dict（兼容 glyy 的 {normal:[...], expert:[...]} 结构，
        以及 doctor_name 在排班条目的嵌套 doctor 子对象里）。
        无 match 时取第一条含 field 的记录（单结果源头，如 get_patient/get_medical_card）。
        """
        if match and isinstance(match, dict):
            for it in self._flatten_records(data):
                if not isinstance(it, dict):
                    continue
                matched = True
                for src_field, my_param in match.items():
                    want = params.get(my_param)
                    if want in (None, "", []):
                        matched = False
                        break
                    if not self._match_value(it, src_field, want):
                        matched = False
                        break
                if matched:
                    return self._pick_field(it, field)
            return None
        return self._pick_field(data, field)

    def _match_value(self, record, src_field: str, want) -> bool:
        """在 record（含嵌套 list/dict）里找 src_field 字段，其值是否等于 want。"""
        if isinstance(record, dict):
            if src_field in record or self._camelize(src_field) in record:
                key = src_field if src_field in record else self._camelize(src_field)
                return str(record.get(key, "")).strip() == str(want).strip()
            for v in record.values():
                if isinstance(v, (dict, list)):
                    if self._match_value(v, src_field, want):
                        return True
        elif isinstance(record, list):
            for v in record:
                if isinstance(v, (dict, list)):
                    if self._match_value(v, src_field, want):
                        return True
        return False

    @staticmethod
    def _camelize(name: str) -> str:
        """dept_code → deptCode（字段名风格兼容：下划线/驼峰互认）。"""
        parts = str(name or "").split("_")
        return parts[0] + "".join(p.capitalize() for p in parts[1:]) if parts else ""

    def _flatten_records(self, data):
        """把返回值展开成所有 dict 记录（递归进 list/dict）。"""
        out = []
        if isinstance(data, list):
            for it in data:
                out.extend(self._flatten_records(it))
        elif isinstance(data, dict):
            out.append(data)
            for v in data.values():
                if isinstance(v, (list, dict)):
                    out.extend(self._flatten_records(v))
        return out

    def _pick_field(self, data, field: str):
        """从源头方法返回值里取字段。支持 a.b 路径；data 为 list 时取首个命中项。"""
        if field == "patient":
            return data if isinstance(data, dict) else None
        if isinstance(data, list):
            for it in data:
                if isinstance(it, dict):
                    v = self._pick_field(it, field)
                    if v not in (None, "", [], {}):
                        return v
            return None
        if isinstance(data, dict):
            for key in (field, self._camelize(field)):
                if key in data and data.get(key) not in (None, "", [], {}):
                    return data.get(key)
            if "." in field:
                cur = data
                for p in field.split("."):
                    p_key = p if p in cur else self._camelize(p)
                    if isinstance(cur, list):
                        cur = next((x.get(p_key) for x in cur
                                    if isinstance(x, dict) and x.get(p_key) is not None), None)
                    elif isinstance(cur, dict):
                        cur = cur.get(p_key)
                    else:
                        return None
                    if cur is None:
                        return None
                return cur
        return None

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
