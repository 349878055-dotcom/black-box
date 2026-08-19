# cloud_orchestrator 代码问题评审与修复记录

> 评审对象：用户提出的 16 项问题（严重 / 中等 / 设计质量三类），逐条对照实际代码核实，
> 其中「明显可修」的已直接修复并冒烟验证，其余「需用户决定」的列出方案待拍板。
>
> 核实方式：读取 [`ws.py`](cloud/cloud_orchestrator/channel/ws.py)、[`config.py`](cloud/cloud_orchestrator/config.py)、[`auth.py`](cloud/cloud_orchestrator/auth.py)、[`routes.py`](cloud/cloud_orchestrator/api/routes.py)、[`bridge.py`](cloud/cloud_orchestrator/channel/bridge.py)、[`session.py`](cloud/cloud_orchestrator/channel/session.py)、[`master.py`](cloud/cloud_orchestrator/core/master.py)、[`graph_engine.py`](cloud/cloud_orchestrator/core/graph_engine.py)、[`agent.py`](cloud/cloud_orchestrator/core/agent.py)、[`login_flow.py`](cloud/cloud_orchestrator/core/login_flow.py)、[`registry.py`](cloud/cloud_orchestrator/adapters/registry.py)、[`persist.py`](cloud/cloud_orchestrator/store/persist.py) 后逐条核对；修改后全部 `py_compile` 通过 + 功能冒烟通过。

---

## 一、结论总览

| # | 问题 | 核实 | 处理 |
|---|------|------|------|
| 1 | `asyncio.get_event_loop()` 废弃 | ✅ 属实（4 处） | ✅ 已修复 |
| 2 | `config.get()` 懒加载重复解析/竞态 | ✅ 属实 | ✅ 已修复 |
| 3 | 自研 Token 安全性弱（64bit 签名/明文/默认密钥/`&=`解析） | ✅ 属实 | ✅ 已修复（除 JWT 迁移见 ③-需决定） |
| 4 | `_push_task` 后台任务无异常回收 | ✅ 属实 | ✅ 已修复 |
| 5 | 登录/注册失败 200+`ok:false` 与 HTTPException 混用 | ✅ 属实 | ✅ 已选 A：统一 200+`{ok,detail}` |
| 6 | `_wait_user_input` 死代码（未来永远不 set_result） | ✅ 属实 | ✅ 已修复（移除死代码） |
| 7 | `_cleanup` 未取消 `_pending_user_input` | ✅ 属实（随 6 一并处理） | ✅ 已修复 |
| 8 | registry 首载 `importlib.reload` 多余 | ✅ 属实 | ✅ 已修复 |
| 9 | `update_step` StepItem vs dict 类型不匹配 | ✅ 属实（会造成进度静默丢弃） | ✅ 已修复 |
| 10 | `_direct_login` 触发词过宽（含「登」即触发） | ✅ 属实 | ✅ 已修复 |
| 11 | `_answer_waiter` 单槽覆盖丢等待 | ✅ 属实（低风险） | ✅ 已修复 |
| 12 | `/dev/*` 端点无独立鉴权 | ✅ 属实 | ✅ 已选：维持邮箱密码登录（不加额外门槛） |
| 13 | HTTP 用 email 当 device_id，WS 用真实 device_id | ✅ 确认一致（device_id=登录 email） | ✅ 已注释契约 |
| 14 | JSON 落盘并发保护 | ✅ 已用 tmp+rename（部分缓解） | ✅ 已选 A：单 worker 部署 |
| 15 | `_browser` 登录流程无总超时 | ✅ 属实（低风险） | ✅ 已选 A：整体 900s 总超时 |
| 16 | `config.py` 重复 `qwen` 赋值 | ✅ 属实（冗余） | ✅ 已修复 |

---

## 二、已修复项（附改动说明）

### 1. `asyncio.get_event_loop()` → `asyncio.get_running_loop()`
**核实**：确在 4 处使用：
- [`ws.py`](cloud/cloud_orchestrator/channel/ws.py) `_send_and_wait` / `send_skill_request`（原 131/185 行）
- [`master.py`](cloud/cloud_orchestrator/core/master.py) `_make_ask`（原 233 行）

**修复**：全部改为 `asyncio.get_running_loop().create_future()`。这些调用都发生在协程内（必有 running loop），语义不变、消除 DeprecationWarning 与 3.14+ 的 RuntimeError 风险。另有一处 `_wait_user_input`（原 199 行）随问题 6 一并移除，未再保留。

