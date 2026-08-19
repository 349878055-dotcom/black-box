# 虾米 Skill 接入接口（v2）

> **给谁看**：供应商，或协助写 skill 的 AI。读完本文就能交一个可被虾米对话 AI 调用的 skill。  
> **这是什么**：内部 skill 包约定（声明 + 蓝图 + 统一返回），不是对外另开一套 HTTP 接口。对方永远是各平台自己的服务器。  
> **对内引擎**：见 [`contract-v2-内部实现.md`](contract-v2-内部实现.md)（供应商不用读）。  
> **手机能执行什么**：见 [`app/src/core/README.txt`](../app/src/core/README.txt)。  
> **仓库怎么跑**：见根目录 [`README.md`](../README.md)。

---

## 1. 要解决什么问题

虾米要用自然语言办各平台的事（查信息、下单、挂号、生成付款入口等）。

平台内部千差万别，但接入虾米时必须统一成同一套形状，这样：

- 对话 AI 总能用同一方式「看见菜单、点菜、读结果」；
- 供应商（或 AI）照本文填表 + 写实现即可接入；
- 平台改版时，只改该 skill，不改虾米大脑。

每个平台交一个 **skill 包**：

| 文件 | 作用 |
|---|---|
| `contract/meta.json` | 平台说明：id / name / capability / aliases / transport / ua … |
| `contract/login.json` | 登录方案 + auth |
| `contract/methods.json` | 方法数组（对话 AI 的菜单） |
| `contract/payment.json` | 交付 / 支付 |
| `api/*.py` | 实现：组蓝图、把平台原始数据变成统一返回 |
| `register.py` | 挂载（复制样板，不写业务） |
| `docs/` | 给人看的说明（建议写清登录与付款怎么测通） |

四份契约由引擎拼成一张表；不要再写单个 `contract.json`。

---

## 2. 业务抽象（接口为什么长这样）

不论哪个平台，办成一件事通常是：

```
查询（给客户看数据）
  → 操作（下单/挂号等，常要登录）
  → 交付（给客户最终东西）
```

中间往往有「客户不会说、也不该让对话 AI 去抄」的内部编码（城市码、科室码、商品 id）。  
这些编码用**依赖声明**自动补，不靠对话 AI 手抄。

### 2.1 交付只有四种

| 交付 `deliver` | 客户得到什么 | 虾米做什么 |
|---|---|---|
| `query` | 数据 | 展示 |
| `action` | 成功或失败 | 告知结果 |
| `pay_url` | https 付款/收银台链接 | 打开浏览器 |
| `scheme` | App 协议（如 `alipays://`） | 拉起对应 App |

虾米**不代替客户付款**，只把链接或协议交给手机打开/拉起。  
若平台只能微信 JSAPI 等拉不起的支付：做到「确认页 / 订单链接」为止，用 `scheme` 或 https 链接交付，不要假装能代付。

### 2.2 方法只有三类角色

| 角色 | 标记 | 对话 AI 能看见吗 | 谁调用 |
|---|---|---|---|
| 最终方法 | `stage: final` | 能 | 对话 AI 直接点 |
| 中间方法 | `stage: intermediate` | 不能 | 系统按依赖自动调（补编码） |
| 登录内部步 | `system_only: true` | 不能 | 登录流程自动调 |

最终方法才进「菜单」和流程地图；中间方法只为补参存在。

### 2.3 登录与环境在手机

**铁律：云端不直连平台。** `transport` 只允许 `phone_only`。云端组蓝图，手机补 cookie/token/签名并用真实 IP 访问平台。没手机或手机离线直接报错，不会改走云端 `requests`。

接口里声明登录方式即可，**不要把登录态存到云端**。登录哪条路通走哪条（`sms_verify` / `browser`），不强制一律浏览器；微信授权不作为客户交付。

> **登录态最小化原则（写 skill 统一遵守）**：
> - **只读/查询方法**（查科室、查排班、查菜单、搜店铺、查号源…）**尽量 `need_login:false`、不带登录态**——接口公开可访问就不带 token，客户查询全程无感；
> - **真正要登录的操作**（挂号、下单、退票、查我的订单/处方/就诊记录…）才 `need_login:true`；
> - 登录态只存手机本地凭据库，云端不持有；需要登录的方法缺登录态时，由手机端反馈 `need_login`，云端触发一次登录后自动重试；
> - 查询 → 下单的衔接不靠 AI 抄内部编码，而靠方法的 `requires` 声明自动补参（见 3.1 B），AI 只传「名字」，代码自动翻译成平台编码。

