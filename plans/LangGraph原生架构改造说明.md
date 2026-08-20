# LangGraph 原生架构改造说明

> 日期：2026-08-20  
> 状态：已落地（本地）  
> 取代：外挂 `DialogueOrchestrator` + `asyncio.Future` 等人机制  
> 以当前 `cloud/cloud_orchestrator/core/graph_native.py` 为准。下文若写 InMemorySaver / `_direct_ask` / 双通道，均已作废。

---

## 1. 做了什么（一句话）

**办事状态机全部收进 LangGraph `StateGraph`**：`phase` / `forms` / `SkillLock` / `pending_ask` 在 `AgentState` 里；`ask_user` 用官方 **`interrupt()` + `Command(resume=)`**；用户回答走 `feed_answer` → `feed_graph_resume`。

---

## 2. 架构对比

### 改造前（已拆除）

```
用户消息 → master.submit
              ↓
         DialogueOrchestrator（图外 Python 模块）
              ↓
         Future + _answer_waiter 等人
              ↓
         薄 ReAct 图（只有 model/tools/correction）
```

### 改造后（当前）

```
用户消息 → master.submit → run_agent_graph
              ↓
    LangGraph StateGraph + InMemorySaver（thread_id = conversation_id）
              ↓
    route → model → tools → model …
              ↓
    ask_user → wait_ask → interrupt() 暂停
              ↓
    feed_answer → Command(resume=回答) → resolve_reply（零 LLM）→ model
```

---

## 3. 文件清单

| 文件 | 角色 |
|---|---|
| [`graph_state.py`](../cloud/cloud_orchestrator/core/graph_state.py) | `AgentState`：messages + phase + forms + locked_skill + pending_ask |
| [`graph_native.py`](../cloud/cloud_orchestrator/core/graph_native.py) | StateGraph 编译、节点实现、interrupt 循环 |
| [`graph_tools.py`](../cloud/cloud_orchestrator/core/graph_tools.py) | 工具 schema；`phase=chat` 时仅 search/done |
| [`graph_engine.py`](../cloud/cloud_orchestrator/core/graph_engine.py) | 薄入口，导出 `run_agent_graph` / `feed_graph_resume` |
| [`master.py`](../cloud/cloud_orchestrator/core/master.py) | `feed_answer` → resume；`graph_hooks` 桥接 App/WS |
| [`dialogue/`](../cloud/cloud_orchestrator/core/dialogue/) | **纯函数**（非外挂编排器）：resolve_reply / route_entry / skill_lock / answer_check |

### 已删除（历史残留，勿恢复）

| 文件 | 原作用 |
|---|---|
| `dialogue/orchestrator.py` | 外挂 DialogueOrchestrator |
| `dialogue/state.py` | 外挂 DialogueState 落盘 |
| `dialogue/config.py` | GUARD_* 开关 |

---

## 4. 图节点说明

| 节点 | 是否调 LLM | 作用 |
|---|---|---|
| `route` | 否 | chat/task 路由 + SkillLock（强实体词） |
| `model` | 是 | ReAct 主循环 |
| `tools` | 否 | skill_run/search/done；ask_user → 推送 App 后 goto wait_ask |
| `wait_ask` | 否 | `interrupt()` 等人 → `resolve_reply` → SET_SLOT/REASK/ABANDON |
| `correction` | 否 | 文字反问统一闸打回 |

---

## 5. 数据流

### 5.1 新用户消息

1. `master.submit` 写会话 messages  
2. `Agent.handle` → `run_agent_graph`  
3. 图从 `route` 开始，checkpointer 按 `thread_id=conversation_id` 恢复 forms/locked_skill  

### 5.2 ask_user 等人

1. 模型调 `ask_user` → `tools` 节点推送 App（`graph_hooks.push_ask`）  
2. `wait_ask` 节点 `interrupt({ask_id, question, …})` → 图返回 `__interrupt__`  
3. `master` 设 `TaskState.status=waiting_user`，推 `task_update`  
4. 用户回答 → HTTP/WS → `feed_answer` → `feed_graph_resume(email, value)`  
5. `Command(resume=value)` → `wait_ask` 重跑 → `resolve_reply` → 写 `state.forms` → 回 `model`  

### 5.3 skill_run 内「确认继续」（例外路径）

`methods[].confirm=true` 时 `_confirm_if_needed` 在 **tools 节点执行过程中**同步问用户，不能嵌套 `interrupt`。  
使用 `master._make_graph_hooks.push_ask` + LangGraph `interrupt()`（含 confirm / 登录验证码）；`feed_answer` **仅** `feed_graph_resume`。

---

## 6. 四类 FAIL 对应机制

| 用例 | 机制 |
|---|---|
| 「算了不买了」 | `wait_ask` → resolve_reply → ABANDON |
| 「今天几点了」 | REASK / OFF_TOPIC_CHAT，不写 form |
| 「东京热不热」 | `phase=chat`，工具面无 ask_user |
| 「鼓楼」→ 拒浦口 | `route` 节点 SkillLock + skill_run 闸门 |

---

