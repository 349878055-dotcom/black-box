# Contract v2 · 内部实现约定（对内）

> **读者**：实现虾米大脑 / 手机执行器的人  
> **对外接口正文**：[`contract-v2-接口说明.md`](contract-v2-接口说明.md) —— 按业务目的设计的通用接入标准  
> **说明**：现存 skill 代码仅作业务参考，不作为接口约束；引擎按接口说明消费，不按旧 skill 特判。

---

## 0. 分工与落地状态

| 文档 | 用途 |
|---|---|
| 接口说明 | 通用接口定义；供应商与写 skill 的 AI 只读它 |
| 本文 | 引擎如何实现该接口 |

**已落地（代码）**：`phone_only` 硬锁；菜单过滤 `intermediate`+`system_only`；`search` 按需召回（无 `skill_list`）；`read_skill` 精读；`requires`/`match` 补参；`confirm`；`login_flow`（短信最多换 3 次图 / 浏览器导出）；`form` 会话状态；付款按返回的 `pay_url`/`scheme` 走 `open_external`；图形码推聊天；`insecure_tls` 按蓝图关校验。

**声明了但引擎不统一执行**：`ua_profile`（UA 写在蓝图头里）、`exec`（各 api 自用）、`error_map` 除返回值 `need_login` 外、`params.validation`、`payment.open`、`flow`（已弃用）。

**当前刻意不做**：
- 云端直连 / 降级直发。
- `error_map` 其它键自动消化。
- `rules` 硬闸。

---

## 1. 目标与铁律

1. skill 写对 → 调用丝滑；平台差异只进 `contract/*.json` + `api/*.py`。  
2. **引擎禁止** `if skill == "tuniu"` 这类特判。  
3. 冻结枚举表内的差异 = 只改 skill；表外 = **升 `schema_version` / 接口版本**，才允许改引擎或手机执行器。  
4. 对内权威是本文 + 接口说明；MCP 只可作最终方法的对外投影，不得裁掉帽子层。

---

## 2. 执行模型（必须落代码）

云端不持登录态、不持手机环境。

```
AI 点最终方法
  → registry.run → api 组蓝图 skill_request
  → bridge 下发手机
  → SkillExecutor：补凭据、算 sign、真实 IP 打网站
  → skill_result（原始 body）
  → api 解析成餐盒 {ok, data, error, need_login}
  → agent 消费餐盒
```

### 蓝图形状（SkillExecutor 认这个）

```jsonc
{
  "skill": "tuniu",
  "request": {
    "method": "POST",
    "url": "https://…",
    "headers": { },
    "body": { },
    "body_type": "json",
    "sign_type": "none"
  },
  "credential": { "kind": "cookie", "target": "tuniu" }
}
```

占位符由手机替换：`{{token}}` `{{cookie}}` `{{sign}}` `{{timestamp}}` `{{nonce}}` `{{api_key}}` `{{refresh_token}}` 等（全表见 App README）。

`credential.kind`：`none` / `cookie` / `bearer` / `session` / `api_key` / `app_scheme`。  
`share_with`：凭据库共用另一 skill 的 key。

### transport

| 值 | 行为 |
|---|---|
| `phone_only` | 无手机通道直接报错。引擎强制只认此值。 |

`cloud` / `phone_fallback_cloud` 已废弃：写了也拦下来，不会云端直发。

### UA

顶层 `ua_profile`；`methods[].ua` 可覆盖。枚举：`wechat` / `mobile_browser` / `default`。

### exec

默认 `{timeout:25, retries:3, retry_delay:2}`；可选 `max_response_kb`。

---

## 3. 统一餐盒（引擎只认这个）

```jsonc
{ "ok": true, "data": {}, "error": "", "need_login": false }
```

| 字段 | 引擎行为 |
|---|---|
| `ok` / `error` | 失败内容交给对话 AI |
| `data` | 展示；按 `provides` / `payment.field` 取字段 |
| `need_login` | `login_flow` → **只重试当前方法**（不重建整段 flow）；保留已有 session |

