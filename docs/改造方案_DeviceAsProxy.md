# 整体改造方案：云端大脑 + 手机手脚（Device-as-Proxy）

> 目标：把「云端直发平台（机房 IP，会被封锁）」改成「云端出蓝图、手机直连平台（真实 IP）」，同时满足 **iPhone 上架 App Store 不碰苹果红线**。
> 本文档是逐条改造的依据，用户按编号逐条提问，确认一条改一条。

---

## 0. 背景与现状（一句话）

**现状**：所有平台请求（glyy 鼓楼医院、tuniu 途牛）都由云端 `requests` 直发 → 平台看到的全是机房 IP + 云端持有登录态（glyy 在 `/tmp`、tuniu 在 `data/sessions/`）→ 一旦风控识别 IDC 段，整机房被封、账号被牵连。

**目标**：平台请求全部改从**用户手机**发出（真实 IP + 真实设备 + 用户自己的账号），云端只当「大脑」（决策 / 组参 / 解析），不再发任何平台请求。

---

## 1. 核心架构：怎么配合

```
用户说话
  ↓
云端（大脑）：LLM 理解 → 检索 skill → 生成「请求蓝图」(JSON) → WS 下发
  ↓ skill_request
手机 App（手脚）：内置执行引擎 → 取本地凭据库(token/cookies) → 手机真实 IP 直连平台
  ↓
平台（glyy / tuniu）：看到「这台手机 + 用户真实 IP + 用户自己的账号」 → 机房不被牵连
  ↓ 原始响应
手机 → WS 回传 skill_result
  ↓
云端：解析成结构化数据 → 汇报用户
```

**分工原则**
- 云端 = 想：LLM 决策、检索 skill、组装请求参数/蓝图、解析响应、编排流程；
- 手机 = 做：发请求（真实 IP）、存登录态（本地凭据库）、跳系统浏览器完成登录/支付/验证码配合；
- 平台流量**全部从手机真实 IP 出**，云端**永不直发平台请求、永不持有平台登录态**。

---

## 2. 苹果红线清单（全程不能碰，每条改造对照）

| 红线 | App Store 条款 | 规避方式 | 对应改造 |
|---|---|---|---|
| **A. 远程代码** | 2.5.2（不得下载/执行代码） | 手机只跑「App 内置固定引擎」，云端只下发 **JSON 配置**（请求蓝图），绝不下发可执行代码 | 第 1、6 条 |
| **B. 内购抽成** | 3.1.1（IAP 30%） | App 内**零收款、零虚拟币/积分**；支付一律跳**系统浏览器**（iOS SFSafariViewController / Android Custom Tabs）走第三方收银台 | 第 5 条 |
| **C. 爬虫壳/非原创** | 4.2（App 须有真实价值） | App 是**功能真实的个人助理**：直连办用户自己的事；文案绝不出现「逆向/抓包/自动抢票」 | 第 8 条 |
| **D. 隐私/聚合凭据** | 5.1.1 + Privacy Manifest | 第三方登录态**只存用户手机本地**（用户自己的凭据），云端不聚合；数据最小化 | 第 4 条 |
| **E. 误导/隐藏功能** | 2.3.10 | 不做「审核版/正式版」两套隐藏逻辑；云端配置只做灰度开关，不藏核心功能 | 第 8 条 |

---

## 3. 逐条改造计划

### 第 1 条：WS 协议扩展 `skill_request` / `skill_result`

- **目标**：手机能收「请求蓝图」并发回原始响应，成为执行通道；
- **现状**：[`channel/ws.py`](../cloud/cloud_orchestrator/channel/ws.py) 只有 `session_ready / result / user_input / user_action / ping`，无 skill 请求通道；
- **新增消息类型**：
  - 云端→手机：`{"type":"skill_request","req_id":"...","skill":"glyy","request":{"method":"POST","url":"...","headers":{...},"body":{...},"sign_type":"none"},"credential":{"kind":"bearer|cookie","target":"glyy|tuniu"}}`
  - 手机→云端：`{"type":"skill_result","req_id":"...","ok":true,"status":200,"headers":{...},"body":"原始响应文本"}`
- **涉及**：[`channel/ws.py`](../cloud/cloud_orchestrator/channel/ws.py)、[`channel/bridge.py`](../cloud/cloud_orchestrator/channel/bridge.py)、App 端（ui.html / 原生）；
- **红线**：A（下发的是 JSON 配置，非代码）；
- **验收**：云端 `_send_and_wait("skill_request", {...})` 能拿到手机回传的 `skill_result`。

### 第 2 条：云端 `registry.run()` 改「两段式」（下发-等待-解析）