## 7. 已知限制 / 后续

| 项 | 说明 |
|---|---|
| Checkpointer | **SqliteSaver**（`data/checkpoints.db`）；forms/steps/phase 权威在 checkpoint |
| `conversations.dialogue` / `get_steps` / `get_forms` | **已废弃**为执行态来源；仅聊天展示仍写 messages |
| 步数上限 | 图递归超限时的「要继续吗」续跑逻辑尚未迁入 |
| 部署 | 需整包部署 `core/graph_*.py` + `master.py` + `agent.py` + `dialogue/` |

---

## 8. 自测

```bash
python tools/_test_dialogue.py      # resolve_reply / SkillLock / route
python tools/_test_ask_guard.py     # 文字反问判定
# 云端集成
PYTHONPATH=cloud python tools/selftest_gate_scenarios.py
```

---

## 9. 历史文档需知

以下文档描述**旧架构**，阅读时以本文为准：

- `plans/随心所欲不偏离轨道-架构规划.md` §6–9 中的「DialogueOrchestrator / PR-0~6 外挂模块」→ 已改为 LangGraph 原生
- `plans/文字反问导致任务卡住-方案决策稿.md` §5.2「graph_engine 收尾硬闸」→ 现为 `correction` 节点
- `plans/问题汇总` 中 `_answer_waiter` / Future 描述 → 已改为 interrupt/resume

---

## 10. LangGraph 能力地图：已用 / 可用 / 业务还缺什么

> 你的架构**本质确实应该依托 LangGraph**——但当前只用了底座约 **30% 能力**；下面按「已用上 → 值得用 → 暂不需要」分层，便于排期。

### 10.1 你现在用了什么（✅ 已落地）

| LangGraph 能力 | 你们代码里的位置 | 业务价值 |
|---|---|---|
| **StateGraph 自定义图** | `graph_native.py` route/model/tools/wait_ask/correction | 办事状态机主干 |
| **AgentState 扩展** | `graph_state.py`（phase/forms/SkillLock/pending_ask） | 引擎管状态，不靠 LLM 猜 |
| **MessagesState + add_messages** | 继承 `MessagesState` | 多轮 messages 累积 |
| **conditional_edges** | `_after_model` → tools/correction/END | 文字反问闸、工具分支 |
| **Command(goto=...)** | ask_user → `goto wait_ask` | 确定性跳转，不等 LLM |
| **interrupt() + Command(resume=)** | `wait_ask` + `feed_graph_resume` | ask_user 等人（主路径） |
| **Checkpointer（内存）** | `InMemorySaver` + `thread_id=conv_id` | 同会话内 forms/lock 跨步恢复 |
| **get_state** | `run_agent_graph` 开头读 checkpoint | 恢复 forms/locked_skill |
| **recursion_limit** | config 里 `max_steps * 2` | 防图跑飞 |

### 10.2 还没用、但**强烈建议**接业务的能力（⭐ 优先级）

#### P0 — 不接会有真实线上风险

| 能力 | 解决什么业务问题 | 建议做法 |
|---|---|---|
| **持久化 Checkpointer**（`SqliteSaver` / `PostgresSaver`） | 现在 `InMemorySaver`：**进程重启** pending_ask / phase / forms 全丢；和「单 worker」绑定 | 换 `SqliteSaver(path=.../checkpoints.db)`，与 `conversations.json` 双写 forms 作兜底 |
| **submit 改为「续跑」而非「重开图」** | 现在每轮 `submit` 都 `ainvoke` 全新 input（虽从 checkpoint 读 forms，但 **messages 从 conversations 重建**），和 LangGraph「thread 持续」模型不一致 | 有 checkpoint 时：`Command(update={messages:[+HumanMessage]})` 或 `update_state` 追加用户话再 invoke；history 以 **checkpoint messages 为权威** |
| **去掉 `_direct_ask` 双通道** | confirm 提问走 Future，和 interrupt 两套等人机制并存 → feed 路由复杂、易串 | 把 confirm 也做成图节点 `interrupt()`，或 `tools` 内 nested interrupt（LangGraph 支持同节点多 interrupt 按序 resume） |
| **步数超限续跑** | 旧 `run_react` 有「要继续吗」；新图没有 → 复杂订票中途 silently 结束 | 在 `_after_model` 捕 recursion 或 corrections 用尽 → `interrupt({kind:"continue?"})` + options 按钮 |

#### P1 — 明显提升体验/可维护性

