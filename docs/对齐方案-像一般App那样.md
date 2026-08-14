# 对齐一般 App 的方案（基于代码审计，不猜测）

> 结论先行：**你的系统已经有 90% 是一般 App（淘宝/豆包）的样子了。**
> 真正要改的只有 2 处：① 拔掉 `profile` 漏缝；② 把会话 `persona` 收敛成「引用上台卡」。
> 剩下要么已经对齐、要么是你特有的架构选择（不该照搬一般 App）。
> 这份文档每一处都标注了代码位置，你自己能核对。

---

## 1. 一般 App 长什么样（一句话）

```
账号 / 会话 / 内容  → 云端（换手机还在）
登录凭证 / 敏感资料 → 手机（只在你这台手机用）
认证               → 双 token（短期 access + 长期可吊销 refresh）
```

你的三句话就是这句话，只是「证件和登录只留手机」比淘宝豆包更严（因为你不信任自己的云端）。

---

## 2. 代码审计：已经对齐的部分（**不用动**）

| 模块 | 一般 App 的做法 | 你现在（代码位置） | 状态 |
|---|---|---|---|
| 账号 | `user_id` 主键 + email + 密码哈希 | [`users.py`](cloud/cloud_orchestrator/store/users.py:47) `User`（user_id / email / password_hash(pbkdf2) / status / created_at） | ✅ 对齐 |
| 认证 | access 短期无状态 + refresh 长期可吊销 | [`auth.py`](cloud/cloud_orchestrator/auth.py:19)（ACCESS 2h + REFRESH 30 天 + 轮换吊销） | ✅ 对齐 |
| 会话 | 聊天记录在云端、按用户隔离 | [`conversations.py`](cloud/cloud_orchestrator/store/conversations.py:20) + [`master.py`](cloud/cloud_orchestrator/core/master.py:95) | ✅ 对齐 |
| 上台卡 | 内容数据在云端 | [`cards.py`](cloud/cloud_orchestrator/store/cards.py:52) + [`seed/cards.json`](cloud/cloud_orchestrator/store/seed/cards.json:1) | ✅ 对齐 |
| skill 代码 | 能力与数据分离，卡只挂 id | [`registry.py`](cloud/cloud_orchestrator/adapters/registry.py:29) 扫 `skills/*/register.py`，卡里 `skills[].id` 只引用 `glyy` 等 | ✅ 对齐 |
| 登录态 | 只存手机 | [`CredentialStore.java`](app/app/src/main/java/com/xiami/host/CredentialStore.java:9)（token/cookie 按 `token_<邮箱>_<skill>` 存本机）+ [`SkillExecutor.java`](app/app/src/main/java/com/xiami/host/SkillExecutor.java:27)（蓝图本地填 token 直连） | ✅ 对齐（且比一般 App 更严） |
| 刷新令牌 | 云端只登记能否吊销 | [`refresh_tokens.py`](cloud/cloud_orchestrator/store/refresh_tokens.py:27) | ✅ 对齐 |

**这一整块都不用动。**

---

## 3. 要改的漏缝（只有 2 处）

### 漏缝 A：`profile` 还从云端进出（办事资料残留）

| # | 位置 | 现状 | 对齐后 |
|---|---|---|---|
| A1 | [`routes.py`](cloud/cloud_orchestrator/api/routes.py:283) `GET /api/v1/me` | 返回 `"profile": {...}` | 不再返回 `profile` |
| A2 | [`routes.py`](cloud/cloud_orchestrator/api/routes.py:48) `MeUpdate` | 接收 `profile: dict` | 不再接收 `profile` |
| A3 | [`users.py`](cloud/cloud_orchestrator/store/users.py:56) `User.profile` | 字段落盘 `users.json` | 删字段，存量数据迁移时丢弃 |

**理由：** 一般 App 里「证件/资料」要么归云端平台管（淘宝地址簿），要么只在设备本地。你选择只留手机，那云端就**连字段都不该有**，否则就是偷偷存了一份。

**改法（等你点头）：**
- `MeUpdate` 删掉 `profile` 字段；
- `update_me` 不再传 `profile`；`users.update` 的 `profile` 参数删掉；
- `_user_view` 与 `me` 返回体不再带 `profile`；
- `User` dataclass 删 `profile` 字段，`from_dict` 读旧数据时丢弃。

### 漏缝 B：`persona` 还是自由 dict，不是「引用上台卡」

| # | 位置 | 现状 | 对齐后 |
|---|---|---|---|
| B1 | [`conversations.py`](cloud/cloud_orchestrator/store/conversations.py:26) | `persona: dict {nickname,prompt,bio}` 随便塞 | 只收 `{person_id, person_name, skills[]}` |
| B2 | [`routes.py`](cloud/cloud_orchestrator/api/routes.py:166) `ConvCreate.persona` | 自由 dict 透传 | 由卡片接口核验后写入引用 |
| B3 | 前端创建会话 | 传什么存什么 | 传卡 id，云端查 `cards.json` 落 `persona` |