平台成功码、字段拆包在 skill 的 `api`；引擎不按平台名写死。  
`error_map` 声明在 contract，供打标/提示（need_login、param_error、duplicate_order、manual、session_reset）。

---

## 4. 引擎消费表（实现清单）

| contract 字段 | 落在哪 | 行为 |
|---|---|---|
| `methods` 过滤 intermediate / system_only | registry / tools 列表 | 生成 AI 菜单 |
| `requires` / `provides` | `agent._fill_requires` | 缺参现调源头；`match` 精确匹配；失败报错不取第一条；`pass_params` 透传；驼峰/下划线互认 |
| `params.type=date` | agent | `resolve_dates` → `YYYY-MM-DD` |
| `params.validation` | — | 契约可写，引擎未拦 |
| `rules` | read_skill / search | 仅给 AI 阅读 |
| `login` | `login_flow` | `sms_verify`：图形码最多 3 次换一张 / 输错重取；`browser` |
| `form` | agent + 会话 `forms` | 填一个存一个；read_skill 给未填项；customer 经 ask_user 记入；auto 现调 `from`；profile 不上云 |
| `payment` + 返回值 | agent + App | data 里有 pay_url/scheme 就 `open_external`；不按 `payment.source` 拦截；`open` 未生效 |
| `confirm: true` | agent | 执行前用户确认 |
| `aliases` / `keywords` | `retrieval.index` | 检索；不拼 `flow` |
| `human_touch` / `not_deliver` | read_skill | 展示边界 |
| 图形码 `image_base64` | login_flow + App | 推聊天展示；选项「换一张」 |

---

## 5. 冻结枚举（表外才动引擎）

| 项 | 合法值 |
|---|---|
| `schema_version` | `"2"` |
| `capability` | `query` / `operate_sms` / `operate` / `operate_wechat`（后者不作为客户交付） |
| `deliver` | `query` / `action` / `pay_url` / `scheme` |
| `stage` | `final` / `intermediate` |
| auth / credential | `none` / `cookie` / `bearer` / `session` / `api_key` / `app_scheme` |
| `login.method` | `sms_verify` / `browser`（哪条路通走哪条） |
| `form.source` | `customer` / `auto` / `profile` |
| `request.insecure_tls` | 缺省 `false`；仅自签名老站 `true` |
| `payment.kind` | `pay_url` / `scheme` |
| `payment.open` | `navigate` / `open_external`（实现一律 `open_external`） |
| `transport` | `phone_only` |
| UA | `wechat` / `mobile_browser` / `default` |
| `sign_type` | `none` / `md5` / `sha1` / `sha256` / `sha1_md5` / `hmac_md5` / `hmac_sha1` / `hmac_sha256` |
| `request.method` | `GET` / `POST` / `PUT`（`PUT` 仅续期） |
| `body_type` | `json` / `form` / `multipart` |
| `params.type` | `string` / `date` / `int` / `list` / `object` / `file` |
| `store.kind` | `token` / `refresh_token` / `expires_in` / `expires_at` / `cookie` / `session` / `api_key` |
| `profile_card` | `zh` / `en` |
| 餐盒字段 | 仅 `ok` / `data` / `error` / `need_login` |

### 已知未进冻结表 / 未落地（升版本或另开再做）

| 能力 | 状态 |
|---|---|
| `params.validation` | 契约可写，引擎未拦 |
| `sign_type=mtgsig` 等 | 未实现 |
| 微信 JSAPI 代付 | 永不做；skill 走路径 B |

---

## 6. 登录 / 付款 / 验证码（引擎侧）

### login_flow

