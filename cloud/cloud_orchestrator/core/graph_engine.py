"""
LangGraph 调度引擎 —— 只负责「模型何时调工具」，不写业务。

大脑仍是 cloud/config.json 里的 LLM（当前为 DeepSeek：api_key + base_url + model），
通过 langchain ChatOpenAI 兼容接口调用；LangGraph 不替代 DeepSeek。

业务（skill_run / 登录 / 补码 / 人设闸门）仍在 agent.Agent._run_tool。
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("xiami.graph_engine")


def _chat_model():
    """DeepSeek（或 config 里配置的 OpenAI 兼容模型）—— Agent 的大脑。"""
    from langchain_openai import ChatOpenAI
    from ..config import get

    api_key = get("llm_api_key") or ""
    base_url = (get("llm_base_url") or "https://api.deepseek.com/v1").rstrip("/")
    model = get("llm_model") or "deepseek-chat"
    if not api_key:
        raise RuntimeError("LLM API Key 未配置（cloud/config.json 的 deepseek.api_key）")
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.2,
        max_tokens=4096,
        # 顺序推进（办事流程依赖上一步结果 + ask_user 阻塞），禁止一次并行调多个工具
        parallel_tool_calls=False,
    )


def _clip_text(text: str, limit: int = 20000) -> str:
    """安全截断（问题⑨）：超长内容优先在完整句子/换行边界切，并标注「已截断」，
    避免 AI 看到被硬切的半截内容、误以为完整而瞎编。"""
    if not text or len(text) <= limit:
        return text
    head = text[:limit]
    # 取最后一个句子边界（中英文句号/叹号/问号/分号 或换行）
    idx = max(head.rfind("。"), head.rfind("！"), head.rfind("？"), head.rfind("；"),
              head.rfind("\n"), head.rfind("."), head.rfind(";"))
    if idx > limit * 0.5:  # 边界不能太靠前，否则信息丢失过多
        head = head[: idx + 1]
    return head + f"…（内容过长，已截断，仅显示前 {len(head)} 字符）"


def _dump(result: Any) -> str:
    if isinstance(result, str):
        return _clip_text(result)
    try:
        return _clip_text(json.dumps(result, ensure_ascii=False))
    except Exception:
        return _clip_text(str(result))


def build_tools(runtime, hired: bool) -> list:
    """把业务运行时的 _run_tool 挂成 LangGraph 可调工具。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, ConfigDict, Field

    tools = []
    # extra="forbid" → 生成的 schema 带 additionalProperties:false（Zoo 风格：封闭参数表）

    class AskArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        question: str = Field(description="向客户提出的问题（一次一个问题，需要多项就逐个调用本工具）")
        options: list[str] = Field(
            default_factory=list,
            description=(
                "建议选项（可空列表）。当问题是从候选里选（如选店/选科室/选日期）时，"
                "把候选填进来（2-4 个），App 渲染成可点按钮，客户点选即可、不用打字；"
                "开放式问题（如问手机号）不传。"
            ),
        )

    class SearchArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        query: str = Field(description="搜索关键词")
        scope: str = Field(default="skill", description="搜哪类：优先 skill=名下才艺/方法；只有名下确实没有或要外部公开信息时才用 web=外部互联网（博查）")
        method: str = Field(default="vector", description="搜法：vector=比意思（语义），keyword=找字面")

    class DoneArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        reply: str = Field(description="给客户的最终回复（办完/如实说明后收尾用）")

    class SkillRunArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        skill: str = Field(description="才艺标识，如 glyy / tuniu / meituan_waimai / njpkzyy")
        method: str = Field(description="方法名（以 read_skill 读到的契约为准）")
        params: dict = Field(default_factory=dict, description="方法参数（按契约填；内部编码由系统自动补）")

    class ReadSkillArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        skill: str = Field(description="才艺标识，如 glyy / tuniu")

    # 问题⑤：update_step 的步骤项用嵌套模型封死参数表（additionalProperties:false），
    # 与 ask_user / search / done 的封闭风格一致，不让 {name:...}/{complete:...} 这类脏键混进来。
    class StepItem(BaseModel):
        model_config = ConfigDict(extra="forbid")
        step: int = Field(
            default=0,
            description="步骤序号；系统按列表顺序自动从 1 递增编号（传 0 或省略均可）",
        )
        title: str = Field(description="步骤名")
        status: str = Field(
            default="pending",
            description="步骤状态：pending(待办)/doing(进行中)/done(已完成)；非法值后端统一归一为 pending",
        )

    class UpdateStepArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        steps: list[StepItem] = Field(
            description=(
                "当前任务的执行进度清单（全量写入），每项 {title: 步骤名, status: pending/doing/done}；"
                "step 可省略（系统自动编号）。客户要办的事需要分多步推进时（如多天比价、先查再订、多店对比、多事项代办等），"
                "用本工具记录进度，每办完一步更新 status=done；跨轮续办靠它记住查到哪。"
                "注意：已完成的步骤（done）会自动保留，不会因本次漏写而消失。"
            ),
        )

    async def ask_user(question: str, options: list[str] | None = None) -> str:
        opts = [str(x) for x in (options or []) if str(x).strip()]
        return _dump(await runtime._run_tool(
            "ask_user",
            {"question": question, "options": opts},
        ))

    async def search(query: str, scope: str = "skill", method: str = "vector") -> str:
        return _dump(await runtime._run_tool(
            "search",
            {"query": query, "scope": scope, "method": method},
        ))

    async def done(reply: str) -> str:
        # 标记结束；引擎跑完后从消息里取 reply
        runtime._done_reply = reply
        return _dump(await runtime._run_tool("done", {"reply": reply}))

    tools.extend([
        StructuredTool.from_function(
            coroutine=ask_user, name="ask_user",
            description=(
                "向客户提问并收集信息——收集客户信息的唯一通道。\n"
                "【什么时候用】先 read_skill 读契约，凡契约声明要『客户提供』（方法 customer_input 或 form 里 source=customer 且还没填的字段）"
                "且客户还没给的信息，用它问：把问题推送给客户（App）并等待回答，回答作为返回值返回；"
                "从候选里选（选店/选科室/选日期）时把候选填进 options 让客户点选。\n"
                "【什么时候不用】契约没标要客户提供 / 自动补（requires）/ 资料卡自动填的都不问；"
                "不要用普通文字反问代替本工具；一次问一件事，需要多项就逐个调用。\n"
                "【示例】ask_user(question='请问您想点哪家店？')"
            ),
            args_schema=AskArgs,
        ),
        StructuredTool.from_function(
            coroutine=search, name="search",
            description=(
                "统一检索工具：需要知道'能办哪些事/哪个方法能用/外部信息'时调用。\n"
                "【什么时候用】① 客户要办事但你不知用哪个才艺/方法；② 初判与客户意图不符、"
                "或客户提出异议（翻盘）；③ 需要外部资讯。\n"
                "【什么时候不用】客户已明确指定才艺（如直接说'去美团'）时，直接 skill_run，不要先 search。\n"
                "【scope】优先 skill=搜名下才艺/方法（返回 top-3 候选，每个带 name+methods）；"
                "只有名下才艺确实没有对应能力、或客户要的是外部公开信息（天气/新闻/政策/电话/价格等）时，"
                "才用 web=搜外部互联网（博查）。\n"
                "【method】vector=比意思（'挂个号'命中'预约'）；keyword=找字面。\n"
                "【返回结构】{ok, candidates:[{skill,name,methods}], note} 或网页列表。\n"
                "【失败处理】没找到相关才艺/网页时，如实告知'未找到相关结果'，禁止编造或假装搜到。"
            ),
            args_schema=SearchArgs,
        ),
        StructuredTool.from_function(
            coroutine=done, name="done",
            description=(
                "办理/回复完成后的收尾工具。\n"
                "【什么时候用】业务办完、或如实说明失败后，把最终结果给客户并结束本任务。\n"
                "【什么时候不用】信息没集齐、流程没办完时绝不调用（那是没完成就收尾）；还需要继续办理时也别 done。\n"
                "【参数】reply=给客户的最终回复文字。"
            ),
            args_schema=DoneArgs,
        ),
    ])

    if hired:
        # 问题⑩（2026-08-16 用户拍板，Roo CLI 哲学）：只留 search，去掉 skill_list。
        # skill_list 全列名下所有方法 = 反模式；用 search 按需拿 top-3 候选即可。
        async def skill_run(skill: str, method: str, params: dict | None = None) -> str:
            return _dump(await runtime._run_tool(
                "skill_run",
                {"skill": skill, "method": method, "params": params or {}},
            ))

        async def read_skill(skill: str) -> str:
            return _dump(await runtime._run_tool("read_skill", {"skill": skill}))

        async def update_step(steps: list) -> str:
            # LangGraph 按 args_schema(UpdateStepArgs) 反序列化后，steps 元素可能是
            # StepItem（Pydantic 模型）而非 dict；_run_tool / master.set_steps 只认 dict，
            # 不做归一化会把进度静默丢弃。这里统一转成 dict 再下发。
            norm: list[dict] = []
            for s in (steps or []):
                if hasattr(s, "model_dump"):
                    norm.append(s.model_dump())
                elif isinstance(s, dict):
                    norm.append(s)
                else:
                    norm.append({"title": str(s), "status": "pending"})
            return _dump(await runtime._run_tool("update_step", {"steps": norm}))

        tools[0:0] = [
            StructuredTool.from_function(
                coroutine=skill_run, name="skill_run",
                description=(
                    "执行才艺方法办理业务（返回结构化数据）——办理业务的唯一入口。\n"
                    "【什么时候用】客户要办事、定了才艺后，每办一步都用它：查科室/排班/搜店/下单/生成链接等，"
                    "都通过它调才艺方法拿真实结果。\n"
                    "【什么时候不用】方法参数没齐时不要硬调——先 ask_user 向客户收集缺的信息，再调本工具；"
                    "只是挑才艺/方法时用 search，不要用本工具。\n"
                    "【参数】skill=才艺 id；method=方法名（以 read_skill 契约为准）；params=按方法契约填参数，内部编码系统自动补。\n"
                    "【返回】{ok, skill, method, data}，data 为该方法的真实结果；失败时 ok=false + error。\n"
                    "【失败处理】失败看 error，必要时 read_skill 读契约诊断后重试/换参/换方法。\n"
                    "【示例】skill_run(skill='meituan_waimai', method='search_poi', params={'keyword':'汉堡'})"
                ),
                args_schema=SkillRunArgs,
            ),
            StructuredTool.from_function(
                coroutine=read_skill, name="read_skill",
                description=(
                    "读某个才艺的契约全文（方法/参数/登录/边界）——精读用，返回该才艺的契约内容。\n"
                    "【什么时候用】① 客户问办事能力/边界时，读契约准确回答、不编造；\n"
                    "② skill_run 失败或卡住时，读契约看方法参数/依赖/登录要求，诊断后决定重试、换参或换方法；\n"
                    "③ 需要确认某个方法的参数含义/前置依赖/触发词时。\n"
                    "【什么时候不用】只是挑平台/方法时用 search，不要用 read_skill（search 已带候选信息）。\n"
                    "【返回】该才艺契约关键内容：方法明细（desc/参数/requires/触发词）、"
                    "登录/支付方式、需要真人配合的事、不能做的事（边界）。"
                ),
                args_schema=ReadSkillArgs,
            ),
            StructuredTool.from_function(
                coroutine=update_step, name="update_step",
                description=(
                    "维护当前任务的执行进度清单（全量写入）——让客户看到办到哪一步、也让你跨轮续办记得住。\n"
                    "【什么时候用】客户要办的事需要分多步推进（如多天比价、先查再订、多店对比、多事项代办等）时建清单，"
                    "每办完一步更新 status=done。\n"
                    "【什么时候不用】单次查询/单次办理就能完成的不必建（如“帮我订3月1日的机票”）；纯咨询/闲聊不用。\n"
                    "【参数】steps=完整清单 [{title, status}]，status 取值 pending/doing/done；step 可省略（系统自动编号）。"
                    "全量写入，但已完成的步骤（done）会自动保留，不会因本次没带上而消失。\n"
                    "【示例】update_step(steps=[{step:1,title:'搜3/1机票',status:'done'},{step:2,title:'搜3/2机票',status:'doing'},{step:3,title:'比价汇总',status:'pending'}])"
                ),
                args_schema=UpdateStepArgs,
            ),
        ]

    return tools