---

## 3. 对话 AI 看到什么（可调用面）

雇了才艺人之后，对话 AI 用这些工具办事（**没有 `skill_list`**）：

| 工具 | 作用 |
|---|---|
| `search` | 按需召回名下才艺/方法（只含菜单方法）；或 `scope=web` 查公开网页 |
| `read_skill` | 精读该 skill 契约全文（含中间方法、登录、`form` 还缺什么） |
| `skill_run` | 执行方法 |
| `ask_user` | 问客户（可带图、选项按钮） |
| `update_step` | 多步进度 |
| `done` | 收尾 |

**菜单方法**（`search` 能点到的）须同时满足：

- `stage` = `final`（或不写 `intermediate`）
- `system_only` 不为 `true`

它靠这些字段选菜：

| 字段 | 作用 |
|---|---|
| `name` | 调哪个实现 |
| `desc` | 干什么、有什么坑（写清楚才会选对） |
| `params` | 要哪些参数 |
| `customer_input` | 要问客户的参数名 |
| `keywords` | 客户说法 |
| `need_login` | 要不要先登录 |
| `confirm` | 真操作前是否先确认 |
| `deliver` | 办完给客户哪种结果 |
| `form` | 多字段表单（可选；引擎按会话填一个存一个） |
| `rules` | 本平台叮嘱（只给 AI 看，引擎不硬拦） |

`flow` 已不再使用：现存契约不写，检索也不拼业务流程。真实 URL、签名、成功码 —— 对话 AI 不需要知道，写在 `api` 里。

---

### 3.1 声明怎么写，AI 才能自主处理（通用规范）

> **核心原则**：契约是「给对话 AI 的菜单 + 说明书」。AI 不背业务，
> 它靠你声明的内容自己判断「该调哪个方法、要问客户什么、哪些不用问」。
> **声明质量 = AI 自主处理能力**（写得越清楚，AI 越不用瞎猜、越不会乱问）。

#### A. 每个最终方法的 `desc` 按 4 要素写（通用模板）

1. **干什么**（一句话）；
2. **什么时候用 / 什么时候不用**（客户说哪类话才点它）；
3. **参数怎么填**：哪些要客户提供、哪些系统自动补、哪些客户端资料卡自动填；
4. **坑与边界**（真操作要确认、需登录、平台限制等）。

#### B. 每个参数必须能回答「从哪来」——三类来源 + 显式代号 `customer_input`（通用）

| 参数来源 | 契约怎么声明 | 对话 AI 行为 |
|---|---|---|
| ① 客户提供 | 方法加 `customer_input: ["param1","param2"]`——**显式代号，列要问客户的参数** | AI **只问 `customer_input` 里列的参数**，清单外都不问（不用推断） |
| ② 代码自动补 | `requires: [{param, from, field, match?, pass_params?}]` | AI 不用管、不用抄编码，系统自动现调源头方法 |
| ③ 客户端资料卡自动填 | 方法 `desc` 注明「该参数由手机资料卡自动填（{{字段}}），无需询问」 | AI 不问，手机按占位符自动填 |

> **`customer_input` 是"要问客户"的代号**：AI 读契约只认这个清单——清单里的缺就问，清单外的（requires / 资料卡 / 没声明的）都不问。未标注该字段的方法按原逻辑推断（params 无 requires、非资料卡 = 客户提供），**渐进迁移**：新写方法建议都标，老方法逐个补。
> 写方法时：逐个参数过一遍"从哪来"，客户提供的写进 `customer_input`；说不清「从哪来」的参数就是坑。

#### C. 「选择类信息」的通用声明模式（常用联系人 / 选店 / 选科室 / 选车次）

平台里常有「客户不用报、但 AI 得让客户挑」的信息（已存的常用联系人、店铺、科室、车次）。
通用做法（**不写死流程脚本**，给 AI 工具 + 提示，让 AI 自己组织）：

1. 若平台有现成选择源 → **提供一个「查选择源」方法**（如 `list_passengers` / `search_poi` / `list_depts`），
   其 `desc` 写清：「先调本方法拿到候选列表，再让客户从里面选；选中的信息可直接用于后续下单方法」；
2. 若平台没有选择源 → 直接在需要它的方法 `desc` 里写「此信息需客户提供，缺则问客户」；
3. AI 拿到候选列表 → `ask_user` 让客户选（或新增）→ 把选中的填进后续方法参数。

