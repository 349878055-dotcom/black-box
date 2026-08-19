"""
主代理业务层（个人助理5）。

调度（模型何时调工具）→ LangGraph，见 graph_engine.py。
本文件写业务：Chat/Hired 人设、经验书、skill 闸门、fill_requires、login、支付。

人选由客户手动挂会话 persona；LLM 不选人。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Awaitable, Callable

from ..adapters import registry as adapters

logger = logging.getLogger("xiami.agent")

SYSTEM_PROMPT_CHAT = """你是「虾米」，家里的闲聊助手。

本对话没有指定帮手：
- 可以闲聊、解释、陪聊；
- 查公开事实（新闻/政策/电话/价格/开放时间等）→ 用 search(scope="web")（博查）；
- 需要用户补充一句再查 → 用 ask_user；
- 答完用 done 收束（或直接文字回复）。

铁律：
- **不能办事**：不能挂号、买票、点外卖、登录医院/平台、下单、支付；
- 用户若要办事 → 如实告知去「✨ 才艺」找对应的人，不要假装已办或编造结果；
- 不编造未检索到的事实。"""

SYSTEM_PROMPT_HIRED = """你是「{name}」，客户在才艺里找你办事。你是一个**通过工具办事的代理**：每办一步都靠调用工具拿到真实结果，绝不用纯文字代替办事。

{greeting}

【做事习惯】
{how_block}

【经验书】（按这些经验提问与停手，不要省略该问的）
{experience_block}

【你名下的才艺】只能 skill_run 这些 skill id：{skills_csv}
（每个才艺的具体方法、参数、要问客户什么、登录态、交付方式——都写在契约里，用 read_skill 读，不背、不编造）

【才艺检查 · 回复前必做】（先做这步，再动手）：
Step 1 评估：客户请求对得上名下哪个才艺？对照：{skills_csv}
Step 2 分支：
- 命中才艺 → 只选一个；【必须先 read_skill 读契约，加载契约后才能继续】；
  【严格按契约的方法自包含（requires 前置依赖 + customer_input）一步步走，不得超出、不得跳过】；
- 没命中（咨询/闲聊）→ 正常回复，不读契约、不拉才艺。
约束：不许跳过本检查；只在选中才艺后才读契约；会话里已读过的契约不重复读。

【★ 每轮必须调工具】：
- 办理中每轮必须至少调用一个工具来推进，禁止用纯文字回复代替办理步骤；
- 纯文字只允许用于：咨询/闲聊、或 done 收束前的阶段小结。

【每轮决策】（先评估：我现在已有什么信息、还缺什么？再选工具；具体以契约为准）：
1. 不知道用哪个才艺/方法 → 调 search 拿候选再挑；search 优先 scope=skill 搜名下才艺，只有名下确实没有、或要外部公开信息时才 scope=web；
2. 定了才艺 → 先 read_skill 读契约，按契约的方法参数/前置依赖/提示推进（要问客户什么、谁填参数、登录态、交付方式，全看契约）；
3. 按契约问客户：read_skill 读到的方法若有 `customer_input`（声明要问客户的参数），缺就逐个 ask_user 问（一次一件）；若契约有 `form` 字段表，只问 source=customer 且还没填的（auto/profile 不要问）；契约没标要客户提供的，不要自己发明要问的；**禁止用文字反问收集信息**——文字反问客户无法把答案喂回流程；
4. 要真实数据 → 调 skill_run 拿真实结果，绝不编造；
5. **客户要办的事需要分多步推进时（如多天比价、先查再订、多店对比、多事项代办等），用 update_step 记录执行进度，每办完一步更新 status=done**（一步就能办完的不必建）；
6. 办完 / 如实说明失败后 → 调 done 收束。

【铁律】：
- 只做名下才艺；越界（经验书写明不代做的）直接拒绝并说明边界；
- 一切按 read_skill 读到的契约为准，不编造、不假装成功；
- skill_run 失败 → 看原因，必要时 read_skill 读契约诊断 → 补/改参重试一次 → 仍失败如实告知客户，禁止编造。

