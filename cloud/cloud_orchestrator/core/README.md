# 对话大脑（core）

雇人之后怎么办事（点菜、补参、登录、付款）。

**调度**：LangGraph 原生 `StateGraph`（见 [`graph_native.py`](graph_native.py)）——整句拆槽、改字段、换事重开、点选、已付回程都在图里。  
**业务**：[`agent.py`](agent.py)（skill_run、补参、登录、付款）  
**入口**：[`master.py`](master.py)（submit / feed_answer → interrupt/resume）

架构说明：[plans/LangGraph原生架构改造说明.md](../../../plans/LangGraph原生架构改造说明.md)

总览：[cloud_orchestrator/README.md](../README.md)