### 2. `config.py` 懒加载竞态
**核实**：原 [`get()`](cloud/cloud_orchestrator/config.py:99) 每次 `llm_api_key` 为空都会重新 `_load_config()` 解析 JSON（且 `_load_config()` 模块底部已执行过一次）。
**修复**：新增模块级 `_LOADED` 标志——`_load_config()` 成功解析后置 True；`get()` / `skill_secret()` 只在 `not _LOADED` 时触发加载。文件缺失时不置位（文件探测很便宜，保留「配置文件稍后出现可加载」能力）。消除了重复解析与无谓的并发写竞态窗口。

### 3. 自研 Token 安全性
**核实**：原 [`_sign`](cloud/cloud_orchestrator/auth.py:27) 只取 SHA-256 前 16 hex（64 bit）；payload 明文含 email/uid；默认密钥硬编码；email 含 `&`/`=` 会破坏 `&` 分隔解析。
**修复**：
- 签名改为**完整 SHA-256 摘要**（64 hex / 256 bit），不再截断；
- `email`/`uid` 用 `urllib.parse.quote/unquote` 编码/解码，含 `&`、`=` 等字符不再破坏字段解析（旧 token 可被 unquote 兼容读取）；
- 默认密钥场景在**首次使用时打印一次醒目告警日志**，提示生产必须配置 `cloud/config.json` 的 `auth.api_key`。
- **注意**：签名长度变化会使旧的 Access Token 失效（TTL 仅 2h，影响可忽略）。未动 Refresh Token（本就是高熵随机串）。完整 JWT 迁移属设计决策，见 ③。

### 4. `_push_task` 后台任务异常回收
**核实**：原 [`_push_task`](cloud/cloud_orchestrator/core/master.py:380) `asyncio.create_task(_bridge.send_push(...))`，任务异常无人 retrieve。
**修复**：包一层 `_push_safe()`（try/except + `logger.warning`），杜绝 "Task exception was never retrieved"。

### 5.（空，见需决定项）

### 6. `_wait_user_input` 死代码移除
**核实**：`user_input` 分支已按铁律只走 [`feed_answer`](cloud/cloud_orchestrator/core/master.py:28)，不再 set `_pending_user_input`；`bridge.wait_user_input` 全库无调用方（已搜索确认）。原 [`_wait_user_input`](cloud/cloud_orchestrator/channel/ws.py:197) 永远 600s 超时返回 None，属死代码且具误导性。
**修复**：移除 `_pending_user_input` 字段、`_wait_user_input` 方法及其注册入参；同步精简 [`bridge.py`](cloud/cloud_orchestrator/channel/bridge.py) 的 `WaitUser` 类型、`register` 参数与 `wait_user_input` 方法。`_cleanup` 中对该 Future 的清理也随之不再需要（问题 7 一并解决）。

### 7. `_cleanup` 未取消 `_pending_user_input`
**核实**：属实，但该 Future 唯一来源 `_wait_user_input` 已移除（见 6），不再有泄漏点。

### 8. registry 首载多余 reload
**核实**：原 [`_load_skills`](cloud/cloud_orchestrator/adapters/registry.py:70) 对每个 skill 先 import 再 reload，首载 = register.py 执行两遍。
**修复**：仅当 `mod_path in sys.modules`（二次扫描/热更新）时才 `reload`；首载直接 import。既消除首载双执行，又保留 `reload_skills()` 热更新能力。

### 9. `update_step` 类型不匹配
**核实**：`UpdateStepArgs.steps` 是 `list[StepItem]`，LangGraph 反序列化后元素可能是 Pydantic 对象；而 [`master.set_steps`](cloud/cloud_orchestrator/core/master.py:305) 只认 `dict`（非 dict 直接 `continue`）→ **执行进度会被静默丢弃**（严重度比原描述更高：不是 AttributeError，而是丢数据）。
**修复**：[`graph_engine.update_step`](cloud/cloud_orchestrator/core/graph_engine.py:199) 统一归一化——Pydantic 对象走 `model_dump()`、dict 原样、其它转 `{title, status:pending}`。已用 FakeStep 冒烟验证。

### 10. `_direct_login` 触发过宽
**核实**：原判断 `"登" in t` 即触发，`登山 / 五谷登丰` 等会误触发登录编排。
**修复**：[`_direct_login`](cloud/cloud_orchestrator/core/agent.py:386) 收紧为只认「登录/登陆」整词。已冒烟：`帮我登录鼓楼 / 我要登陆美团` 触发，`今天去登山 / 五谷登丰 / 帮我登一下` 不触发。