> 平台差异（途牛乘车人、美团店铺、医院科室）各不相同，但**声明方式完全相同**：
> 查选择源的方法 + desc 提示「先查再选」，剩下的「先查 → 选 → 填」由 AI 自己组合。

#### D. 中途问题（缺信息 / 要确认 / 失败）——统一由这些声明解决，别在 desc 里写死流程

| 中途情况 | 靠什么声明 | 谁处理 |
|---|---|---|
| 缺客户信息 | 参数没 `requires` → 客户提供 | AI 用 `ask_user` 问 |
| 内部编码（城市码/科室码/id） | `requires` / `provides` | 系统自动补 |
| 要登录 | `need_login: true` | 系统自动登录 |
| 真操作前确认 | `confirm: true` | 系统自动 ask_user |
| 失败 / 需要人工 | `error` 返回 + `error_map` 打标 | AI 看错误，按失败自愈重试/如实告知 |

> AI 的「办事流程」是它自己组合的（先查 → 选 → 填 → 确认 → 下单），**不要**在某个方法的
> `desc` 里写死整条流程脚本——写清楚「这个方法干什么、参数从哪来」即可。

#### E. 给 AI 看的字段 vs 不给 AI 看的（分清边界）

| 给 AI 看（会出现在 search / read_skill 返回） | 不给 AI 看（写在 api 实现里） |
|---|---|
| `name` `desc` `params` `customer_input` `keywords` `requires`(简略) `need_login` `confirm` `deliver` `form` `rules` `human_touch` `not_deliver` | 真实 URL、请求头、签名算法、成功码、响应解析 |

#### F. 表单类 skill：声明 `form`（字段表），不写云端复杂机制（通用）

> 有些平台办一件事 = 填一张**多字段表单**（如海关申报、就诊人登记、购票乘车人信息）。
> 这类 skill 在契约里**声明一个 `form` 字段表**即可，云端不为此加复杂机制。

**声明方式（每个 skill 自己写自己的表单，放 `meta.json`）：**

```json
"form": [
  { "field": "passport_no", "label": "护照号", "type": "text",  "source": "customer" },
  { "field": "flight_no",   "label": "航班号", "type": "text",  "source": "auto", "from": "query_flight" },
  { "field": "name",        "label": "姓名",   "type": "text",  "source": "profile" }
]
```

| 字段 | 含义 |
|---|---|
| `field` | 字段名（进表单状态 / 填进方法参数） |
| `label` | 中文名（给客户看/问） |
| `type` | 类型（text/number/date…，提示如何收集） |
| `source` | 来源：`customer`=要客户提供（问/识别）、`auto`=代码自动调方法拿（同 `requires`）、`profile`=资料卡自动填 |
| `from` | 仅 `source=auto` 时：从哪个方法自动拿 |

**声明后 AI 怎么处理（由 AI 自己组织，不写死流程）：**
1. AI 读到 `form` 字段表 → 按 `source` 分类；
2. `customer` 字段缺 → `ask_user` 问（或以后支持图片识别填）；
3. `auto` 字段 → 代码自动补（同 `requires` 机制）；
4. `profile` 字段 → 资料卡自动填；
5. 填一个存一个（云端通用表单状态，挂在会话上），每轮只把"当前没填的字段"给 AI。

资料卡字段（`source=profile`）只在手机填，**不写入云端表单状态**。

新 skill 若是一张多字段表单，在 `meta.json` 声明 `form`；方法参数名与 `field` 对齐后，引擎会把已填值补进 `skill_run`。没有 `form` 的 skill 仍用 `customer_input` + `ask_user`。

---

## 4. 统一返回（所有方法必须一样）

平台原始响应可以乱七八糟，但交给虾米时必须变成下面四个字段（缺一不可）：

```json
{
  "ok": true,
  "data": {},
  "error": "",
  "need_login": false
}
```

| 字段 | 含义 |
|---|---|
| `ok` | 业务是否成功 |
| `data` | 成功时给对话 AI 用的结构化数据（不要塞整页原始 JSON） |
| `error` | 失败原因；成功时为空字符串 |
| `need_login` | 是否登录失效；为 true 时系统走登录后**只重试这一步** |

说明：

- 各平台成功码不同 → 在你自己的 `api` 里判断，填好 `ok`。  
- `data` 里的名字必须和你在 contract 里声明的 `provides`、`payment.field`、图形码字段一致。  
- 这是**接口约定**，与任何现存 skill 实现无关；新写就必须遵守。

