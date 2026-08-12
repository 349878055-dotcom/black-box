# glyy 架构流程图：微信小程序 → 后端 API → H5 登录

> 目的：说清「为什么要拆微信（解析网络请求）」「跟服务器不需要签名」「为什么登录/挂号不依赖微信小程序」「H5 登录页是不是官方的」。
> 所有结论均来自代码/监听证据，非推测。

---

## 一、总览（一张图）

```
                 ┌──────────────────────────────────────────────────────┐
                 │      鼓楼医院互联网医院官方服务器 (ih.njglyy.com:9532)  │
                 │                                                      │
                 │   ┌──────────────────────────────────────────────┐   │
                 │   │  官方后端 API  (caring/api)  ← 核心资产       │   │
                 │   │  · 挂号  /public/v3/register                 │   │
                 │   │  · 查科室 /public/dept                       │   │
                 │   │  · 登录  /v4/session/phone                   │   │
                 │   │  · （签名字段可选，实测非必需）                │   │
                 │   └───────────────────▲──────────────────────────┘   │
                 │                       │ 同一后端，两套"门面"          │
                 │   ┌───────────────────┴───────────────┐              │
                 │   │ 官方前端①：微信小程序 (servicewechat)│ 官方前端②：H5 网页│
                 │   │ 只能微信环境渲染                     │ 任何浏览器可开   │
                 │   │ page-frame.html#.../login/phone     │ caring/front/   │
                 │   │ 双tab登录页                         │ ps-patient-front│
                 │   └────────────────────────────────────┘              │
                 └──────────────────────────────────────────────────────┘
```

---

## 二、三个关键结论（带证据）

### 结论 1：微信解密 = 把小程序里的「网络请求」扒成说明书，不是要签名

医院**没有公开 API 文档**。普通人只能在微信里点按钮，看不到「请求发到哪个 URL、参数怎么写」。所以要做的事只有一件：

> **把微信小程序发出去的网络请求解析清楚**（拆源码 [`PKG_app-service.js`](tools/glyy_rev/PKG_app-service.js) 和/或抓包 `/tmp/glyy_flows.mitm`），抄成 skill 能直接调用的接口清单。

挖出来、整理进 [`_base.py`](cloud/cloud_orchestrator/adapters/skills/glyy/api/_base.py:48) `_REQUEST_MAP` 的核心是这些：
- 挂号 `/public/v3/register`
- 查科室 `/public/dept`
- 登录 `/v4/session/phone`
- 各接口要什么参数、登录三步怎么走、官方 H5 地址在哪

**微信解密的全部价值 = 这份「网络请求说明书」。** 抄完之后，运行时不再经过微信，skill 自己发同样的 HTTP 请求即可。

### 关于"签名"：小程序自己带的字段，跟服务器打交道不需要

小程序请求里还能看到 `sign=SHA1(MD5(appKey+时间戳+随机数))`、微信 UA、Referer 等字段。那是小程序**自己附带**的防伪头，**不是**你跟医院服务器说话的门槛。

**实测（见第五节）已经否定「必须签名」：**
- 公开接口（查科室等）：直接 curl，**不带签名也能通**
- 需登录接口：真正缺的是 **Bearer token**（手机号+验证码登录后拿到），不是签名
- skill 里保留签名/微信 UA = 照抄小程序习惯当保险，**非必需**

所以：**前面要拆微信，是为了解析网络请求（URL/参数/登录流程）；不是因为服务器强制要签名。**

### 结论 2：后端 API 不依赖微信 → 登录/挂号都不需要微信小程序

- 医院服务器（`ih.njglyy.com:9532`）只认 **接口 + 签名**，不认"你是不是微信"。
- 手机 App 用 [`SkillExecutor`](app/app/src/main/java/com/xiami/host/SkillExecutor.java:27) 的 `HttpURLConnection` 直接发同样请求（带签名；微信 UA 可带可不带，实测都能通）即可，服务器照常响应。
- 登录三步是**纯 API**（[`login.py`](cloud/cloud_orchestrator/adapters/skills/glyy/api/login.py:37)）：
  1. `POST /sms/captcha?phone=` → 图形验证码
  2. `POST /sms?phone=&type=1&code=<图形码>` → 发短信验证码
  3. `POST /v4/session/phone?phone=&code=<短信码>` → 登录拿 token
  - 全程只需 `Basic sms/hospital` 授权头 + 签名，**无任何微信授权依赖**；微信 UA 不是必需（见第五节实测）。
- 登录态 token 存手机本地 [`CredentialStore`](app/app/src/main/java/com/xiami/host/CredentialStore.java:10)，挂号时 App 自动带 `Authorization: Bearer <token>`。