【通用行为】（吸收 Zoo Code 通用规则）：
- 能用工具/已有信息搞定的，就别多问客户；
- 目标是完成客户的任务，不是来回闲聊；办事要直接、切题；
- done 收束的结果要写成最终结论，不要在结尾提问或请求继续对话；
- 每次工具用完后看结果再决定下一步，别假设；
- 客户要分多步推进的任务（如比价、先查再订、多事项代办），按顺序逐次推进；单步办理的任务直接调 skill_run，前置由代码自动补；
- 每次调工具前先想：这一步该用哪个工具、参数齐不齐（参数不齐先 ask_user 补齐，别硬调）。"""


MAX_STEPS = 14

# 向量检索相似度阈值：低于它视为"乱码/无关话"，不硬塞候选（待定 2 已落地）
_MIN_VECTOR_SCORE = 0.5


class Agent:
    """业务运行时：人设闸门 + 工具实现；调度由 LangGraph 完成。"""

    def __init__(self, ask_user_fn: Callable[[str], Awaitable[str]] | None = None,
                 device_id: str = "",
                 steps_fn: dict | None = None,
                 form_fn: dict | None = None) -> None:
        self.ask_user_fn = ask_user_fn
        self.device_id = device_id or ""
        # 执行进度锚点（update_todo_list 轻量版）：{get: ()->list, set: (steps)->None}
        self.steps_fn = steps_fn or {}
        # 契约 form 字段表：{get: ()->dict, set: (forms)->bool}；无回调则用内存
        self.form_fn = form_fn or {}
        self._form_mem: dict = {}
        self.current_skill: str | None = None
        self._pending_image: str | None = None
        self.allowed_skills: list[str] = []
        self.person_id: str = ""
        self.hired: bool = False
        self._done_reply: str | None = None

    async def handle(self, text: str, history: list[dict] | None = None,
                     persona: dict | None = None) -> str:
        """处理一条用户消息。persona 来自会话（手动找人）；history 为多轮文本。"""
        persona = persona if isinstance(persona, dict) else {}
        self.person_id = str(persona.get("person_id") or "").strip()
        self.hired = bool(self.person_id)
        self.allowed_skills = self._resolve_allowed_skills(persona)
        self._done_reply = None

        if self.hired:
            system = self._build_hired_system()
        else:
            system = SYSTEM_PROMPT_CHAT

        # 时间解析预处理
        time_note = ""
        try:
            from .date_utils import summarize
            time_note = summarize(text)
        except Exception as e:
            logger.warning("时间解析失败: %s", e)
            try:
                import datetime
                time_note = (f"【时间解析】今天是{datetime.date.today().isoformat()}"
                             f"（云端服务器日期）。")
            except Exception:
                pass
        try:
            from .date_utils import clock_note
            clock_part = clock_note(text)
            if clock_part:
                time_note = "\n".join(x for x in (time_note, clock_part) if x)
        except Exception as e:
            logger.warning("当前时刻注入失败: %s", e)

        user_content = text
        # 问题⑩（2026-08-16 用户拍板）：删除「每次强制向量检索塞小纸条」环节——
        # 检索回归 AI 主动工具（后续加 search 工具），不再每句话强制注入检索结果。
        # 仅保留时间注入 + 用户原话。
        if time_note:
            user_content = f"{time_note}\n【用户原话】\n{text}"

        # 登录直通：仅 Hired
        if self.hired:
            try:
                direct_skill, direct_phone = self._direct_login(text)
                if direct_skill and (
                    not self.allowed_skills or direct_skill in self.allowed_skills
                ):
                    # 隐私：日志不记录完整手机号，只留尾 4 位
                    _phone_masked = (str(direct_phone or "")[-4:] if direct_phone else "-")
                    logger.info("检测到明确登录意图 skill=%s phone尾4位=%s，直通系统登录编排",
                                direct_skill, _phone_masked or "-")
                    ok = await self._ensure_login(direct_skill, direct_phone)
                    from ..adapters.registry import get_adapter
                    cfg = get_adapter(direct_skill, self.person_id) or {}
                    name = str(cfg.get("name") or direct_skill)
                    login_m = str((cfg.get("login") or {}).get("method") or "")
                    if login_m == "sms_verify":
                        how = "（短信验证码）"
                    elif login_m == "browser":
                        how = "（需在页面完成登录）"
                    else:
                        how = ""
                    return (f"已开始为你登录{name}{how}。" if ok
                            else f"{name}登录未完成，请稍后重试或换网络。")
            except Exception as e:
                logger.warning("登录直通异常: %s", e)

        # 调度交给 LangGraph（业务仍在 _run_tool）
        from .graph_engine import run_react
        return await run_react(
            runtime=self,
            system=system,
            user_content=user_content,
            history=history,
            hired=self.hired,
            max_steps=MAX_STEPS,
        )

    def _resolve_allowed_skills(self, persona: dict) -> list[str]:
        """名下才艺：只认挂在此人 skill 档案下的包（owner_id = person_id）。"""
        if not self.person_id:
            return []
        raw = persona.get("skills") or []
        from_persona = [str(x).strip() for x in raw if str(x).strip()]
        candidates: list[str] = []
        try:
            from ..store.archive_center.skill_archive.cards import cards
            card = cards.get(self.person_id)
            if card:
                from_card = [str(s.get("id") or "").strip()
                             for s in (card.get("skills") or [])
                             if isinstance(s, dict) and s.get("id")]
                if from_card:
                    if from_persona:
                        candidates = [s for s in from_persona if s in from_card] or from_card
                    else:
                        candidates = from_card
        except Exception as e:
            logger.warning("读取上台卡 skills 失败: %s", e)
        if not candidates:
            candidates = from_persona
        # 再按注册表归属过滤：必须挂在此人目录下（签名 owner/skill）
        try:
            from ..adapters.registry import get_adapter
            owned = []
            for sid in candidates:
                if get_adapter(sid, self.person_id):
                    owned.append(sid)
            return owned
        except Exception as e:
            logger.warning("按 owner 过滤 skills 失败: %s", e)
            return candidates

    def _build_hired_system(self) -> str:
        """按上台卡拼人设 system（经验书 + how）。"""
        name = self.person_id or "帮手"
        greeting = ""
        how_lines: list[str] = []
        exp_lines: list[str] = []
        try:
            from ..store.archive_center.skill_archive.cards import cards
            card = cards.get(self.person_id) or {}
            name = card.get("name") or name
            greeting = str(card.get("greeting") or "").strip()
            for s in (card.get("skills") or []):
                if not isinstance(s, dict):
                    continue
                sid = s.get("id") or ""
                if self.allowed_skills and sid not in self.allowed_skills:
                    continue
                label = s.get("label") or sid
                how = (s.get("how") or "").strip()
                how_lines.append(f"- {label}（{sid}）：{how or '按客户需求办理'}")
            for e in (card.get("experience") or []):
                if not isinstance(e, dict):
                    continue
                title = (e.get("title") or "").strip()
                note = (e.get("note") or "").strip()
                if title or note:
                    exp_lines.append(f"- {title}：{note}" if title else f"- {note}")
        except Exception as e:
            logger.warning("拼人设 system 失败: %s", e)
        if not how_lines:
            how_lines = [f"- {s}" for s in self.allowed_skills] or ["- （未挂才艺）"]
        if not exp_lines:
            exp_lines = ["- 问清楚再动手；按契约推进，真下单类以契约为准。"]
        if not greeting:
            greeting = f"我是{name}，你说要办的事就行。"
        return SYSTEM_PROMPT_HIRED.format(
            name=name,
            greeting=greeting,
            how_block="\n".join(how_lines),
            experience_block="\n".join(exp_lines),
            skills_csv="、".join(self.allowed_skills) or "（无）",
        )

    # ─────────── 工具执行 ───────────
    async def _run_tool(self, name: str, args: dict) -> dict:
        args = args or {}
        try:
            if name == "skill_run":
                if not self.hired:
                    return {"ok": False, "error": "当前是闲聊对话，不能办事；请去「✨ 才艺」找对应的人"}
                skill = str(args.get("skill", ""))
                method = str(args.get("method", ""))
                params = args.get("params") or {}
                if self.allowed_skills and skill not in self.allowed_skills:
                    return {"ok": False, "skill": skill, "method": method,
                            "error": f"当前帮手不会「{skill}」，名下才艺：{', '.join(self.allowed_skills)}"}
                self.current_skill = skill
                # 契约 form：已填值补进参数；auto 字段现调源头；写回会话状态
                params = await self._apply_form(skill, params)
                # 前置依赖自动补齐（原子化 + 前置依赖）：requires 参数缺失时，
                # 代码自动现调源头方法拿真实编码填入，LLM 无需抄编号（导诊台机制）
                self._fill_misses = []   # 记录「提供了名字但匹配不到」的项
                self._fill_cache = {}    # 源头结果缓存（同一次 skill_run 内复用，避免重复查接口）
                params = await self._fill_requires(skill, method, params)
                # 匹配不上名字 → 明确返回错误给 AI，不继续瞎调（宁可报错也不挂错）
                if getattr(self, "_fill_misses", []):
                    return {"ok": False, "skill": skill, "method": method,
                            "error": "；".join(self._fill_misses)[:500],
                            "note": "请确认名称是否正确，或询问用户后重试"}
                # date 参数规范化（methods[].params.type=date）
                params = self._normalize_date_params(skill, method, params)
                # confirm: true → 执行前用户确认
                if not await self._confirm_if_needed(skill, method):
                    return {"ok": False, "skill": skill, "method": method,
                            "error": "用户未确认，已取消执行"}
                # 自动触发登录：方法需要登录且未登录 → 云端通用登录器登录后自动重试（最多 2 次）
                for attempt in range(2):
                    result = await adapters.run(skill, method, params,
                                                device_id=self.device_id,
                                                owner_id=self.person_id)
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
                # 付款产物：按 contract.payment 声明打开链接或提示 scheme
                result = await self._deliver_payment(skill, method, result)
                return result
            if name == "read_skill":
                if not self.hired:
                    return {"ok": False, "error": "当前是闲聊对话，不能读取才艺；请去「✨ 才艺」找对应的人"}
                return self._read_skill(str(args.get("skill", "")))
            if name == "ask_user":
                image = self._pending_image
                self._pending_image = None   # 用一次后清掉
                opts = args.get("options") or []
                opts = [str(x) for x in opts if str(x).strip()] if isinstance(opts, list) else []
                question = str(args.get("question", ""))
                ans = await self._ask(question, image, options=opts)
                self._store_form_answer(question, ans)
                return {"ok": True, "answer": ans}
            if name == "search":
                # 问题⑩（2026-08-16）：统一检索工具——AI 自己生成关键词 + 选 scope。
                # scope=skill：搜名下才艺/方法（向量比意思 / 关键词找字，返回候选 top-3 完整信息）
                # scope=web  ：搜外部互联网（博查，等价原 web_search）
                # 检索结果只在 AI 调用后返回，不再每句话强制注入。
                # scope 归一化：兼容大小写/首尾空格（WEB / web  /  web 一律按 web 处理）
                scope = str(args.get("scope", "") or "skill").strip().lower()
                if not self.hired and scope != "web":
                    return {"ok": False, "error": "当前是闲聊对话，不能检索名下才艺；请去「✨ 才艺」找人"}
                query = str(args.get("query", "") or "").strip()
                if not query:
                    return {"ok": False, "scope": scope,
                            "error": "缺少搜索关键词（query）"}
                method = str(args.get("method", "") or "vector")
                if scope == "web":
                    return await self._web_search(query)
                # scope=skill（默认）：向量或关键词检索名下才艺/方法
                return await self._search_skill(query, method=method)
            if name == "done":
                return {"ok": True, "done": True, "reply": args.get("reply", "")}
            if name == "update_step":
                # 问题⑧-1（防御）：update_step 只在 hired（雇了才艺人）时可用。
                # 不能只靠"工具只在 hired 才挂载"兜住，分支内也加一道防线。
                if not self.hired:
                    return {"ok": False, "error": "当前是闲聊对话，不能维护执行进度；请去「✨ 才艺」找对应的人"}
                # 执行进度锚点（update_todo_list 轻量版）：覆盖式写入当前任务步骤
                raw = args.get("steps") or []
                if not isinstance(raw, list):
                    return {"ok": False, "error": "steps 需为列表：[{step,title,status}]"}
                setter = self.steps_fn.get("set") if isinstance(self.steps_fn, dict) else None
                if not setter:
                    # 问题③：进度根本没处可存（steps_fn 没传/任务卡片缺失）时，
                    # 如实报错，不让虾米误以为写上了。
                    return {"ok": False, "error": "进度存储不可用"}
                saved = setter(raw)
                if saved is False:
                    # 问题③：落库失败（跨轮记忆会丢）也要如实告知，不假装成功。
                    return {"ok": False, "error": "进度保存失败，请稍后重试"}
                # 问题④：回读实际生效版（清洗后：截断/丢弃/序号重排/状态归一）再返回，
                # 虾米拿到的永远是"真存下来的清单"，不和 App 端对不上。
                getter = self.steps_fn.get("get") if isinstance(self.steps_fn, dict) else None
                actual = getter() if getter else None
                if not isinstance(actual, list):
                    actual = raw
                return {"ok": True, "steps": actual}
            return {"ok": False, "error": f"未知工具：{name}"}
        except Exception as e:
            logger.warning("tool %s 异常: %s", name, e)
            return {"ok": False, "error": f"{name} 异常：{e}"}

    # ─────────── 自动触发登录（skill_run 返回 need_login 时）───────────
    def _direct_login(self, text: str) -> tuple[str, str]:
        """检测明确登录意图：对照名下 skill 的 name/aliases（不写死平台）。

        收紧触发词（问题⑩）：只认「登录/登陆」整词，不认单字「登」——
        否则「登山 / 五谷登丰」等含「登」的话会误触发登录编排。
        """
        t = (text or "").strip()
        if not any(w in t for w in ("登录", "登陆")):
            return "", ""
        phone = ""
        m = re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", t)
        if m:
            phone = m.group(0)
        low = t.lower()
        try:
            from ..adapters.registry import get_adapter
            loggable: list[str] = []
            for sid in (self.allowed_skills or []):
                cfg = get_adapter(sid, self.person_id) or {}
                if not cfg.get("login"):
                    continue
                loggable.append(sid)
                needles = [sid, str(cfg.get("name") or "")]
                needles.extend(str(a) for a in (cfg.get("aliases") or []) if a)
                for n in needles:
                    n = str(n or "").strip()
                    if not n:
                        continue
                    if n.lower() in low or n in t:
                        return sid, phone
            if len(loggable) == 1:
                return loggable[0], phone
        except Exception as e:
            logger.warning("登录直通匹配失败: %s", e)
        return "", ""

    async def _ensure_login(self, skill: str, phone: str = "") -> bool:
        """按 skill 声明的 login 配置触发登录（云端通用 login_flow）。"""
        try:
            from ..adapters.registry import get_adapter
            from .login_flow import run_login
            cfg = get_adapter(skill, self.person_id) or {}
            login_cfg = cfg.get("login") or {}
            if not login_cfg:
                logger.warning("skill %s 未声明 login 配置，无法自动登录", skill)
                return False
            return await run_login(
                skill, login_cfg, self.device_id, self._ask, phone,
                owner_id=self.person_id,
            )
        except Exception as e:
            logger.warning("登录编排异常 skill=%s: %s", skill, e)
            return False

    # ─────────── 小纸条机制 ───────────
    def _make_note(self, text: str) -> dict:
        """两级检索 → 小纸条。仅 Hired 调用；限定 allowed_skills。

        铁律（2026-08-16）：向量检索不可用/失败直接抛错暴露，绝不降级 skill_list 全量。
        """
        from ..retrieval.index import get_index

        idx = get_index()
        if idx is None:
            raise RuntimeError(
                "向量索引不可用（BGE 模型未加载/缺 torch），请检查 retrieval 依赖"
            )
        return idx.make_note(
            text,
            current_skill=self.current_skill,
            allowed_skills=self.allowed_skills or None,
            owner_id=self.person_id or None,
        )

    def _keyword_search_payloads(self) -> list[dict]:
        """关键词检索候选快照：每个名下才艺一条，含完整方法信息 + 命中用 _hay 文本。

        keyword 语义 = 找字面：客户显式说出平台名/方法名/别名/触发词时用它。
        不走 _skill_list_payload 的 current_skill 锁定——keyword 应全量名下才艺，
        否则客户说"美团"却被当前平台锁住就找不到了。
        """
        from ..adapters.registry import get_adapter, is_ai_visible

        out = []
        for sid in (self.allowed_skills or []):
            cfg = get_adapter(sid, self.person_id)
            if not cfg:
                continue
            methods = [{"name": m, **info} for m, info in (cfg.get("methods") or {}).items()
                       if is_ai_visible(info)]
            if cfg.get("web_methods"):
                methods += [{"name": m, **info} for m, info in cfg["web_methods"].items()
                            if is_ai_visible(info)]
            aliases = [str(a) for a in (cfg.get("aliases") or []) if str(a).strip()]
            # 问题⑥（字段加权排序）：命中文本拆三档——
            # name 档（平台名/别名/sid，权重最高）、method 档（方法名，中）、rest 档（说明/触发词，低）
            name_parts = [str(sid), str(cfg.get("name") or ""), " ".join(aliases)]
            method_parts = [str(m.get("name") or "") for m in methods]
            rest_parts = [str(cfg.get("capability_note") or "")]
            for m in methods:
                kws = " ".join(str(k) for k in (m.get("keywords") or []) if str(k).strip())
                rest_parts.append(f"{m.get('desc') or ''} {kws}")
            hay_parts = name_parts + method_parts + rest_parts
            out.append({
                "skill": sid,
                "name": cfg.get("name", sid),
                "methods": methods,
                "rules": cfg.get("rules") or [],
                "capability": cfg.get("capability", ""),
                "capability_note": cfg.get("capability_note", ""),
                "deliver": cfg.get("deliver", ""),
                "payment": cfg.get("payment") or {},
                "_hay": " ".join(x for x in hay_parts if x).lower(),
                "_hay_name": " ".join(x for x in name_parts if x).lower(),
                "_hay_method": " ".join(x for x in method_parts if x).lower(),
                "_hay_rest": " ".join(x for x in rest_parts if x).lower(),
            })
        return out

    async def _search_skill(self, query: str, method: str = "vector") -> dict:
        """统一 search 工具的 skill 分支：搜名下才艺/方法，返回候选 top-3 完整信息。

        method=vector → 向量语义检索（比意思），走 _make_note 小纸条；
        method=keyword → 关键词检索（找字），按平台名/别名/方法名/desc/触发词找字面命中。
        结果让 AI 自己挑（候选带完整信息 + 可读 note），不再是"系统锁死 top-1"。
        """
        q = (query or "").strip()
        if not q:
            return {"ok": False, "method": method, "query": query,
                    "error": "缺少搜索关键词（query）"}
        from ..retrieval.index import get_index

        idx = get_index()
        if idx is None:
            raise RuntimeError(
                "向量索引不可用（BGE 模型未加载/缺 torch），请检查 retrieval 依赖"
            )
        # 关键词搜法：在名下才艺的 name/别名/方法名/desc/触发词/流程标题里找字面命中的
        # 问题⑤（拆词匹配）：先把客户话按空格/标点切成词，再分开去 _hay 里找；
        # 命中词数>0 才入选，按命中词数降序排（多词不再整串硬匹配，不会拆乱——规则写死）。
        if method == "keyword":
            tokens = [w for w in re.split(r"[\s,，。、.!?！？;；:：/]+", q.lower()) if w]
            # 问题⑥（字段加权排序）：平台名/别名/sid 命中 3 分、方法名 2 分、说明/触发词 1 分，按总分降序
            scored = []
            for sk in self._keyword_search_payloads():
                score = 0
                for w in tokens:
                    if w in (sk.get("_hay_name") or ""):
                        score += 3
                    elif w in (sk.get("_hay_method") or ""):
                        score += 2
                    elif w in (sk.get("_hay_rest") or ""):
                        score += 1
                if score > 0:
                    scored.append((sk, score))
            scored.sort(key=lambda x: -x[1])
            candidates = []
            lines = []
            for i, (sk, sc) in enumerate(scored[:3], start=1):
                # 问题⑪：候选统一带 score（加权命中分），与 vector 候选格式一致
                candidates.append({"skill": sk["skill"], "name": sk["name"],
                                   "score": sc,
                                   "methods": [m["name"] for m in sk["methods"]]})
                lines.append(f"【候选平台 {i}】{sk['name']}（skill={sk['skill']}）")
                lines.append("【该平台相关方法】")
                for m in sk["methods"]:
                    params = "，".join(f"{k}={v}" for k, v in (m.get("params") or {}).items()) or "无"
                    dep = ""
                    reqs = m.get("requires") or []
                    if reqs:
                        dep = "；前置依赖：" + "、".join(
                            f"{r.get('param', '')}←{r.get('from', '')}"
                            for r in reqs if isinstance(r, dict))
                    lines.append(f"- {m.get('name')}：{m.get('desc', '')}"
                                 f"（需登录：{'是' if m.get('need_login') else '否'}，参数：{params}{dep}）")
                if i < len(scored[:3]):
                    lines.append("")
            return {"ok": True, "method": "keyword", "query": query,
                    "candidates": candidates,
                    "note": "\n".join(lines) if lines else f"关键词「{q}」未命中名下任何才艺/方法"}
        # 默认向量：小纸条（含 top-3 平台 + 各自方法完整信息）
        note = self._make_note(q)
        if not note:
            return {"ok": True, "method": "vector", "query": query,
                    "candidates": [], "top_skill": "",
                    "note": f"未找到与「{q}」相关的名下才艺，请换个说法或确认才艺范围"}
        plats = note.get("platforms") or []
        top_score = plats[0].get("score", 0) if plats else 0
        if top_score < _MIN_VECTOR_SCORE:
            # 相似度过低 → 乱码/无关话，不硬塞候选（待定 2 已落地）
            return {"ok": True, "method": "vector", "query": query,
                    "candidates": [], "top_skill": "",
                    "note": (f"「{q}」与名下才艺的相关度不足"
                             f"（最高 {top_score:.2f} < {_MIN_VECTOR_SCORE:.2f}），"
                             f"未找到合适才艺。可直接说明要办的平台/事，或换个说法再试。")}
        if note.get("top_skill"):
            self.current_skill = note["top_skill"]
        return {"ok": True, "method": "vector", "query": query,
                "candidates": plats,
                "note": note.get("note") or "",
                "top_skill": note.get("top_skill") or ""}

    def _read_skill(self, skill: str) -> dict:
        """read_skill：读某 skill 的契约全文（流程/方法/参数/登录/边界）。

        仅限名下白名单才艺；返回人读文本，供 AI 精读、诊断与流程咨询。
        数据源 = contract.json（get_contract），不是空壳。
        """
        sid = str(skill or "").strip()
        if not sid:
            return {"ok": False, "skill": sid, "error": "缺少才艺 id（skill）"}
        if self.allowed_skills and sid not in self.allowed_skills:
            return {"ok": False, "skill": sid,
                    "error": f"当前帮手不会「{sid}」，名下才艺：{', '.join(self.allowed_skills)}"}
        self.current_skill = sid
        from ..adapters.registry import get_contract
        c = get_contract(sid, self.person_id)
        if not c:
            return {"ok": False, "skill": sid, "error": f"找不到才艺「{sid}」的契约，无法精读"}
        lines = [f"【{c.get('name', sid)}】（skill={sid}）"]
        if c.get("category"):
            lines.append(f"分类：{c['category']}")
        if c.get("intro"):
            lines.append(f"一句话：{c['intro']}")
        if c.get("capability_note"):
            lines.append(f"能力说明：{c['capability_note']}")
        auth = c.get("auth") or {}
        lines.append(f"登录要求：{'是' if auth.get('required') else '否'}（方式：{auth.get('kind', '无')}）")
        if c.get("login"):
            lines.append("登录流程：" + json.dumps(c["login"], ensure_ascii=False))
        if c.get("payment"):
            lines.append("支付方式：" + json.dumps(c["payment"], ensure_ascii=False))
        if c.get("methods"):
            lines.append("")
            lines.append("【方法明细】")
            for m in c["methods"]:
                mname = m.get("name") or ""
                lines.append(f"- {mname}：{m.get('desc', '')}（需登录：{'是' if m.get('need_login') else '否'}）")
                params = m.get("params") or {}
                if params:
                    lines.append(f"   参数：{', '.join(f'{k}={v}' for k, v in params.items())}")
                ci = m.get("customer_input") or []
                if ci:
                    lines.append(f"   要问客户：{'、'.join(str(x) for x in ci)}")
                for r in (m.get("requires") or []):
                    if isinstance(r, dict):
                        note = f"（{r.get('note')}）" if r.get("note") else ""
                        lines.append(f"   前置依赖：{r.get('param', '')}←{r.get('from', '')}{note}")
                kws = m.get("keywords") or []
                if kws:
                    lines.append(f"   触发词：{'、'.join(str(k) for k in kws)}")
        if c.get("human_touch"):
            lines.append("")
            lines.append("【需要真人配合】" + "；".join(str(x) for x in c["human_touch"]))
        if c.get("not_deliver"):
            lines.append("")
            lines.append("【不能做的（边界）】" + "；".join(str(x) for x in c["not_deliver"]))
        form_txt = self._form_render(sid, c.get("form"))
        if form_txt:
            lines.append("")
            lines.append(form_txt)
        return {"ok": True, "skill": sid, "name": c.get("name", sid),
                "contract": "\n".join(lines)}

    def _form_schema(self, skill: str) -> list[dict]:
        from .form_state import parse_schema
        try:
            from ..adapters.registry import get_adapter, get_contract
            cfg = get_adapter(skill, self.person_id) or {}
            form = cfg.get("form")
            if not form:
                c = get_contract(skill, self.person_id) or {}
                form = c.get("form")
            return parse_schema(form)
        except Exception:
            return []

    def _form_all(self) -> dict:
        getter = self.form_fn.get("get") if isinstance(self.form_fn, dict) else None
        if getter:
            try:
                data = getter() or {}
                return dict(data) if isinstance(data, dict) else {}
            except Exception:
                return {}
        return dict(self._form_mem)

    def _form_save_all(self, data: dict) -> None:
        setter = self.form_fn.get("set") if isinstance(self.form_fn, dict) else None
        if setter:
            try:
                setter(data or {})
                return
            except Exception as e:
                logger.warning("表单状态保存失败: %s", e)
        self._form_mem = dict(data or {})

    def _form_values(self, skill: str) -> dict:
        blob = (self._form_all().get(skill) or {})
        return dict(blob) if isinstance(blob, dict) else {}

    def _form_set_values(self, skill: str, values: dict) -> None:
        all_f = self._form_all()
        all_f[skill] = dict(values or {})
        self._form_save_all(all_f)

    def _form_render(self, skill: str, form) -> str:
        from .form_state import parse_schema, render_for_ai
        schema = parse_schema(form) if form else self._form_schema(skill)
        if not schema:
            return ""
        return render_for_ai(schema, self._form_values(skill))

    def _store_form_answer(self, question: str, answer: str) -> None:
        from .form_state import match_answer
        skill = str(self.current_skill or "")
        if not skill:
            return
        schema = self._form_schema(skill)
        if not schema:
            return
        values = self._form_values(skill)
        hit = match_answer(schema, values, question, answer)
        if not hit:
            return
        field, val = hit
        values[field] = val
        self._form_set_values(skill, values)

    async def _apply_form(self, skill: str, params: dict) -> dict:
        """把会话表单状态补进本次参数，并尝试自动补 auto 字段。"""
        from .form_state import collect_from_params, filled, merge_into_params
        schema = self._form_schema(skill)
        if not schema:
            return params
        values = self._form_values(skill)
        params = merge_into_params(schema, values, params)
        params, values = await self._fill_form_auto(skill, schema, params, values)
        values = collect_from_params(schema, values, params)
        self._form_set_values(skill, values)
        return params

    async def _fill_form_auto(self, skill: str, schema: list, params: dict,
                              values: dict) -> tuple[dict, dict]:
        """source=auto 且还空：调 from 方法，按字段名从返回里取值。"""
        from .form_state import filled
        params = dict(params or {})
        values = dict(values or {})
        try:
            from ..adapters.registry import get_adapter
            cfg = get_adapter(skill, self.person_id) or {}
            methods = cfg.get("methods") or {}
        except Exception:
            return params, values
        for item in schema:
            if item.get("source") != "auto":
                continue
            f = item["field"]
            if filled(params.get(f)):
                values[f] = params[f]
                continue
            if filled(values.get(f)):
                params[f] = values[f]
                continue
            from_m = item.get("from") or ""
            if not from_m:
                continue
            src_minfo = methods.get(from_m) or {}
            allowed = set((src_minfo.get("params") or {}).keys())
            blob = {**values, **params}
            src_params = {k: v for k, v in blob.items() if k in allowed and filled(v)}
            try:
                src_params = await self._fill_requires(skill, from_m, src_params)
                src = await adapters.run(skill, from_m, src_params,
                                         device_id=self.device_id,
                                         owner_id=self.person_id)
            except Exception as e:
                logger.warning("form auto 调 %s.%s 失败: %s", skill, from_m, e)
                continue
            if not (isinstance(src, dict) and src.get("ok")):
                continue
            val = self._pick_field(src.get("data"), f)
            if filled(val):
                params[f] = val
                values[f] = val
                logger.info("[form] %s 自动补 %s", skill, f)
        return params, values

    def _method_info(self, skill: str, method: str) -> dict:
        try:
            from ..adapters.registry import get_adapter
            cfg = get_adapter(skill, self.person_id) or {}
            return (cfg.get("methods") or {}).get(method) or {}
        except Exception:
            return {}

    def _normalize_date_params(self, skill: str, method: str, params: dict) -> dict:
        """methods[].params.type=date → YYYY-MM-DD。"""
        params = dict(params or {})
        minfo = self._method_info(skill, method)
        pdef = minfo.get("params") or {}
        date_keys = []
        for k, v in pdef.items():
            if isinstance(v, dict) and v.get("type") == "date":
                date_keys.append(k)
        if not date_keys:
            return params
        try:
            from . import date_utils
            for k in date_keys:
                raw = params.get(k)
                if raw in (None, ""):
                    continue
                resolved = date_utils.resolve_dates(str(raw))
                if isinstance(resolved, dict):
                    dates = resolved.get("dates") or []
                    if dates:
                        params[k] = dates[0]
                    elif resolved.get("today") and str(raw) in ("今天", "今日"):
                        params[k] = resolved["today"]
                elif isinstance(resolved, str) and resolved:
                    params[k] = resolved
        except Exception as e:
            logger.debug("date normalize skip: %s", e)
        return params

    async def _confirm_if_needed(self, skill: str, method: str) -> bool:
        """methods[].confirm=true → 执行前请用户确认。"""
        minfo = self._method_info(skill, method)
        if not minfo.get("confirm"):
            return True
        desc = minfo.get("desc") or method
        ans = (await self._ask(
            f"即将执行「{desc}」（{skill}.{method}）。确认继续请回复「确认」，取消请回复「取消」。"
        )).strip()
        # 否定词优先排除：避免「不好/不是/不要/算了」被「好/是」子串误判为确认（真操作确认不得绕过）
        neg = any(x in ans for x in ("不", "否", "取消", "别", "算了"))
        pos = any(ans.startswith(x) for x in ("确认", "确定", "是", "好", "继续", "可以"))
        ok = pos and not neg
        if not ok:
            logger.info("用户未确认，取消 %s.%s ans=%s", skill, method, ans[:80])
        return ok

    async def _deliver_payment(self, skill: str, method: str, result: dict) -> dict:
        """按返回内容交付 pay_url 或 scheme（不做 deliver/source 拦截）。

        铁律：主代理不替 skill 决定「该不该交付」——skill 返回的 data 里带有
        pay_url（https 链接）或 scheme（拉起协议）就直接交付（弹出/拉起 + 留链接）。
        """
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        try:
            from ..adapters.registry import get_adapter
            payment = (get_adapter(skill, self.person_id) or {}).get("payment") or {}
        except Exception:
            payment = {}
        data = result.get("data")
        if not isinstance(data, dict):
            return result
        blob = dict(data)
        if isinstance(data.get("data"), dict):
            blob = {**data, **data["data"]}

        kind = str(payment.get("kind") or "")
        field = str(payment.get("field") or "")
        # 按返回内容识别支付产物：field 声明优先，否则看 data 里的 pay_url / scheme
        val = str(blob.get(field) or blob.get("pay_url") or blob.get("scheme") or "").strip()
        if not val:
            return result
        if not kind:
            kind = ("pay_url" if val.startswith("http://") or val.startswith("https://")
                    else "scheme")

        if kind == "pay_url" and self.device_id:
            # 支付不进内置浏览器遥控：用系统浏览器打开（App 内零收款，第 5 条）
            # 同时交付：直接弹出 + 结果里保留链接文本，AI 可展示给客户（未弹出也能复制/稍后点）
            try:
                from ..channel.bridge import bridge
                await bridge.send_cmd(self.device_id, "open_external", {"url": val})
                result = dict(result)
                result["pay_url"] = val
                result["note"] = f"已为您打开支付页面：{val}（若未弹出，可复制此链接稍后支付）"
            except Exception as e:
                logger.warning("推送支付页面失败: %s", e)
                result = dict(result)
                result["pay_url"] = val
                result["note"] = f"支付页面打开失败，请复制链接在浏览器打开：{val}"
        elif kind == "scheme":
            result = dict(result)
            fb = payment.get("fallback_https")
            fb_url = str(blob.get(fb) or "") if fb else ""
            # 同时交付：拉起 App + 结果里保留 scheme 与备用 https 链接，供 AI 展示/客户稍后点
            result["scheme"] = val
            if fb_url:
                result["fallback_https"] = fb_url
            note = f"已为您拉起：{val}"
            if fb_url:
                note += f"（未拉起可复制备用链接：{fb_url}）"
            result["note"] = note
            if self.device_id:
                try:
                    from ..channel.bridge import bridge
                    open_url = fb_url if fb_url.startswith("http") else val
                    await bridge.send_cmd(self.device_id, "open_external", {"url": open_url})
                except Exception as e:
                    logger.warning("推送 scheme/备用链接失败: %s", e)
        return result

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
        # 源头结果缓存：同一次 skill_run 内，同一源头方法 + 相同参数只查一次接口
        _cache = getattr(self, "_fill_cache", None)
        if _cache is None:
            _cache = {}
            self._fill_cache = _cache
        try:
            from ..adapters.registry import get_adapter
            cfg = get_adapter(skill, self.person_id)
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
                # 循环保护：仅当源头方法自身也有 requires（可能引发 A→B→A）才拦截
                _src_minfo = (cfg.get("methods") or {}).get(from_m) or {}
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
                # 源头缓存：同一源头方法 + 相同参数 → 复用上次结果，不再重复查接口
                cache_key = (skill, from_m, self._freeze_params(src_params))
                if cache_key not in _cache:
                    _cache[cache_key] = await adapters.run(
                        skill, from_m, src_params,
                        device_id=self.device_id,
                        owner_id=self.person_id)
                src = _cache[cache_key]
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

    @staticmethod
    def _freeze_params(d: dict) -> tuple:
        """源头参数规范化快照（key 排序 + 值统一转 str），用作源头缓存 key。"""
        return tuple(sorted((str(k), str(v)) for k, v in (d or {}).items()))

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
                    val = self._pick_field(it, field)
                    if val not in (None, "", [], {}):
                        return val
                    # 容器 dict（如 {normal:[...], expert:[...]} 顶层）也会被递归匹配到，
                    # 但取不到字段 → 继续找下一条真实记录，不能直接 return None
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

    async def _ask(self, question: str, image: str | None = None,
                   options: list[str] | None = None) -> str:
        """问用户。image 为可选验证码图片（base64），options 为建议选项（App 点选按钮）。

        铁律（2026-08-16）：ask_user 通道缺失或异常 → 直接抛错暴露，不静默返回空串。
        """
        # 显式带图提问（login_flow 直接传图）时也清掉暂存验证码图，
        # 避免 get_graphical_captcha 残留的旧图被后续 LLM ask_user 误带
        if image is not None:
            self._pending_image = None
        if not self.ask_user_fn:
            raise RuntimeError("ask_user 通道未注入（无法向客户提问）")
        opts = [str(x) for x in (options or []) if str(x).strip()]
        try:
            if image:
                return str(await self.ask_user_fn(question, image, opts)).strip()
            return str(await self.ask_user_fn(question, options=opts)).strip()
        except Exception as e:
            logger.exception("ask_user 异常: %s", e)
            raise

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
            answer = (data.get("data", {}).get("answer") or "").strip()
            # 待定 3：博查没有综合 answer 时，给首条（最相关）网页摘要当直接结论，AI 不必只读链接
            top_summary = (pages[0].get("summary") or "") if pages else ""
            # 问题⑩：博查返回 JSON 却没解析到内容 → 明确"未找到"，禁止 AI 把空结果当成功编造
            if not pages and not answer:
                return {"ok": True, "query": query, "pages": [], "answer": "", "top_summary": "",
                        "note": f"未检索到与「{query}」相关的网页结果；请如实告知客户，不要编造或假装搜到"}
            return {"ok": True, "query": query, "pages": pages[:5],
                    "answer": answer[:500],
                    "top_summary": top_summary[:300],
                    "note": (answer[:300] or top_summary[:300])}
        except Exception as e:
            return {"ok": False, "error": f"搜索失败：{e}"}