### 4.1 错误返回解读机制（AI 自愈的前提）

> **核心**：skill_run 失败时，AI 要靠 `error` 判断"缺什么 / 下一步怎么办"。**`error` 必须"说人话"**——写清楚缺什么、要客户给什么；写得太技术（如"170001 参数错误"）AI 看不懂、只能干瞪眼。

**error 文案模板（说人话三要素：缺什么 / 要谁给 / 下一步）：**

| 情况 | error 怎么写（示例） | AI 会怎么处理 |
|---|---|---|
| 缺客户信息 | `"缺少客户提供的参数：phone（手机号）"` | AI → `ask_user` 问手机号 → 补上重试 |
| 缺内部编码 | `"缺少前置数据：车次下单编码（需先调 train_booking_info）"` | AI → 调源头方法（requires 自动补）→ 重试 |
| 要登录 | `need_login: true`（error 可写"需要先登录 tuniu"） | 系统自动登录（登录缺手机号/验证码走 ask_user）→ 重试这一步 |
| 客户操作/平台限制 | `"已出票订单平台无自助退票，需打客服 400-xxx"` | AI → 如实告知客户，不假装能办 |
| 名称对不上 | `"无法识别「张三」对应的患者，请确认名称"` | AI → `ask_user` 让客户确认/换说法 → 重试 |

**AI 收到错误后的自愈顺序（第 2 层 AI 兜底）：**
1. 看 `error` 是否说明缺什么 → 能读懂 → `ask_user` 问 / 调源头方法补 / 直接重试；
2. 读不懂 → 调 `read_skill` 读契约诊断（看参数声明/流程）→ 再决定；
3. 平台限制 / 客户不配合 → 如实告知客户，不编造、不假装成功；
4. 反复失败 → 如实说明并建议放弃（AI 调 `done` 收尾 = 整体结束）。

**配套 `error_map` 打标**：把平台错误码映射成语义标签（`need_login` / `param_error` / `duplicate_order` / `manual` / `session_reset`），`need_login` 等系统能识别并自动处理（自动登录 + 重试）。

---

## 5. 目录约定

skill **挂在某个人的 skill 档案下**（对接实现就在这个包里，不另拆一层）：

```
store/archive_center/skill_archive/<人>/
├── card.json                 # 上台展示
└── skills/<id>/              # 此人的完整 skill
    ├── contract/
    │   ├── meta.json
    │   ├── login.json
    │   ├── methods.json
    │   └── payment.json
    ├── register.py
    ├── api/                  # 函数名 = methods[].name
    └── docs/
```

`id` = 文件夹名 = `meta.json` 的 `id`。不同人的 skill 各归各的目录。引擎用 `load_contract_parts` 把四份拼成一张契约。

---

## 6. 写之前先定三件事

| # | 定什么 | 写到哪里 |
|---|---|---|
| 1 | 用什么环境进平台（H5 / 微信 / App 等） | `ua_profile`、文档 |
| 2 | 登录怎么拿稳（短信 / 浏览器真人 / 不登录） | `auth`、`login` |
| 3 | 最终交付哪种（四种 `deliver` 之一；付款则再定 `payment`） | 方法 `deliver`、`payment` |

---

## 7. 契约字段（拆成 `contract/` 下四个 json）

### 7.1 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一 id |
| `schema_version` | 是 | 固定 `"2"` |
| `name` | 是 | 展示名 |
| `category` | 是 | 分类 |
| `capability` | 是 | 只填**最高档**，不要拼 `query+operate`。`operate*` 默认含查询。取值见第十节 |
| `capability_note` | 是 | 一句话能力边界 |
| `deliver` | 是 | 主交付（检索用）；细节以各最终方法的 `deliver` 为准 |
| `aliases` | 否 | 客户说法 → 命中本平台 |
| `transport` | 是 | `phone_only`（铁律：云端不直连平台，一切请求走手机通道） |
| `ua_profile` | 是 | `wechat` / `mobile_browser` / `default`（写入契约；实际 UA 由蓝图 headers 自带，引擎不另改） |
| `exec` | 否 | `{timeout, retries, retry_delay}`，建议 25 / 3 / 2（各 skill `api` 自用；引擎不统一读） |
| `error_map` | 否 | 平台错误码→语义标签；**引擎目前只认方法返回里的 `need_login`**，其它键不自动消化 |
| `auth` | 是 | 登录态说明 |
| `login` | 条件 | 需要本系统代登录时必填（路径 B 只交 scheme、客户在对方 App 登录则可不写） |
| `form` | 否 | 多字段表单；写在 `meta.json`；引擎按会话填一个存一个 |
| `payment` | 条件 | 有付款类最终方法时必填 |
| `rules` | 否 | 本平台叮嘱（只给 AI 看） |
| `human_touch` | 否 | 需要真人配合的事（read_skill 会展示） |
| `not_deliver` | 否 | 明确不能做的边界（read_skill 会展示） |
| `flow` | 否 | **已弃用**。现存 skill 不写；检索也不拼流程地图 |
| `methods` | 是 | 全部原子方法 |

