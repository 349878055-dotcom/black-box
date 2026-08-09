# 个人助理5 · skill 消费版（API 优先 · 微信小程序方向）

> **放弃模拟点击（UI 自动化），全面转向「消费 skill = 平台逆向 API」模式。**
> 当前主攻方向：**微信小程序逆向** —— 把常用微信小程序（医院挂号、出行购票…）
> 背后的真实 HTTP 接口封装成 skill，主代理（AI）直接 requests 直调拿数据，
> 不再驱动浏览器去点/填/等。

## 本仓库只「消费 skill」，不制作 skill

- **skill 的制作**（逆向/解包/抓包/自测/发布）由**专门项目 `Skill工作台`** 负责：
  - 方法论文档：`Skill工作台/docs/微信小程序批量逆向方法论.md`（解包 wxapkg → 挖接口 → 抓登录态 → 规范化）
  - 工具：`Skill工作台/tools/unpack_wxapkg.py`（wxapkg 解包）
  - 制作产物：`Skill工作台/skill_maker/sites/{id}/`（contract.json + api.py + session.py）
- 本仓库（个人助理5）只负责**注册 + 执行**：`adapters/registry.py` 注册，主代理 `skill_run` 执行；
- 每个 skill = 一个平台逆向 API 类（session 保持登录态，返回结构化 dict/list，AI 可直接读）。

## 已接入的 skill（2026-08-06 更新）

| skill | 平台 | 方法数 | 说明 |
|---|---|---|---|
| `glyy` | 南京鼓楼医院互联网医院（微信小程序） | 26 | 挂号全链路 + 报告/缴费/处方/病历/复诊/在线咨询（Bearer token） |
| `tuniu` | 途牛（官方 MCP + 官网/小程序） | 10 + 8 | MCP 查票 + 官网查车次/下单/订单/取消（cookies + sessionId） |

每个 skill 的完整能力（`flow` 分层业务地图 + `methods` 方法表）用 `skill_list` 查看。

## 核心架构

```
手机 App（对话 + 内置浏览器：只用于登录/验证码/看页面配合 + 导出登录态）
      │  HTTP + WS
云端（主代理）
  ├─ 主代理（LLM：理解用户 → skill_list 找 skill → skill_run 执行 → ask_user 交互 → 汇报）
  ├─ skill 注册表 adapters/registry.py   ← 每个 skill 一个 *_api.py
  │    ├─ glyy_api.py        ← 南京鼓楼医院（微信小程序逆向）
  │    └─ tuniu_api.py       ← 途牛（MCP + 官网/小程序，含 TuniuWebAPI）
  ├─ 个人资料中心（账号/就诊人/收货地址…自动带入）
  └─ 用户资料/历史存储
```

## 主代理工具

| 工具 | 作用 |
|---|---|
| `skill_list` | 列出已接入的 skill（平台逆向 API）及可用方法（含是否需要登录） |
| `skill_run` | 执行 skill 方法办理业务（skill=平台，method=方法，params=参数） |
| `ask_user` | 向用户提问/收集信息（验证码、手机号、确认等） |
| `web_search` | 博查联网搜索通用信息（新闻/政策/电话） |
| `done` | 办理完成，汇报结果 |

> `skill_run` 支持 `web_*` 前缀方法：走同一平台的第二套实现（如途牛官网 `TuniuWebAPI`）。

## 向量检索「小纸条」机制（retrieval/）

skill 越来越多后，不再把全部方法塞给 AI，而是**两级按需召回**：

- **平台级检索**：客户一句话 → 本地 BGE 向量（中文，云端本机跑，零网络）→ 方法级聚合成 top-1 平台
- **功能级检索**：在该平台内选出最相关方法 2~4 个
- **小纸条**：只把「当前平台 + 当前功能方法 + 流程地图 + 备选平台」注入 LLM，AI 只在小纸条里选
- **会话锁定 + 防抖**：同一话题沿用当前平台；连续 2 次检索指向别的平台才切换（客户一句话没说完不乱跳）
- **降级**：模型不可用时自动回退到旧 `skill_list` 全量模式

依赖：`sentence-transformers`；模型已下载到 `cloud/models/bge-small-zh-v1.5`（离线可用）。
新增 skill 后自动纳入索引（`retrieval/register.py` 重建）。

## 微信小程序逆向 → skill 流程（速览）