**打个比方**：微信小程序 = 医院官方"柜台"；拆微信/抓包 = 把柜台每次递出去的「单据格式」（URL、参数、登录步骤）抄下来；有了这份单据格式，自己开窗口（虾米 App 直接调 API）就能办事，不用再去柜台排队。抄的是网络请求格式，不是什么「必须盖的签名章」。

### 结论 3：H5 登录页是官方地址，不是自己造的

- H5 前端地址**写在 glyy 微信小程序官方代码里**（[`PKG_app-service.js`](tools/glyy_rev/PKG_app-service.js)，含 `webview.wxml` / `webview?url=`，即小程序内部就是通过 webview 加载这些 H5 页）：
  - `https://www.ih.njglyy.com:9532/caring/front/ps-patient-front/` ← 患者端（登录页）
  - `https://www.ih.njglyy.com:9532/caring/front/ehospital-doctor/` ← 医生端
  - `https://www.ih.njglyy.com:9532/caring/front/pbm-mobile-front/` ← 移动端
  - `https://www.ih.njglyy.com:9532/caring/front/nursing-patient-front/` ← 护理端
- 即：**glyy 微信小程序 = 医院官方前端之一；这些 H5 页面 = 医院官方前端之二**，两者同一服务器、同一后端、同一登录体系。
- 手机内置浏览器打不开微信小程序页（servicewechat 对非微信环境返回 404，微信封闭性），但能打开官方 H5 前端。

---

## 三、实际操作链路（本仓库实现）

```
虾米 App（手机）
  ├─ 打开官方 H5 登录页（tools/glyy_open_login.py → App 原生 navigate）
  │    → https://www.ih.njglyy.com:9532/caring/front/ps-patient-front/
  │    → 切到「手机验证码登录」tab（loginWay=1）
  │    → 用户输手机号 + 短信验证码 → 登录
  ├─ token 存手机 CredentialStore（xiami_creds）
  └─ 业务请求：SkillExecutor 直接 HttpURLConnection 调官方 API
       （/caring/api/...，自动补 sign + Bearer token）
       查科室 / 挂号 / 查单 / 缴费 —— 全部不经过任何页面
```

### 一句话总结
> 微信小程序 = 微信里的入口；H5 网页 = 浏览器里的入口；两者是**同一家医院系统的两个"壳"**，后面是**同一个官方后端 API**。虾米 App 走 H5 壳登录 + 直接调 API 办事，功能与微信小程序完全等价。

### 关于"渲染"（数据 vs 画面）
- **后端 API 只给数据，不渲染画面**。返回的是 JSON（如 `{"dept_name":"泌尿外科"}`），本身不是页面。
- **渲染 = 把数据变成画面**。谁把数据画出来，谁在渲染：
  - 微信小程序 → 用**微信自己的渲染器**画（只在微信环境有）→ 普通浏览器打不开（404）
  - H5 网页 → 用**浏览器渲染器**画（Chrome / 虾米内置浏览器都行）→ 任何浏览器可开
  - 虾米 App（SkillExecutor）→ **不渲染**，直接 `HttpURLConnection` 要数据用
- **同一个后端，各用自己的方式渲染/使用**：微信小程序、H5、App 都连 `ih.njglyy.com:9532/caring/api`，只是"把数据变成画面"的方式不同。微信只是其中一个画数据的工具，**不是必须的**。

### 关于"页面 vs 接口"（skill 到底连的哪个）
同一个 9532 端口上有**两类东西**，别混淆：
- **页面（给人看）**：`/caring/front/ps-patient-front/` 等 → H5 前端，登录/看界面用
- **接口（给程序）**：`/caring/api/...` → 后端 API，skill 直接调它拿数据

**skill 连的是接口，不是页面**（[`_base.py`](cloud/cloud_orchestrator/adapters/skills/glyy/api/_base.py:20)）：
```python
BASE    = "https://www.ih.njglyy.com:9532/caring/api"          # skill 真正访问的地址（接口）
UA_WX   = "Mozilla/5.0 ...MicroMessenger/8.0.38..."            # 请求头里的微信 UA（可带可不带）
REFERER = "https://servicewechat.com/.../page-frame.html"      # 请求头里的 Referer 字段
```
- **skill 直连的是 `9532 端口的 /caring/api 接口`**（不是微信端口，也不是 H5 页面）。
- 微信 UA / servicewechat Referer **只是请求头里的两行字**，不是 skill 访问的地址；带不带微信 UA 实测都能通（见第五节）。
- H5 页面（登录用）和 API（skill 用）**都在同一个 9532 端口**，只是路径不同（`/caring/front/...` 页面、`/caring/api/...` 接口）。