### 7.2 auth

```json
{
  "required": true,
  "kind": "cookie",
  "how": "内置浏览器真人登录，cookie 存手机",
  "how_to_get": "登录后导出 cookie",
  "share_with": ""
}
```

`kind`：`none` / `cookie` / `bearer` / `session` / `api_key` / `app_scheme`

### 7.3 login

哪条路好走走哪条，写进 `method`（`sms_verify` 或 `browser`），不强制一律浏览器。微信授权不作为客户交付。

短信：

```json
{
  "method": "sms_verify",
  "display": "平台中文名",
  "steps": {
    "captcha": {
      "method": "get_graphical_captcha",
      "params": { "phone": "{phone}" },
      "image_field": "image_base64"
    },
    "send_sms": {
      "method": "send_sms",
      "params": { "phone": "{phone}", "gcode": "{captcha_code}" }
    },
    "login": {
      "method": "login",
      "params": { "phone": "{phone}", "code": "{sms_code}" }
    }
  },
  "interact": {
    "phone": "请输入手机号，完成{display}登录",
    "captcha_image": "请输入图形验证码（看上方图片）",
    "sms_code": "短信已发送，请输入验证码"
  }
}
```

`steps` 里的方法必须出现在 `methods` 中，并设 `system_only: true`。

### 7.4 登录容错机制（图形验证码"看不清 / 输错"自动重试）

> **问题**：登录要客户看图输验证码，客户可能"看不清"或"输错"。skill 登录要有容错，不能一次定生死（否则客户一插话就崩、整轮重来）。

**规范（login_flow 通用实现；skill 只需声明 + 提供 `get_graphical_captcha`）：**
- 图形码环节做成**循环（最多 3 次）**：取新图 → ask 客户输入 → 若客户点"看不清，换一张" 或 输入错误（send_sms 失败）→ **自动重新取图再来**；
- 交互：图形码 ask 带 `options=["🔄 看不清，换一张"]`（客户点按钮，不用打字）；客户乱输入会被当验证码提交、失败后自动换图重来（不强制输入框，靠循环兜底）；
- 循环次数用满仍失败 → 登录失败（返回 `False`）→ **抛给 AI 兜底**（AI 决定换登录方式 / 如实告知 / 放弃）。

**skill 契约要做什么：**
1. `login.steps.captcha` 正常声明（method=`get_graphical_captcha`、`image_field`）；
2. 提供 `get_graphical_captcha`（`system_only: true`）；
3. `login.interact.captcha_image` 文案可含"看不清可换一张"提示。

引擎已按此循环实现；满 3 次仍失败 → 登录返回 `False`，交给 AI 兜底。

浏览器真人：

```json
{
  "method": "browser",
  "display": "平台中文名",
  "url": "https://m.example.com/login",
  "precheck": "export_cookies",
  "clear_cookies": true,
  "export": { "cmd": "export_cookies", "domain": "https://m.example.com" },
  "interact": {
    "guide": "已打开登录页，请完成验证后回复「已登录」"
  }
}
```

图形验证码：返回 `data.image_base64`。  
滑块等：用 `guide` 引导；提示语可含「验证码 / 图片 / 截图 / 在屏幕上」以便客户端切浏览器。

### 7.5 payment

https 链接：

```json
{
  "kind": "pay_url",
  "source": "pay",
  "field": "pay_url",
  "open": "navigate"
}
```

App 协议：

```json
{
  "kind": "scheme",
  "source": "generate_order_link",
  "field": "scheme",
  "fallback_https": "https_link",
  "schemes": ["alipays://", "imeituan://"]
}
```

`field` 必须等于对应方法返回的 `data` 字段名。
`source`：标注哪个方法产出支付产物（如 `pay` / `medical_pay`）；**主代理不再按它拦截**——skill 返回的 `data` 里只要带 `pay_url`（https）或 `scheme`（拉起协议）就直接交付（弹出/拉起 + 留链接）。
`open`：声明里可写 `navigate` / `open_external`，**实现一律走系统浏览器 `open_external`，此字段暂未生效。**