**理由：** 一般 App 的「会话」只记「跟谁/哪个内容在聊」的引用，不会把内容整份复制进聊天记录。你的会话只该知道「跟张医生聊」= `person_id: "zhang"`，要加载能力时按 id 去 `adapters/skills/glyy/` 找，**不复制整张卡、更不复制证件**。

**改法（等你点头）：**
- `Conversation.persona` 的写入方（`create_conversation` / `ConvCreate`）只允许 `{person_id, person_name, skills[]}`，云端用 `cards.get(person_id)` 校验存在后落库；
- 读侧不用改（本来就是透传）。

---

## 4. 你特有的架构选择（**别照搬一般 App**，不用改）

这几处如果「学淘宝」反而会改坏，专门说明：

| 选择 | 你的做法 | 为什么不能照搬一般 App |
|---|---|---|
| 存储用 JSON 文件 | `users.json` 等，无数据库 | 一般 App 用 MySQL/PostgreSQL 是为了**成千上万用户并发**；你是单用户自用，JSON 就是你的本地数据库，够用且好备份。**不建议为对齐而上数据库**。 |
| skill 执行 = 手机直连 | 云端组装蓝图 → 手机真实 IP 直连平台（[`registry.py`](cloud/cloud_orchestrator/adapters/registry.py:104)、[`SkillExecutor.java`](app/app/src/main/java/com/xiami/host/SkillExecutor.java:114)） | 一般 App 是「服务器直调自己的 API」。你是「云端不持有平台登录态、手机持证直连」，这是为了**登录态留手机**这条铁律。手机直连就是你的「对齐方式」，不是偏差。 |
| `skills[].intents` | 卡里带意图词（[`cards.py`](cloud/cloud_orchestrator/store/cards.py:47)） | 这不是敏感数据，是给本地检索用的索引词，保留。 |
| `avatar` | `User` 里预留的展示字段（[`users.py`](cloud/cloud_orchestrator/store/users.py:55)） | 一般 App 都有头像，非敏感，可留可去。 |

---

## 5. 对齐后的数据流（一张图）

用大白话读这张图：

- **你的手机**里只放：① 登录凭证（access/refresh token）；② 办事资料（证件、就诊人）；③ 医院的 token、途牛的 cookie。这些**不上云**。
- **云端**只放三样：你的号（`users.json`）、聊天记录（`conversations.json`）、上台卡（`cards.json`）+ 才艺代码（`adapters/skills/`）。
- 要办事（比如挂号）时，云端不自己去医院，而是**发一张"蓝图"给你的手机**（蓝图=「去这个网址、带这个头、填这个签名」的纸条），**手机拿着本机存的 token 直连医院**，把结果回给云端解析。这样医院/途牛的登录态永远不出你的手机。
- 两边用同一个 `user_id` 对上号：`users.json` 是主键，`cards.json` 用 `owner_id` 指回来，两边的字段**不合并**。

---

## 6. 我要动哪些地方？（等你同意才动手）

「动手清单」的意思就是：**我准备改哪几个代码文件、改完会变成什么样**。一共两处，改的都是云端代码，**手机 App 和腾讯云部署都不用动**。

### 改第 1 处：把 `profile` 从云端拿掉

- **现在**：云端 `users.json` 里每个号带一个 `profile` 字段，`GET /api/v1/me` 还会把它吐出来。
- **改成**：删掉这个字段，云端既**不再收**、也**不再返回** `profile`。
- **改动文件**：[`routes.py`](cloud/cloud_orchestrator/api/routes.py:44)（接口不再接收/返回 profile）、[`users.py`](cloud/cloud_orchestrator/store/users.py:56)（`User` 里删掉 profile 字段）。

### 改第 2 处：让会话只记"跟谁聊"，不复制整张卡

- **现在**：`conversations.json` 里的 `persona` 是随便塞的自由 dict（昵称、prompt、bio 都行），等于把整张上台卡/资料可能带进聊天记录。
- **改成**：`persona` 只允许 `{person_id, person_name, skills[]}` 三样，而且 `person_id` 必须真的在 `cards.json` 里存在才让存。会话只记「跟 zhang（张医生）聊」，要用能力时按 id 去 `adapters/skills/glyy/` 找，**不复制卡片、更不碰证件**。
- **改动文件**：[`routes.py`](cloud/cloud_orchestrator/api/routes.py:164)（创建会话时只收这三样并核验）、[`conversations.py`](cloud/cloud_orchestrator/store/conversations.py:26)（字段定义收紧）。

### 改完怎么验证（你一眼能看出来）

- 登录后调 `GET /api/v1/me` → 返回里**没有 `profile`** 了，只剩 `user_id / email / nickname / bio / avatar / created_at`。
- 建一个新会话 `POST /api/v1/conversations` → `persona` 里只有 `person_id / person_name / skills[]`，不再有别的。

这两处改完，云端就真的只存「号、聊天、上台卡」，证件和登录态全在手机，跟一般 App 一样干净了。