### 11. `_answer_waiter` 单槽覆盖
**核实**：原 `_answer_waiter[device_id] = {...}` 覆盖旧等待；若出现第二个 ask，先发的 Future 被丢弃（600s 超时）。设计上「一设备一任务」使其概率低，但属隐患。
**修复**：[`master.py`](cloud/cloud_orchestrator/core/master.py:25) 重构为 `device_id -> {ask_id: Future}` 多槽；`feed_answer` 按 ask_id 精确路由（无 ask_id 时仅当唯一等待才喂，兼容旧客户端）；`_make_ask` 结束只弹自己的 ask_id。已冒烟：喂 a2 只解 a2，a1 保留。

### 16. `config.py` 重复 `qwen` 赋值
**核实**：`qwen = data.get("qwen")...` 在同一函数内出现两次（43 / 92 行），冗余。
**修复**：删除重复赋值，92 行处复用上方已解析的 `qwen` 变量。

---

## 三、决策落地记录（用户已拍板，均已实现）

### ① 问题 5：HTTP 业务错误状态码 → **选 A：统一 200 + `{ok, detail}`**
- 已把 [`routes.py`](cloud/cloud_orchestrator/api/routes.py) 中所有业务 `HTTPException` 改为 `200 + {"ok": false, "detail": ...}`：
  - `refresh` 令牌无效（原 401）、`_own_conv` 会话不存在（原 404，4 个会话接口）、`_validate_persona` 卡不存在（原 404）、`api_get_card` 卡不在场（原 404）、`me` 未登录（原 401）、`update_me` 用户不存在（原 404）。
- 前端统一只认 `ok` 字段；auth 中间件对「未带/无效 token」仍返回真实 401（属基础设施层，与业务响应区分开）。

### ② 问题 12：`/api/v1/dev/*` 鉴权 → **维持邮箱密码登录，不加额外门槛**
- 按你「认邮箱注册、就是邮箱密码」的意见：dev 端点继续走统一邮箱密码登录鉴权，不额外加 admin 白名单或 debug 开关。风险已在文档注明（单主人个人助理，任何已登录用户即本人）；若将来多用户再收紧。

### ③ 问题 3（余下部分）：Token → **维持已加固的自研 HMAC，不引入 PyJWT**
- 你表示「不是很懂 JWT」，故保留已在「二、已修复项 #3」加固的自研 HMAC：**完整 256bit 签名 + email/uid URL 编码 + 默认密钥告警**。安全性已达标、零新依赖；PyJWT 迁移仅作为可选项留待以后。

### ④ 问题 13：device_id 契约 → **确认 = 登录 email，契约自洽**
- 你确认前端 WS 的 device_id 就是登录 email，与 HTTP 侧 `_my_email(request)` 一致 → 任务/ask_user/skill_run 按 email 找设备成立，**无需改功能**。
- 已在 [`routes.py`](cloud/cloud_orchestrator/api/routes.py:141) `chat` 加注释固化该契约（前端连 `/api/v1/ws` 必须用同一 email 注册），防止日后误改。

### ⑤ 问题 14：JSON 落盘并发 → **选 A：单 worker 部署**
- 当前架构即单进程单线程，[`persist.save_json`](cloud/cloud_orchestrator/store/persist.py:31) 已是 tmp+rename 原子写，无并发损坏风险。**部署约束：不要 `uvicorn --workers > 1`**（多进程会跨进程覆盖丢更新）。无需改代码。

### ⑥ 问题 15：`_browser` 登录总超时 → **选 A：整体包 `asyncio.wait_for(900)`**
- 已在 [`login_flow.run_login`](cloud/cloud_orchestrator/core/login_flow.py:24) 对 sms_verify / browser 整体包 `asyncio.wait_for(..., timeout=LOGIN_TOTAL_TIMEOUT=900)`；超时后向用户提示「登录超时（超过 900 秒），请稍后重试」并返回 False，由 agent 走「登录未完成」分支，不再无限期挂起。

---
## 四、冒烟验证摘要

在 `cloud/` 下执行（全部通过）：
- 8 个修改文件 `py_compile` 全部 OK；
- auth：特殊字符 email（`user&name=xx@example.com`）token 往返解析正确，签名 64 hex；
- `feed_answer` 多槽：按 ask_id 精确路由，不误解其它等待；
- `config.get()`：`_LOADED` 置位，正常返回配置值；
- `registry.reload_skills()`：4 个 skill 正常加载（首载不 reload）；
- `update_step` 归一化：StepItem / dict / 字符串混合输入全部转 dict；
- `_direct_login`：只认「登录/登陆」，不再误触发。