### 7.6 rules

**规矩给对话 AI 自己看**，引擎不做硬拦（不根据 rules 禁止调用）。

一个 skill（比如一家医院）可以有很多条规矩；不同功能/方法也可以有不同规矩：

| 写法 | 含义 |
|---|---|
| 顶层 `rules[]`，不写 `when` | 整个 skill 通用叮嘱 |
| 顶层 `rules[]`，带 `when: "方法名"` | 只跟某一步有关 |
| 方法上的 `desc` / 可选 `rules` | 这一步自己的说明/叮嘱 |

```json
{
  "rules": [
    { "id": "no_proxy_pay", "text": "本平台不代付，只送到支付页" },
    { "id": "confirm_dept", "when": "register", "text": "挂号前必须问清科室和日期" }
  ]
}
```

客户说什么会不会点到某方法：靠方法的 `desc` / `keywords`，以及 AI 读 rules 后自己判断；云端不另做一套「能不能调」的裁判。`flow` 已弃用，不必写。

---

## 8. methods（原子方法）

只声明**最小一步**；不要做「一键办完」的大方法。  
`name` 必须与 `api` 里函数名相同。

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 方法名 |
| `stage` | 是 | `final` / `intermediate` |
| `deliver` | 最终方法必填 | 四种交付之一 |
| `confirm` | 否 | `true` = 执行前先让用户确认（真下单、退票等） |
| `desc` | 是 | 给对话 AI 的说明 |
| `need_login` | 是 | 是否要登录 |
| `ua` | 否 | 覆盖顶层 UA |
| `params` | 是 | 参数表 |
| `customer_input` | 否 | **要问客户的参数代号**（数组，列"客户提供"的参数名，如 `["passengers","contact_tel"]`）；AI 只问清单里的，清单外（requires / 资料卡 / 没声明的）都不问。⚠️ **最终操作方法（下单/挂号等）必须把客户必填的名字级参数列进 `customer_input`**（如医生名/日期/时段），否则 AI 不会主动问、全靠上下文猜 |
| `requires` | 否 | 缺参时自动调谁、取哪个字段 |
| `provides` | 否 | 本方法 `data` 提供什么编码 |
| `keywords` | 否 | 命中用语；中间方法必须 `[]` |
| `system_only` | 否 | 登录内部步为 `true` |
| `rules` | 否 | 本方法专用叮嘱（给 AI 看；也可用顶层 `rules.when`） |

### 参数

```json
{
  "date": {
    "type": "date",
    "desc": "日期",
    "optional": false,
    "validation": {}
  }
}
```

`type`：`string` / `date` / `int` / `list` / `object` / `file`  
`validation` 可选声明：`enum`、`case`、`min_len`、`max_len`、`pattern`、`min`、`max`、`ext`、`max_size_kb`、`format`。**引擎尚未按此表拦截**（`params.type=date` 会规范化成 `YYYY-MM-DD`）。

### 依赖

```json
"requires": [
  {
    "param": "item_id",
    "from": "resolve_item",
    "field": "item_id",
    "pass_params": { "keyword": "keyword" },
    "match": { "name": "keyword" },
    "note": "缺编码时自动解析"
  }
],
"provides": {
  "order_id": { "desc": "订单号", "used_by": ["pay"] }
}
```

多条结果时必须用 `match` 按名字锁定；匹配不到就报错，**禁止默认取第一条**。  
`match` 形状是 **`{ 源头记录字段: 本方法参数名 }`**（如 `"dept_name": "dept_name"`），不是 `{by, from_param}`。  
⚠️ `match` 的字段必须与要取的字段在**同一条记录**里：若字段在嵌套数组里（如排班 `detail` 里的时段），需把数组**展平**让每条记录自带匹配键（医生名+时段），否则系统取不到或取第一条（挂错）。

---

## 9. api 实现约定

每个方法：

1. 生成**请求蓝图**（方法、URL、头、body、签名、凭据、可选 store/续期）；  
2. 运行时**必须**经手机执行（`phone_only`）；  
3. 把原始响应变成第四节的统一返回。

请求蓝图示例：