async def run_react(
    *,
    runtime,
    system: str,
    user_content: str,
    history: list[dict] | None,
    hired: bool,
    max_steps: int = 14,
    _resume_depth: int = 0,
) -> str:
    """跑一轮 LangGraph ReAct；返回最终给用户的文本。"""
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.prebuilt import create_react_agent

    runtime._done_reply = None
    model = _chat_model()
    tools = build_tools(runtime, hired=hired)

    # 注入当前执行进度（update_todo_list 轻量版）：hired 时让模型知道"办到哪一步"
    if hired:
        try:
            getter = runtime.steps_fn.get if isinstance(runtime.steps_fn, dict) else None
            if getter:
                steps = getter()
                if steps:
                    lines = []
                    for s in steps:
                        st = str(s.get("status") or "pending")
                        mark = {"done": "✅", "doing": "▶️", "pending": "⬜"}.get(st, "•")
                        lines.append(f"- {mark} {s.get('step')}. {s.get('title')}（{st}）")
                    if lines:
                        system = f"{system}\n\n【当前执行进度】\n" + "\n".join(lines)
        except Exception as e:
            logger.warning("进度注入失败: %s", e)

    graph = create_react_agent(model, tools, prompt=system)

    messages: list = []
    for h in (history or [])[-8:]:
        role = h.get("role")
        content = str(h.get("content") or "")[:2000]
        if not content:
            continue
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=user_content))

    # recursion_limit：模型一步 + 工具一步约算 2，故 *2
    try:
        out = await graph.ainvoke(
            {"messages": messages},
            config={"recursion_limit": max(4, max_steps * 2)},
        )
    except Exception as e:
        # 防止递归步数上限触发后表现为“假死”
        msg = str(e or "")
        if "recursion" in msg.lower() or "graphrecursion" in msg.lower():
            # 用 ask_user（带 options）生成 App 按钮，而不是普通文本
            opts = ["继续", "取消"]
            try:
                choice = await runtime._ask(
                    "我已经尝试执行到最多步数仍未完成。要继续跑吗？",
                    options=opts,
                )
            except Exception:
                # ask_user 失败兜底：至少给明确提示
                return "我尝试继续办理时遇到限制，暂时没法继续。你可以再发一句消息让我重试。"

            choice_l = str(choice or "").strip()
            if (not choice_l) or ("取消" in choice_l):
                return "已取消继续办理。"

            # 允许最多续跑 1 次，避免无限循环
            if _resume_depth >= 1:
                return "已触发多次步数限制，还是没办完。请把关键目标再说一遍，我会换策略重试。"

            new_max_steps = min(max_steps * 2, 28)
            return await run_react(
                runtime=runtime,
                system=system,
                user_content=user_content,
                history=history,
                hired=hired,
                max_steps=new_max_steps,
                _resume_depth=_resume_depth + 1,
            )
        raise

    if getattr(runtime, "_done_reply", None):
        return str(runtime._done_reply)

    # 取最后一条有文本的 AI 回复
    for msg in reversed(out.get("messages") or []):
        if isinstance(msg, AIMessage):
            text = (msg.content or "").strip() if isinstance(msg.content, str) else ""
            if not text and isinstance(msg.content, list):
                parts = []
                for p in msg.content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        parts.append(str(p.get("text") or ""))
                    elif isinstance(p, str):
                        parts.append(p)
                text = "".join(parts).strip()
            # 跳过「纯 tool_calls、无正文」的中间步
            if text:
                return text
    return "（无回复）"