1. **定位小程序**：电脑微信缓存 `~/.xwechat/radium/Applet/packages/{appid}/` 找目标 wxapkg
2. **解包**：`python3 tools/unpack_wxapkg.py __APP__.wxapkg --out /tmp/xxx` → 拿到 `app-service.js`（明文业务代码）
3. **挖接口**：从 JS 搜接口路径 / 登录机制 / 签名算法 → 形成接口字典
4. **登录态 + 抓包**：mitmproxy 抓真实请求 → 拿 token / cookies / sessionId（验证码/短信真人配合一次）
5. **规范化**：写 `sites/{id}/`（contract.json + api.py + session.py）→ 注册进 `registry.py`

## 启动云端（本地测试）

```bash
cd 个人助理5 && PYTHONPATH=. python -m cloud.cloud_orchestrator.main   # :19000
```

## 目录结构

```
cloud/cloud_orchestrator/
  main.py            FastAPI 入口（/health /api/v1/chat /api/v1/task /api/v1/ws …）
  core/              主代理（agent.py：LLM + skill 工具循环；master.py：后台任务）
  adapters/          skill 注册表（registry.py）+ 平台逆向 API（*_api.py）
  channel/           WS 通道（App 连接；ask_user 交互 + 浏览器人工配合）
  store/             用户资料 / 流程日志持久化
  api/               HTTP 路由

app/                 Android 手机端（对话 UI + 内置浏览器 + 导出登录态）
```

## 登录态（是什么 + 每个 skill 从哪来）

**登录态 = 请求时带的"门禁卡"**：每次请求带着它，网站才知道是你。
卡的样式可能是 token / cookie / sessionId（本质一样，只是放的位置/样式不同）：
- **Token**：请求头 `Authorization: Bearer xxx`（如鼓楼医院）
- **Cookie**：请求自动带 `session=xxx`（如途牛网页版）
- **sessionId**：请求参数带 `sid=xxx`（如途牛小程序）

**关键**：微信小程序（鼓楼医院、途牛）的登录态在微信私有通道里，**内置浏览器导出拿不到**。各 skill 登录态正确来源如下：

> 📌 **登录态说明是每个 skill 的固定栏目**：未来新增 skill 必须在制作端 `contract.json` 的 `auth.how_to_get` 里写明「①形式 ②从哪来 ③要不要人配合」，拖到本仓库后补进下表——缺登录态说明的 skill 视为不完整，不能上线。

| skill | 登录态形式 | 从哪来（正确来源） | 要内置浏览器吗 | 现状 |
|---|---|---|---|---|
| glyy 鼓楼医院 | Bearer token | **内置浏览器自助登录**（2026-08-08 改）：自动弹内置浏览器打开 `https://www.ih.njglyy.com`（微信 UA）→ 客户自己输手机号+短信码登录 → 自动 `export_token` 导出 token 存手机凭据库 | ✅ 需要（微信 UA） | ✅ 已改造，待手机实测 |
| tuniu 查询 | apiKey | **config.json 配置**（`tuniu.api_key`） | ❌ 不需要 | ✅ 已配置，查询可用 |
| tuniu 下单 | cookies + sessionId | **网页版**：App 内置浏览器登录 → 导出 cookies；**小程序**：抓包拿 sessionId | ⚠️ 网页版可，小程序不行 | 🔄 需重新获取一次 |

> 说明（2026-08-08 用户铁令）：**所有平台登录统一改为「弹内置浏览器 → 客户自己登录 → 自动导出登录态存手机」**，
> 废弃 glyy 旧的「云端 ask_user 一步步问手机号/图形验证码/短信码」方式。
> glyy 登录页 `https://www.ih.njglyy.com` 必需微信 UA（navigate 传 `ua=wechat`）；登录后云端下发 `export_token`
> 命令，手机端从浏览器 localStorage/cookie 读 Bearer token 存 `CredentialStore token_glyy`，后续请求自动补
> `Authorization: Bearer`。途牛下单同理念（网页版导出 cookie）。

## 登录态文件（持久化于 data/sessions/，云端重启不丢）

| skill | 登录态文件 | 获取方式 |
|---|---|---|
| glyy | `cloud/cloud_orchestrator/data/sessions/glyy_session.json` | 手机号+短信验证码登录（glyy_api.get_graphical_captcha → send_sms → login）；验证码图片通过 WS 推送到 App 聊天窗口显示，用户看图输入 |
| tuniu | `cloud/cloud_orchestrator/data/sessions/tuniu_web_session.json` | App「导出登录态」/ 抓包 → `TuniuWebAPI.save_session()` 保存；重启自动加载 |