```json
{
  "skill": "example_shop",
  "request": {
    "method": "POST",
    "url": "https://api.example.com/order",
    "headers": { "Content-Type": "application/json", "Authorization": "Bearer {{token}}" },
    "body": {},
    "body_type": "json",
    "sign_type": "none",
    "insecure_tls": false
  },
  "credential": { "kind": "bearer", "target": "example_shop" },
  "store": { "kind": "token", "field": "data.access_token", "target": "example_shop" },
  "auto_refresh": true,
  "refresh": { "method": "PUT", "url": "https://api.example.com/session?refresh_token={{refresh_token}}" },
  "response": { "pick": ["data.access_token"], "max_size": 20000 },
  "profile_card": "zh"
}
```

| 项 | 取值 |
|---|---|
| `request.method` | `GET` / `POST` / `PUT`（`PUT` 仅 token 续期蓝图） |
| `body_type` | `json` / `form` / `multipart`（`multipart` 上传手机本地文件） |
| `sign_type` | `none` / `md5` / `sha1` / `sha256` / `sha1_md5` / `hmac_md5` / `hmac_sha1` / `hmac_sha256`（手机按名哈希） |
| `request.insecure_tls` | 缺省 `false`（系统证书校验）；仅自签名老站才 `true` |
| `credential.kind` | `none` / `cookie` / `bearer` / `session` / `api_key` / `app_scheme` |
| `store.kind` | `token` / `refresh_token` / `expires_in`（或 `expires_at`，均当秒数加到当前时间）/ `cookie` / `session` / `api_key` |

头 / URL / body / `sign_content` 可用占位符，由手机替换：`{{token}}` `{{refresh_token}}` `{{cookie}}` `{{session_id}}` `{{api_key}}` `{{sign}}` `{{timestamp}}` `{{nonce}}` `{{appKey}}` `{{deviceid}}`，以及资料卡字段（`{{name}}` `{{phone}}` …，靠 `profile_card`=`zh`/`en` 选卡）。

`credential` 是声明；真正补头的规则：`kind=cookie` 时 App 自动补 `Cookie`；其它 kind 在蓝图里写对应占位符。

可选：`store`（登录成功回写凭据库）、`auto_refresh`+`refresh`（token 快过期静默续期）、`response.pick`/`max_size`（回传裁剪）、`profile_card`。

`transport` 只允许 `phone_only`。`cloud` / `phone_fallback_cloud` 已废弃，写了也会被拦下。

需要新的签名算法等能力时，走**接口升版**，不要私自增加枚举值。上传文件用已允许的 `body_type=multipart`。

---

## 10. 允许的枚举（只能用这些）

| 项 | 允许值 |
|---|---|
| `schema_version` | `"2"` |
| `capability` | `query`（只查）/ `operate_sms`（短信登录后可操作，含查询）/ `operate`（浏览器等登录后可操作，含查询）/ `operate_wechat`（**不作为客户交付**，仅探路） |
| `deliver` | `query` / `action` / `pay_url` / `scheme` |
| `stage` | `final` / `intermediate` |
| `auth.kind` / `credential.kind` | `none` / `cookie` / `bearer` / `session` / `api_key` / `app_scheme` |
| `login.method` | `sms_verify` / `browser`（哪条路通走哪条，不强制一律浏览器） |
| `form.source` | `customer` / `auto` / `profile` |
| `request.insecure_tls` | 缺省 `false`（校验证书）；仅自签名老站 `true` |
| `payment.kind` | `pay_url` / `scheme` |
| `payment.open` | `navigate` / `open_external`（当前实现一律 `open_external`） |
| `transport` | `phone_only`（云端不直连，其余已废弃） |
| UA | `wechat` / `mobile_browser` / `default` |
| `sign_type` | `none` / `md5` / `sha1` / `sha256` / `sha1_md5` / `hmac_md5` / `hmac_sha1` / `hmac_sha256` |
| HTTP | `GET` / `POST` / `PUT`（`PUT` 仅续期蓝图） |
| `body_type` | `json` / `form` / `multipart` |
| `params.type` | `string` / `date` / `int` / `list` / `object` / `file` |
| `store.kind` | `token` / `refresh_token` / `expires_in` / `expires_at` / `cookie` / `session` / `api_key` |
| `profile_card` | `zh` / `en` |
| `error_map` 键 | `need_login` / `param_error` / `duplicate_order` / `manual` / `session_reset` |
| 统一返回 | 仅 `ok` / `data` / `error` / `need_login` |

`params.validation` 可写在方法参数上，引擎尚未按表拦截。新能力升 `schema_version`，不要私加枚举。

---

## 11. 完整示例（复制改）

