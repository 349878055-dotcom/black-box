"""LangGraph 工具定义（按 phase 过滤工具面）。"""
from __future__ import annotations

import json
from typing import Any


def _clip(text: str, limit: int = 20000) -> str:
    if not text or len(text) <= limit:
        return text
    return text[:limit] + "…"


def _dump(result: Any) -> str:
    if isinstance(result, str):
        return _clip(result)
    try:
        return _clip(json.dumps(result, ensure_ascii=False))
    except Exception:
        return _clip(str(result))


def build_tools(runtime, hired: bool) -> list:
    """phase=chat → 仅 search/done；ask_user 由图节点 interrupt 处理，此处只提供 schema。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, ConfigDict, Field

    phase = str(getattr(runtime, "dialogue_phase", "task") or "task")
    chat_only = hired and phase == "chat"

    class AskArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        question: str = Field(description="向客户提出的问题（一次一个问题）")
        options: list[str] = Field(default_factory=list, description="可选按钮")

    class SearchArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        query: str = Field(description="搜索关键词")
        scope: str = Field(default="skill", description="skill 或 web")
        method: str = Field(default="vector", description="vector 或 keyword")

    class DoneArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        reply: str = Field(description="给客户的最终回复")

    class SkillRunArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        skill: str
        method: str
        params: dict = Field(default_factory=dict)

    class ReadSkillArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        skill: str

    class StepItem(BaseModel):
        model_config = ConfigDict(extra="forbid")
        step: int = 0
        title: str
        status: str = "pending"

    class UpdateStepArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")
        steps: list[StepItem]

    async def ask_user_stub(question: str, options: list[str] | None = None) -> str:
        return "{}"  # 实际执行在 graph_native._node_tools

    async def search(query: str, scope: str = "skill", method: str = "vector") -> str:
        return _dump(await runtime._run_tool("search", {"query": query, "scope": scope, "method": method}))

    async def done(reply: str) -> str:
        result = await runtime._run_tool("done", {"reply": reply})
        if isinstance(result, dict) and result.get("ok"):
            runtime._done_reply = reply
        return _dump(result)

    tools = [
        StructuredTool.from_function(coroutine=search, name="search", args_schema=SearchArgs,
            description="统一检索：skill=名下才艺，web=互联网。"),
        StructuredTool.from_function(coroutine=done, name="done", args_schema=DoneArgs,
            description="办完或说明失败后收尾。"),
    ]

    if chat_only:
        return tools

    tools.insert(0, StructuredTool.from_function(
        coroutine=ask_user_stub, name="ask_user", args_schema=AskArgs,
        description="向客户提问并等待回答（唯一信息采集通道）。"))

    if hired:
        async def skill_run(skill: str, method: str, params: dict | None = None) -> str:
            return _dump(await runtime._run_tool("skill_run",
                {"skill": skill, "method": method, "params": params or {}}))

        async def read_skill(skill: str) -> str:
            return _dump(await runtime._run_tool("read_skill", {"skill": skill}))

        async def update_step(steps: list) -> str:
            norm = [s.model_dump() if hasattr(s, "model_dump") else s for s in (steps or [])]
            return _dump(await runtime._run_tool("update_step", {"steps": norm}))

        tools[0:0] = [
            StructuredTool.from_function(coroutine=skill_run, name="skill_run", args_schema=SkillRunArgs,
                description="执行才艺方法。"),
            StructuredTool.from_function(coroutine=read_skill, name="read_skill", args_schema=ReadSkillArgs,
                description="读才艺契约。"),
            StructuredTool.from_function(coroutine=update_step, name="update_step", args_schema=UpdateStepArgs,
                description="维护执行进度。"),
        ]
    return tools