- 哪条路通走哪条，看契约 `login.method`，不强制一律浏览器。
- `sms_verify`：按 `steps` 调 system_only 方法；图形码最多 3 次（点「换一张」或 send_sms 失败自动换图）；`interact` 文案 ask_user；图形码读 `image_field`。  
- `browser`：打开 `url`；可选 `precheck` / `clear_cookies`；`export` 写凭据库；等用户「已登录」。

### payment

- 不按 `payment.source` 拦截。`data` 里出现 `pay_url` 或 `scheme`（或声明的 `field`）就交付。  
- 一律 `open_external`（系统浏览器 / 拉起 App）。  
- `scheme` 失败可读 `fallback_https`。

### 多步 + need_login

只重试当前方法。`error_map.session_reset` **未做自动重建**；失败原文给 AI。

---

## 7. 原子化依赖（已在代码，保持）

- 禁止聚合方法进菜单。  
- `_fill_requires`：递归补参、循环保护、`match`、`pass_params`。  
- 匹配不到 → 明确错误给 AI，禁止默认第一条。

---

## 8. 与 MCP

- 对内不另立 MCP 规范。  
- 若加 `/mcp`：仅投影 `stage=final` 方法为 tools；login/payment/手机通道仍按本文。

---

## 9. 落地检查（改引擎时）

```
□ 无平台名特判
□ 菜单过滤 intermediate / system_only
□ 餐盒四字段统一处理
□ need_login → 登录 → 仅重试当前方法
□ payment / confirm / date / requires / form 走声明
□ 无 skill_list、无云端直发、无检索降级
□ 新枚举必须升版本，并改 SkillExecutor（若涉及）
```

---

## 10. 声明如何送达对话 AI（search / read_skill）+ 引擎不特判

### search（统一检索）返回 = 给 AI 的「菜单快照」

- 候选每个带 `name` + `desc` + `params` + `requires`（param←from）。**不带 flow。**
- 只收录菜单方法（非 `system_only`、非 `intermediate`）。
- AI 靠它判断「选哪个方法、要问什么、哪些自动补」——所以 `desc` / `params` 写不写清楚，
  直接决定 AI 判断质量（见接口说明 §3.1，声明质量 = AI 自主处理能力）。

### read_skill（精读契约）返回 = 给 AI 的「契约全文」

- 含方法明细（desc / 参数 / customer_input / requires / 触发词）、登录 / 支付、`form`（已填/还缺）、`human_touch` / `not_deliver`。**含中间方法**（精读用）。
- 用于：客户问流程 / 能力边界时准确回答；skill_run 失败时诊断并决定重试或换方法；确认参数 / 依赖。

### 引擎不特判的保证（选择类信息 / 参数来源全走声明）

- **选择类信息**（常用联系人 / 选店 / 选科室 / 选车次）：引擎**不做任何平台特判**，
  完全靠 skill 提供「查选择源方法 + desc 提示先查再选」+ AI 自己组合「先查 → 选 → 填」。
- **参数三类来源**：
  - ② 自动补 → `requires` 走 `_fill_requires`；
  - ③ 客户端资料卡自动填 → 适配器在蓝图写 `{{字段}}` 占位符，手机 SkillExecutor 填（引擎不感知）；
  - ① 客户提供 → AI 问（缺时 ask_user）；有 `form` 时只问还没填的 `customer` 项，回答写入会话表单状态。
- **新增这类能力**（如 `list_passengers`）**不改引擎、不改 SkillExecutor**，只改 skill 的 `contract/*.json` + `api/*.py`。

---

## 附录：文档拆分

| 文件 | 读者 |
|---|---|
| [`contract-v2-接口说明.md`](contract-v2-接口说明.md) | 做 skill 的 AI / 作者 |
| 本文 | 内部实现 → 变代码 |

单 skill 实现说明（如 glyy 请求头档位）写在该 skill 的 `docs/`，例如 [`glyy/docs/README.md`](../cloud/cloud_orchestrator/store/archive_center/skill_archive/jintao/skills/glyy/docs/README.md)。