```json
{
  "id": "example_shop",
  "schema_version": "2",
  "name": "示例平台",
  "category": "本地生活",
  "capability": "operate",
  "capability_note": "可查询与下单；付款交付 https 链接，客户自行支付",
  "deliver": "pay_url",
  "aliases": ["示例店"],
  "transport": "phone_only",
  "ua_profile": "mobile_browser",
  "exec": { "timeout": 25, "retries": 3, "retry_delay": 2 },
  "error_map": {
    "need_login": ["401", "未登录"],
    "param_error": ["参数错误"]
  },
  "auth": {
    "required": true,
    "kind": "cookie",
    "how": "浏览器真人登录",
    "how_to_get": "导出 cookie 存手机"
  },
  "login": {
    "method": "browser",
    "display": "示例平台",
    "url": "https://m.example.com/login",
    "clear_cookies": true,
    "export": { "cmd": "export_cookies", "domain": "https://m.example.com" },
    "interact": { "guide": "请登录完成后回复「已登录」" }
  },
  "payment": {
    "kind": "pay_url",
    "source": "pay",
    "field": "pay_url",
    "open": "open_external"
  },
  "rules": [],
  "methods": [
    {
      "name": "search",
      "stage": "final",
      "deliver": "query",
      "desc": "按关键词查询列表",
      "need_login": false,
      "params": {
        "keyword": { "type": "string", "desc": "关键词" }
      },
      "keywords": ["搜索", "查找"],
      "system_only": false
    },
    {
      "name": "resolve_item",
      "stage": "intermediate",
      "desc": "关键词转为商品编码；仅供自动补参",
      "need_login": false,
      "params": {
        "keyword": { "type": "string", "desc": "关键词" }
      },
      "provides": {
        "item_id": { "desc": "商品 id", "used_by": ["submit_order"] }
      },
      "keywords": [],
      "system_only": false
    },
    {
      "name": "submit_order",
      "stage": "final",
      "deliver": "action",
      "confirm": true,
      "desc": "下单。真实下单，执行前需用户确认。",
      "need_login": true,
      "params": {
        "keyword": { "type": "string", "desc": "商品关键词" }
      },
      "customer_input": ["keyword"],
      "requires": [
        {
          "param": "item_id",
          "from": "resolve_item",
          "field": "item_id",
          "pass_params": { "keyword": "keyword" },
          "match": { "name": "keyword" },
          "note": "自动解析商品编码"
        }
      ],
      "provides": {
        "order_id": { "desc": "订单号", "used_by": ["pay"] }
      },
      "keywords": ["下单", "购买"],
      "system_only": false
    },
    {
      "name": "pay",
      "stage": "final",
      "deliver": "pay_url",
      "desc": "获取支付链接",
      "need_login": true,
      "params": {
        "order_id": { "type": "string", "desc": "订单号", "optional": true }
      },
      "requires": [
        {
          "param": "order_id",
          "from": "submit_order",
          "field": "order_id",
          "note": "缺订单号时需先下单"
        }
      ],
      "keywords": ["付款", "支付"],
      "system_only": false
    }
  ]
}
```

---

## 12. 协助写 skill 的 AI 应怎么做

1. 先问清：环境、登录方式、最终交付（四种里哪一种；要不要付款声明）。  
2. 用第十一节示例改出 `contract/` 四文件。  
3. 只设计原子方法；内部编码用中间方法 + `requires`。  
4. 实现 `api`：请求描述 + 统一返回四字段。  
5. 用第十三节清单自检。  
6. 不要改虾米大脑；缺能力就标明「需要接口升版」。

---

## 13. 交付清单

```
□ schema_version 为 "2"
□ 契约是 contract/{meta,login,methods,payment}.json 四文件
□ capability 只填最高档（不要 query+operate）
□ 环境 / 登录 / 交付已写进 contract；transport 必须 phone_only
□ 最终方法都有 deliver；危险操作有 confirm
□ 中间方法 keywords 为空；登录内部步 system_only 为 true
□ 方法名与 api 函数一一对应
□ 每个 api 返回 ok / data / error / need_login
□ provides、payment.field 与 data 字段名一致
□ match 用 {源字段: 本方法参数名}，不瞎取第一条
□ 枚举都在第十节允许表内
□ 没有「一键办完」的大方法
□ 方法级 deliver 必须等于该方法实际交付（返回 pay_url/scheme 就声明 pay_url/scheme，不得声明成 action）
□ need_login 必须与实现是否带登录态一致（查询不带、操作才带）
□ 未改虾米大脑
```
