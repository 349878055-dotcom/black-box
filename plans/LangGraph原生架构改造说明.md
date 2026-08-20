# LangGraph 原生架构改造说明

> 日期：2026-08-20  
> 状态：已落地  
> 源码：`cloud/cloud_orchestrator/core/graph_native.py`  
> Skill 接口：`plans/contract-v2-接口说明.md`

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
python tools/_test_dialogue.py      # resolve_reply / SkillLock / 整句拆槽 / ask_id
python tools/_test_ask_guard.py     # 文字反问判定
python tools/_test_done_guard.py    # done 收束不得带提问
```

---

## 9. 读代码入口

以本文 + 源码为准，不要再找外挂编排器 / `_answer_waiter` 文档：

- 图：`cloud/cloud_orchestrator/core/graph_native.py`
- 状态：`graph_state.py`
- 对话规则：`core/dialogue/`
- Skill 接口：`plans/contract-v2-接口说明.md`、`plans/contract-v2-内部实现.md`

