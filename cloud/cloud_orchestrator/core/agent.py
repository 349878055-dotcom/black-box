"""
主代理（个人助理5 · skill 消费版）— LLM 编排。

核心思路：不模拟点击，直接执行「skill（平台逆向 API）」拿真实数据。
工具：skill_list / skill_run / ask_user / web_search / done
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from .llm import LLMClient
from ..adapters import registry as adapters

logger = logging.getLogger("xiami.agent")

SYSTEM_PROMPT = """你是「老百姓助手」，帮老百姓在网上办事（预约挂号、查号源、注册等）。

办事方式 = 执行 skill（平台逆向 API，直接调 HTTP 接口，不是模拟点击/开网页）：
1. 先 skill_list 看有哪些 skill（平台）。每个 skill 带「flow」分层地图
   （如 12320：①医院→②科室→③医生→④排班→⑤时段→⑥登录→⑦预约），
   先看 flow 顺着步骤调用，不要乱跳、不要跳过依赖步骤（后面的方法需要前面返回的代码）；
2. 用 skill_run(skill, method, params) 执行 skill 方法，拿真实数据，绝不编造；
3. 查医生时优先用 find_doctor（给医院名+医生名，自动定位科室和医生），
   **不要向用户问科室**——除非 find_doctor 返回 error（找不到/多位同名）才问；
4. 需要用户提供信息（12320 账号密码、图形验证码、手机号、确认）→ 用 ask_user；
4. 查通用信息（新闻/政策/电话）→ 用 web_search；
5. 办完用 done 总结给用户。

铁律：
- 图形验证码由 skill 本地 OCR 自动识别（login_auto），不需要用户看图；
- 账号密码已由个人资料中心自动带入（skill_run 调 book/login 时自动填），
  不要 ask_user 要账号密码；只有真的缺少（个人资料没存）才问；
- 真提交（挂号/下单/注册）有副作用，提交前必须 ask_user 明确确认；
- 12320 老站不稳定（403/慢）是常态，一次失败可换参数重试一次，再失败如实说明。

流程提示（12320 挂号）：
- search_hospital 得医院 → list_departments 得科室（返回全部科室，直接从中找目标科室名，无需 web_search）→
  get_schedule 得排班（可约格子 schcode）→ get_time_slots 得具体时段 →
  check_login 看是否登录 → 未登录则 login（ask_user 向用户要图形验证码）→ 确认后预约。"""


def _tool(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required or []},
    }}


TOOL_SPECS = [
    _tool("skill_list", "列出已接入的 skill（平台逆向 API）及可用方法（含是否需要登录）", {}),
    _tool("skill_run", "执行 skill 方法办理业务（返回结构化数据）",
          {"skill": {"type": "string", "description": "skill 标识（平台），如 nj12320"},
           "method": {"type": "string", "description": "方法名（见 skill_list）"},
           "params": {"type": "object", "description": "方法参数"}},
          ["skill", "method"]),
    _tool("ask_user", "向用户提问/收集信息（账号密码、图形验证码、手机号、确认等）",
          {"question": {"type": "string"}}, ["question"]),
    _tool("web_search", "联网搜索通用信息（博查）", {"query": {"type": "string"}}, ["query"]),
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

    async def handle(self, text: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        for _ in range(MAX_STEPS):
            out = self.llm.chat_tools(messages, TOOL_SPECS)
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
                return {"ok": True, "data": adapters.list_skills()}
            if name == "skill_run":
                self._fill_credentials(args)
                return adapters.run(
                    str(args.get("skill", "")),
                    str(args.get("method", "")),
                    args.get("params") or {},
                )
            if name == "ask_user":
                ans = await self._ask(str(args.get("question", "")))
                return {"ok": True, "answer": ans}
            if name == "web_search":
                return await self._web_search(str(args.get("query", "")))
            if name == "done":
                return {"ok": True, "done": True, "reply": args.get("reply", "")}
            return {"ok": False, "error": f"未知工具：{name}"}
        except Exception as e:
            logger.warning("tool %s 异常: %s", name, e)
            return {"ok": False, "error": f"{name} 异常：{e}"}

    def _fill_credentials(self, args: dict) -> None:
        """预约/登录时自动从用户 profile（个人资料中心）取 12320 账号密码，免用户提供。
        只补 book/login/login_auto；用户 params 已带或 profile 没有则不覆盖。"""
        method = str(args.get("method") or "")
        if method not in ("book", "login", "login_auto"):
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

    async def _ask(self, question: str) -> str:
        if self.ask_user_fn:
            try:
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

            r = httpx.post(
                "https://api.bochaai.com/v1/web-search",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"query": query, "summary": True, "count": 5},
                timeout=30,
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
