#!/usr/bin/env python3
"""本地诊断：完整跑一遍 hired ReAct，打印每一步消息（含 tool_call / tool 返回），
判断 LLM 到底有没有调用 search/skill_run/ask_user。"""
import asyncio
import json
import sys

sys.path.insert(0, "cloud")
sys.path.insert(0, "cloud/cloud_orchestrator")


async def main() -> None:
    from langchain_core.messages import AIMessage, HumanMessage

    from cloud_orchestrator.core.agent import Agent
    from cloud_orchestrator.core.graph_engine import build_tools, _chat_model
    from langgraph.prebuilt import create_react_agent

    # 用与云端一致的 agent 拼 system（hired=金涛，名下 4 才艺）
    # mock ask_user：脚本化回答（第 2 个 CLI 参数传，逗号分隔），可测「选完一项后是否继续走下一步」
    raw = sys.argv[2] if len(sys.argv) > 2 else "鼓楼医院,心血管内科,明天"
    answers = [x.strip() for x in raw.split(",") if x.strip()]
    counter = {"i": 0}

    async def mock_ask(q: str):
        i = counter["i"]
        counter["i"] += 1
        return answers[i] if i < len(answers) else ""

    agent = Agent(ask_user_fn=mock_ask)
    agent.person_id = "jintao"
    agent.hired = True
    agent.allowed_skills = ["glyy", "meituan_waimai", "tuniu", "njpkzyy"]
    system = agent._build_hired_system()

    msg = sys.argv[1] if len(sys.argv) > 1 else "帮我挂个号"
    print("=" * 60)
    print("SYSTEM PROMPT 前 400 字:")
    print(system[:400])
    print("=" * 60)
    print(f"用户消息: {msg}")

    model = _chat_model()
    tools = build_tools(agent, hired=True)
    graph = create_react_agent(model, tools, prompt=system)

    out = await graph.ainvoke(
        {"messages": [HumanMessage(content=msg)]},
        config={"recursion_limit": 28},
    )

    print("\n" + "=" * 60)
    print("完整对话/工具轨迹:")
    for m in out.get("messages", []):
        t = type(m).__name__
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                print(f"\n[模型] → 调工具 {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})")
        elif t == "ToolMessage":
            c = str(m.content)
            print(f"[工具] {m.name} 返回: {c[:300]}")
        elif isinstance(m, HumanMessage):
            print(f"\n[用户] {m.content[:200]}")
        elif isinstance(m, AIMessage):
            c = str(m.content)
            if c.strip():
                print(f"[AI回复] {c[:400]}")
        else:
            c = str(getattr(m, "content", ""))
            if c.strip():
                print(f"[{t}] {c[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