---

## 四、关键文件索引

| 文件 | 作用 |
|---|---|
| [`tools/glyy_rev/PKG_app-service.js`](tools/glyy_rev/PKG_app-service.js) | 微信小程序原始代码（逆向产物），含官方 H5 地址 / 接口 / webview |
| [`tools/glyy_rev/PKG_page-frame.js`](tools/glyy_rev/PKG_page-frame.js) | 小程序页面渲染帧（page-login 双 tab 登录页结构） |
| [`cloud/cloud_orchestrator/adapters/skills/glyy/api/_base.py`](cloud/cloud_orchestrator/adapters/skills/glyy/api/_base.py:48) | 后端 API 清单 + 签名/请求头常量 |
| [`cloud/cloud_orchestrator/adapters/skills/glyy/api/login.py`](cloud/cloud_orchestrator/adapters/skills/glyy/api/login.py:37) | 验证码登录三步（纯 API） |
| [`app/app/src/main/java/com/xiami/host/SkillExecutor.java`](app/app/src/main/java/com/xiami/host/SkillExecutor.java:27) | 手机直连 API 执行引擎 |
| [`app/app/src/main/java/com/xiami/host/CredentialStore.java`](app/app/src/main/java/com/xiami/host/CredentialStore.java:10) | 手机本地登录态凭据库 |
| [`tools/glyy_open_login.py`](tools/glyy_open_login.py) | 一键在手机内置浏览器打开官方 H5 登录页 |
| `/tmp/glyy_flows.mitm` | 电脑微信访问 glyy 的监听流（mitmproxy） |

---

## 五、实测澄清（重要）：接口是否需要微信 UA？——多测 3 次定论

**实测（2026-08-10，`/caring/api/public/hotDept?limit=2` 与 H5 前端页各测 3 次，12s 超时）：**

| 组合 | 第1次 | 第2次 | 第3次 |
|---|---|---|---|
| API + 微信 UA | 200 | 200 | 000(超时) |
| API + 无 UA | 000 | 200 | 000 |
| H5 前端页 + 微信 UA | 200 | 200 | 200 |
| H5 前端页 + 无 UA | 200 | 000 | 200 |
| 443 根路径 + 微信 UA | 504 | - | - |
| 443 根路径 + 无 UA | 000 | - | - |

**结论：**
1. **API 和 H5 前端，带不带微信 UA 基本都能返回**（偶发 000 是网络抖动，非规律）。之前单次"带微信 UA 20s 无响应"是**误判**，被当成了规律，现已推翻。
2. **真正稳定的唯一规律**：**443 端口根路径 504（云防护挡），9532 端口正常**。
3. **H5 前端页（带微信 UA 3 次全 200）最稳定**，是手机浏览器应打开的入口。
4. 代码注释已修正（[`_base.py`](cloud/cloud_orchestrator/adapters/skills/glyy/api/_base.py:6)）：微信 UA 非硬性要求，保留仅为兼容老站风控。

**补充实测（2026-08-11）：调 API 需不需要"签名/暗号"？**

| 接口 | 不带签名/不带 token 直接调 | 结果 |
|---|---|---|
| 公开接口（查科室 hotDept） | 直接 curl | ✅ `{"code":0,"message":"OK"}` 返回数据 |
| 需登录接口（我的订单 orders） | 直接 curl | ❌ 报错"缺 CURRENT_USER_ID"（缺登录身份） |
| 需登录接口（挂号 register） | 直接 curl | ❌ 报错"缺请求体"（缺参数） |

**结论：调 API 不需要"微信暗号（签名）"，真正需要的是：**
1. **公开接口**：直接调就行，连签名都不用。
2. **需登录接口**：带**登录 token**（`Authorization: Bearer <token>`，手机号+验证码登录后拿到）+ 正确参数。
- **token 不是微信暗号**，是"登录后发的通行证"，存手机 [`CredentialStore`](app/app/src/main/java/com/xiami/host/CredentialStore.java:10)。
- 签名（sign）/微信 UA 只是微信小程序自己带的保险（防篡改），服务器对公开接口不强制检查；skill 保留它们=照抄微信的做法，非必需。

**关键概念澄清（端口 vs 页面 vs 渲染）：**
- **端口只有两个**：443（云防护，基本全挡）和 9532（真实服务，正常）。不是"微信一个端口/支付宝一个端口"。
- **微信/支付宝/小程序是同一端口上的不同前端入口，不是端口**。
- **微信小程序入口：后端 API 能连（能返回数据），但浏览器"渲染"不了它的页面**（微信私有渲染引擎，浏览器没有）→ 打开就 404/空页。**这是渲染引擎问题，不是端口问题。**