- **目标**：云端不再直发平台请求；
- **现状**：[`registry.py:314`](../cloud/cloud_orchestrator/adapters/registry.py) `run()` 同步 `fn(**params)` 直发；
- **改造**：`run()` → `describe_request()` 生成蓝图 → 经 bridge 下发手机 → 阻塞等 `skill_result` → 调平台自身「解析层」→ 返回结构化结果；
- **涉及**：[`registry.py`](../cloud/cloud_orchestrator/adapters/registry.py)、[`core/agent.py`](../cloud/cloud_orchestrator/core/agent.py)、[`channel/bridge.py`](../cloud/cloud_orchestrator/channel/bridge.py)、`core/master.py`；
- **红线**：A；
- **验收**：`skill_run` 返回的数据与现在一致，但请求由手机发出（云端日志无平台请求）。

### 第 3 条：每个 `*_api.py` 加 `describe_request()`

- **目标**：把现有「直接 requests」拆成「蓝图生成 + 响应解析」两层；
- **现状**：[`glyy_api.py:144`](../cloud/cloud_orchestrator/adapters/glyy_api.py) `_get/_post` 直连；[`tuniu_api.py:335`](../cloud/cloud_orchestrator/adapters/tuniu_api.py) `_post` 直连；
- **改造**：每个方法加 `describe_request(params) -> 蓝图`；签名（glyy 的 `SHA1(MD5(appKey+ts+nonce))`、`sign_type`）由手机本地按 `sign_type` 计算；「响应解析」保留为独立方法留在云端；
- **涉及**：[`glyy_api.py`](../cloud/cloud_orchestrator/adapters/glyy_api.py)、[`tuniu_api.py`](../cloud/cloud_orchestrator/adapters/tuniu_api.py)（glyy 签名/登录相关常量与函数已内联进 glyy_api.py，原 glyy_session.py 已删除）；
- **红线**：A；
- **验收**：每个方法都能产出可在手机端执行的完整蓝图。

### 第 4 条：登录态迁移手机本地凭据库

- **目标**：token/cookies 只存手机（用户自己的凭据），云端不再持有；
- **现状**：glyy 写 `/tmp/glyy_session.json`（[`glyy_api.py:48`](../cloud/cloud_orchestrator/adapters/glyy_api.py)）；tuniu 存云端 `data/sessions/tuniu_web_session.json`（[`tuniu_api.py:279`](../cloud/cloud_orchestrator/adapters/tuniu_api.py)）；
- **改造**：
  - 手机本地凭据库：Android Keystore/加密 SharedPreferences；iOS Keychain；
  - glyy 登录：改手机本地完成短信登录（图形码+短信码走 WS 推送），token 存手机；
  - tuniu 登录：iOS 用 ASWebAuthenticationSession（共享 Safari cookie）或同域 WKWebView 注入 JS 读 cookie；Android 沿用现有 WebView 导出；
- **涉及**：[`glyy_api.py`](../cloud/cloud_orchestrator/adapters/glyy_api.py)、[`tuniu_api.py`](../cloud/cloud_orchestrator/adapters/tuniu_api.py)、App 端；
- **红线**：D（用户自己的凭据存自己手机，合规；解除「机房+账号」双暴露）；
- **验收**：云端进程重启不影响；手机断网时平台也查不到云端持有凭据。

### 第 5 条：支付跳转（pay_url → 系统浏览器）

- **目标**：App 内零收款，支付全部走系统浏览器第三方收银台；
- **现状**：无支付实现（[`tuniu_api.py:391`](../cloud/cloud_orchestrator/adapters/tuniu_api.py) `web_add_order` 只下单）；
- **改造**：云端下单成功 → 返回 `pay_url` → 下发手机 → 手机跳系统浏览器（iOS SFSafariViewController / Android Custom Tabs）→ 支付完成回 App → 云端轮询订单状态汇报；
- **涉及**：[`tuniu_api.py`](../cloud/cloud_orchestrator/adapters/tuniu_api.py)、[`glyy_api.py`](../cloud/cloud_orchestrator/adapters/glyy_api.py)、App 端；
- **红线**：B（App 零收款、零虚拟币）；
- **验收**：支付全流程在第三方页面完成，App 无任何收款代码。

### 第 6 条：手机端 skill 执行引擎（Android 先做）