| 能力 | 解决什么 | 建议 |
|---|---|---|
| **astream / stream_mode** | App 只能等整轮结束才 `task_update`；长 skill_run 像卡死 | `astream(..., stream_mode=["updates","messages"])` → WS 推「正在查票…」进度 |
| **ToolNode（prebuilt）** | 自写 `_node_tools` 只处理第一个 tool_call；扩展时要自己维护 | 保留 ask_user 特殊分支，其余 tool 交 `ToolNode`；或 `@tool` + 统一 executor |
| **update_state / 时间旅行** | 无法「撤销上一步填错表单」、debug 困难 | 客服/开发用 `get_state_history()` 看每步 state；必要时回滚 forms |
| **steps 进 AgentState** | `steps` 还在 `conversations.json` + `TaskState`，和图状态**两套** | `AgentState.steps` + reducer；`update_step` 只写 state，master 只读图 state 推 App |
| **phase 用 conditional_edges 硬分图** | 现在 phase 只在 `build_tools` 动态删工具，模型仍「看到」过 chat 上下文 | chat 相位：`route → chat_model → END`（子图），task 相位：完整 ReAct 子图 |
| **LangSmith / tracing** | 线上「为什么问了浦口」无法回放 | 配置 `LANGCHAIN_TRACING_V2`；按 thread_id 查完整图执行 |

#### P2 — 中长期架构演进

| 能力 | 场景 | 说明 |
|---|---|---|
| **Subgraph 按 skill** | 途牛 / 挂号 / 外卖 流程差异大 | 每个 skill 一个子图（查票→选人→下单），主图只负责路由+SkillLock |
| **Store（长期记忆）** | 「上次帮你订过南京→上海」 | LangGraph Store API 存用户偏好，不等于 conversations messages |
| **Send / map-reduce** | 同时查 3 天票价再比价 | 多 `skill_run` 并行后汇总节点（零 LLM） |
| **RetryPolicy** | 途牛接口偶发超时 | 在 tool 节点对 `skill_run` 自动重试 1 次 |
| **Dynamic breakpoint** | 运营/debug 暂停在某节点 | 开发环境用，生产一般不需要 |

### 10.3 可以**不必**用的（避免过度设计）

| 能力 | 为什么现在不必 |
|---|---|
| `create_react_agent` 预制 | 你们已有 correction/wait_ask/route，预制体改起来更痛苦 |
| 多 Agent 套娃 | 规划已拍板：单 Agent + 引擎状态机 |
| 并行 tool_calls | 办事流程有顺序依赖（先 read_skill 再 skill_run），已 `parallel_tool_calls=False` |
| Postgres 分布式 checkpointer | 单 worker 阶段 Sqlite 足够 |
| LangGraph Platform Cloud | 自托管 FastAPI + 手机 WS 已成型 |

### 10.4 当前架构的「本质缺口」（一句话）

```
LangGraph 负责「一轮任务内的状态机」✅ 基本成立
LangGraph 还没负责「跨轮会话 continuity + 持久化 + 唯一等人机制」❌ 仍是 master + conversations.json 在外补
```

具体表现：

1. **双状态机**：`TaskState`（master 内存）和 `AgentState`（checkpoint）各管一半  
2. **双等人**：`interrupt/resume`（ask_user）+ `_direct_waiters`（confirm）  
3. **双历史**：checkpoint messages vs `conversations.json` messages  
4. **checkpoint 不持久**：重启后图 amnesia，只靠 JSON 补 forms  

**理想终态**：`thread_id = conversation_id` 一条线贯穿；用户每句话 = 对同一 thread 的 `invoke/resume`；App 的 waiting_user/done 从 `get_state()` 读；forms/steps/phase 只在 AgentState。

### 10.5 建议实施顺序（依托 LangGraph，不再外挂）

| 阶段 | 内容 | 工作量 |
|---|---|---|
| **LG-1** | SqliteSaver + submit 改续跑（messages 以 checkpoint 为准） | 1～2 天 |
| **LG-2** | confirm 并入 interrupt，删 `_direct_ask` | 0.5～1 天 |
| **LG-3** | steps 迁入 AgentState；master 只镜像推 App | 0.5 天 |
| **LG-4** | astream 推 WS 进度（skill_run 长任务） | 1 天 |
| **LG-5** | chat/task 拆 subgraph | 1～2 天 |
| **LG-6** | LangSmith  trace + get_state_history 调试 | 0.5 天 |

### 10.6 和业务模块的对应关系

| 你的业务模块 | 应在 LangGraph 哪一层 | 现在在哪 |
|---|---|---|
| 闲聊 vs 办事路由 | `route` 节点 | ✅ 图内 |
| SkillLock（鼓楼） | `route` + state | ✅ 图内 |
| ask_user 等人 | `wait_ask` interrupt | ✅ 图内 |
| 答非所问/放弃 | `wait_ask` resolve_reply | ✅ 图内 |
| 文字反问闸 | `correction` 节点 | ✅ 图内 |
| 契约 form 写入 | `wait_ask` SET_SLOT → state.forms | ✅ 图内 |
| skill_run / 登录 / 支付 | `tools` → agent._run_tool | ✅ 图内（业务在 agent） |
| confirm 确认 | 应在 interrupt | ❌ `_direct_ask` |
| 执行进度 steps | 应在 state | ❌ conversations.json |
| 会话聊天历史展示 | 应与 checkpoint messages 统一 | ❌ conversations.json 另存 |
| App task 卡片 | 应从 get_state 派生 | ❌ master TaskState |
| 跨重启恢复 | 应靠持久 checkpointer | ❌ 仅 forms JSON |

---

*§10 追加 · 2026-08-20*

