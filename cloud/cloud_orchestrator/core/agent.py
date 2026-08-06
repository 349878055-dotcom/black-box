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
1. 系统已按你的话自动检索出「当前平台 + 最相关方法」给你（小纸条），
   **只在小纸条列出的方法里选**，不要用没列出的方法；若小纸条给了备选平台且客户意图
   明显是别的平台，再 skill_run 前用 skill_list 看看那个平台；
2. 用 skill_run(skill, method, params) 执行 skill 方法，拿真实数据，绝不编造；
3. 查医生时优先用 find_doctor（给医院名+医生名，自动定位科室和医生），
   **不要向用户问科室**——除非 find_doctor 返回 error（找不到/多位同名）才问；
4. 需要用户提供信息（验证码、手机号、确认等）→ 用 ask_user；
4. 查通用信息（新闻/政策/电话）→ 用 web_search；
5. 办完用 done 总结给用户。

铁律：
- 图形验证码由 skill 方法获取，通过图片推送到 App 让用户看图输入（验证码真人配合）；
- 账号密码已由个人资料中心自动带入（skill_run 调登录方法时自动填），
  不要 ask_user 要账号密码；只有真的缺少（个人资料没存）才问；
- 真提交（挂号/下单/注册）有副作用，提交前必须 ask_user 明确确认；
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

    async def handle(self, text: str) -> str:
        # 小纸条机制：先按用户这句话做两级检索，注入最相关平台+方法
        user_content = text
        note = self._make_note(text)
        if note:
            note = self._apply_debounce(note, text)
            user_content = f"【检索提示（只在这些方法里选）】\n{note.get('note')}\n\n【用户原话】\n{text}"
            self.current_skill = note.get("current_skill") or self.current_skill
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
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
                return {"ok": True, "data": self._skill_list_payload()}
            if name == "skill_run":
                self._fill_credentials(args)
                result = adapters.run(
                    str(args.get("skill", "")),
                    str(args.get("method", "")),
                    args.get("params") or {},
                )
                # 若 skill 返回了验证码图片（base64），暂存给下一次 ask_user 推送 App
                data = result.get("data") if isinstance(result, dict) else None
                if isinstance(data, dict) and data.get("image_base64"):
                    self._pending_image = data["image_base64"]
                    logger.info("已捕获验证码图片，等待 ask_user 推送 App")
                return result
            if name == "ask_user":
                image = self._pending_image
                self._pending_image = None   # 用一次后清掉
                ans = await self._ask(str(args.get("question", "")), image)
                return {"ok": True, "answer": ans}
            if name == "web_search":
                return await self._web_search(str(args.get("query", "")))
            if name == "done":
                return {"ok": True, "done": True, "reply": args.get("reply", "")}
            return {"ok": False, "error": f"未知工具：{name}"}
        except Exception as e:
            logger.warning("tool %s 异常: %s", name, e)
            return {"ok": False, "error": f"{name} 异常：{e}"}

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
        """skill_list 返回：优先返回「当前小纸条」（当前平台方法），否则全量。"""
        # 若当前已锁定平台 → 只返回该平台详情（含备选），避免一次给太多
        if self.current_skill:
            try:
                from ..adapters.registry import ADAPTERS
                cfg = ADAPTERS.get(self.current_skill)
                if cfg:
                    methods = [{"name": m, **info} for m, info in cfg["methods"].items()]
                    if cfg.get("web_methods"):
                        methods += [{"name": m, **info} for m, info in cfg["web_methods"].items()]
                    return [{"skill": self.current_skill, "name": cfg["name"],
                             "flow": cfg.get("flow", []), "methods": methods}]
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