- **目标**：手机具备「收蓝图 → 直连平台 → 回传」能力；
- **现状**：[`MainActivity.java:45`](../app/app/src/main/java/com/xiami/host/MainActivity.java) 只有浏览器指令；
- **改造**：新增 `SkillExecutor`：收 `skill_request` → 凭据库填 token/cookies → OkHttp 直连 → 回 `skill_result`；iOS 用 URLSession 对应实现；
- **涉及**：`app/`（新增 Java/Kotlin 类）；
- **红线**：A（引擎是 App 内置固定代码）；
- **验收**：手机直连 glyy 查科室能返回真实数据。

### 第 7 条：降级与兜底（手机离线）

- **目标**：手机离线时不做云端直发（避免封机房）；
- **改造**：手机离线 → ask_user 提示「请打开 App 保持在线」；默认不自动云端直发（除非显式配置）；
- **涉及**：[`core/agent.py`](../cloud/cloud_orchestrator/core/agent.py)、`core/master.py`；
- **红线**：无（内部逻辑）；
- **验收**：手机离线时 skill_run 返回明确提示，不发平台请求。

### 第 8 条：上架配套（App 工程）

- **目标**：App 能过 App Store 审核；
- **改造**：
  - Privacy Manifest（红线 D，说明使用用户自己的第三方账号访问对应服务）；
  - 文案定位「AI 生活助手」，不出现逆向/抓包/自动抢票字样（红线 C/E）；
  - 审核演示走无害功能（对话/天气/资讯），敏感功能需用户授权触发；
- **涉及**：App 工程配置（Android + iOS）；
- **红线**：C / D / E；
- **验收**：提交 App Store Connect 材料齐全。

---

## 4. 改造顺序与依赖

```
第 1 条（WS 协议）← 地基，其余依赖
  ├─ 第 2 条（云端 run 两段式）← 依赖 1
  ├─ 第 3 条（describe_request）← 依赖 1、2
  ├─ 第 6 条（手机执行引擎）← 依赖 1
  ├─ 第 4 条（登录态迁移）← 依赖 3、6
  ├─ 第 5 条（支付跳转）← 依赖 6
  ├─ 第 7 条（降级兜底）
  └─ 第 8 条（上架配套）
```

建议按 1 → 2 → 3 → 6 → 4 → 5 → 7 → 8 顺序执行。

---

## 5. 实施进度（本次改造完成）

| 条目 | 状态 | 关键改动 |
|---|---|---|
| 第 1 条 WS 协议扩展 | ✅ | [`channel/ws.py`](../cloud/cloud_orchestrator/channel/ws.py)（skill_request/skill_result + `send_skill_request`）、[`channel/bridge.py`](../cloud/cloud_orchestrator/channel/bridge.py)、[`ui.html`](../app/app/src/main/assets/ui.html) |
| 第 2 条 run 两段式 | ✅ | [`adapters/registry.py`](../cloud/cloud_orchestrator/adapters/registry.py)（`run()` async + 手机在线检查）、[`core/agent.py`](../cloud/cloud_orchestrator/core/agent.py)、[`api/routes.py`](../cloud/cloud_orchestrator/api/routes.py) |
| 第 3 条 describe_request | ✅ | [`glyy_api.py`](../cloud/cloud_orchestrator/adapters/glyy_api.py) / [`tuniu_api.py`](../cloud/cloud_orchestrator/adapters/tuniu_api.py)（蓝图 `_blueprint`/`describe_request` + 手机执行通道 executor + 云端解析） |
| 第 6 条 手机执行引擎 | ✅ | 新增 [`SkillExecutor.java`](../app/app/src/main/java/com/xiami/host/SkillExecutor.java)、[`CredentialStore.java`](../app/app/src/main/java/com/xiami/host/CredentialStore.java)、`MainActivity.executeSkill`、OkHttp 依赖 |
| 第 4 条 登录态迁移 | ✅ | glyy `login` 走手机 + store 回写（token 存手机）；tuniu executor 模式云端不持 session；`export_cookies` 自动存本地凭据库；`saveCredential` bridge |
| 第 5 条 支付跳转 | ✅ | tuniu/glyy 下单提取 `pay_url`；agent 推送 `open_external`；`MainActivity.openExternal` 系统浏览器 + AndroidManifest `<queries>` |
| 第 7 条 降级兜底 | ✅ | `registry.run` 手机离线 → 返回明确提示，不发平台请求 |
| 第 8 条 上架配套 | ✅ | 敏感词清理、AndroidManifest `<queries>`、[`docs/上架配套_AppStore.md`](上架配套_AppStore.md) |

> **遗留（后续迭代）**：iOS 端 URLSession 执行引擎（第 6 条对等）；CredentialStore 升级 Android Keystore 加密（第 4 条深化）；支付完成后云端自动轮询订单状态并汇报（第 5 条补全）。