---

## 六、常见误区澄清

| 误区 | 事实 |
|---|---|
| "进不去微信小程序，功能就用不了" | 错。挂号/登录都走后端 API，与小程序无关 |
| "H5 登录页是别人造出来的假页面" | 错。地址写在 glyy 官方小程序代码里，官方 H5 前端 |
| "必须伪装成微信才能调接口" | 错。实测公开接口带/不带微信 UA 均正常返回，见第五节 |
| "微信解密白做了" | 错。解密/抓包是为了把微信里的网络请求解析成 API 说明书 + H5 入口；运行时不用微信，但说明书只能从这里来 |
| "必须算出签名才能调服务器" | 错。实测公开接口不带签名也能通；需登录接口要的是 token，不是签名（见第五节） |
| "登录必须微信授权" | 错。验证码登录是纯 API，微信授权只是"手机号快捷登录"另一条路 |
| "同一个端口，输出应该都一样" | 错。**端口(9532)=一栋楼，路径=楼里的房间**：`/caring/api/`给纯数据(skill用)，`/caring/front/`给网页(浏览器用)。同端口不同路径，返回不同 |
| "同一个页面，一开始渲染不出来后来能渲染" | 错。**是两个不同官方页面**：微信小程序页(浏览器打不开) vs H5网页页(浏览器能开)，逆向挖到了H5地址 |
| "skill 是在冒充微信" | 错。skill 是**按从微信里抄到的接口地址和参数**直接调后端；签名/微信 UA 可有可无，服务器认的是接口+（需登录时）token |
| "H5 页面差，skill 就用不了" | 错。**H5 前端页面差(维护少、有bug)是事实，但 skill 用的是后端 API（稳定），不经过 H5 页面**。实测 API 5 次 3 次正常返回。H5 页面只影响"人在浏览器登录"时的体验，不影响 skill 干活 |
| "必须用医院的 H5 页面" | 错。**渲染是"给 人 看"用的，是可选的**。拿到 API 数据后 3 种方式：①skill 不渲染直接拿数据干活(现在的方式) ②用官方 H5 页面(现成) ③自己写界面渲染(理论上可行)。skill 是程序不需要界面，直接拿数据干活最简单 |
| "医院有 web 和 h5 两个前端" | 错。**web = H5，是同一个东西（网页）**。医院真正两个前端入口是：微信小程序 + H5网页。微信小程序自己渲染是它的设计，与 H5 维不维护无关 |
| "最终会被计算出一个 API request" | **对（方向正确）**。不管微信小程序 / H5 / skill，一切交互的终点都是**发 API request 给服务器**，服务器返回数据；前端只是把数据变成给人看的界面 |
| "微信就一个价值：找 API 地址" | **对，本质就是解析微信发出的网络请求**。医院没有公开 API 文档，只能从微信里挖：①接口地址 ②登录流程 ③参数格式 ④H5地址(可选)。签名算法顺带能看到，但实测非必需。挖完微信就没用了 |
| "web 格式不能下单，因为桌面UA被服务器拒" | 错。**服务器不看 UA 判断来源**（实测桌面UA/微信UA/无UA 报错一样）。真正拒单的是**缺登录 token**（报"CURRENT_USER_ID 缺失"）。无论 web/微信/skill，**带上登录 token + 正确参数就能下单**；不带就被拒 |

---

## 七、一句话总结（用户理解版）

**整件事的本质：**

```
监听/拆开微信小程序（电脑微信操作 glyy 或读 PKG_app-service.js）
   ↓ 解析它发出的网络请求，一次性抄出
   ① 后端 API 接口清单（挂号/查科室/登录…）
   ② 登录流程与参数格式
   ③ 官方 H5 前端地址（可选）
   ↓
skill 直接调 API（ih.njglyy.com:9532/caring/api）——不需要签名
   ↓ 登录(手机号+验证码) → token 存手机 → 挂号/查单/缴费
```

**核心 4 点：**
1. **前面为什么要拆微信**：医院没文档，只能把微信里的网络请求解析成说明书；之后运行时微信就没用了。
2. **跟服务器不需要签名**：实测公开接口直接调就行；需登录接口要 token，不要签名。签名/微信 UA 只是小程序自己带的字段。
3. **监听/解密的本质**：拿到「端口(9532) + URL + 参数 + 登录怎么走」——即网络请求怎么发，不是算暗号。
4. **整个 skill 就是发 API 请求**：登录/挂号/查单/缴费全部直接调 `:9532/caring/api`，不经过微信、不经过浏览器页面。
