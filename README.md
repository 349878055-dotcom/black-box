# 个人助理5 · skill 消费版（API 优先）

> **放弃模拟点击（UI 自动化），全面转向「消费 skill = 平台逆向 API」模式。**
> 每个办事平台（南京12320/闲鱼/淘宝…）封装成一个 skill（*_api.py，requests 直调 HTTP 接口），
> 主代理（AI）执行 skill 直接拿数据，不再驱动浏览器去点/填/等。

## 本仓库只「消费 skill」，不制作 skill

- **skill 的制作**（探索/逆向/自测/发布）由**专门项目**负责；
- 本仓库（个人助理5）只负责**注册 + 执行**：`adapters/registry.py` 注册，主代理 `skill_run` 执行；
- 每个 skill = 一个平台逆向 API 类（session 保持登录态，返回结构化 dict/list，AI 可直接读）。

## 为什么换路线

模拟点击（Playwright/WebView 驱动）在 12320 老站踩坑：
- 老站不稳：403/慢/多端口/多路径 session
- 每个页面都要探索控件、等渲染，脆弱
- 验证码、登录态反复折腾

而 12320 实测证明：**大部分操作就是 HTTP 接口**（`hos_search.do`/`showScheduleTime.do`…），
requests 直调又快又稳，返回 JSON 直接给 AI 读。

## 核心架构

```
手机 App（对话 + 内置浏览器：只用于登录/验证码/看页面配合）
      │  HTTP + WS
云端（主代理）
  ├─ 主代理（LLM：理解用户 → skill_list 找 skill → skill_run 执行 → ask_user 交互 → 汇报）
  ├─ skill 注册表 adapters/registry.py   ← 每个 skill 一个 *_api.py
  │    ├─ nj12320_api.py      ← 南京12320（已验证，查询链路通）
  │    └─ ...（闲鱼/淘宝等后续）
  ├─ 个人资料中心（账号/就诊人/收货地址…自动带入）
  └─ 用户资料/历史存储
```

## 主代理工具

| 工具 | 作用 |
|---|---|
| `skill_list` | 列出已接入的 skill（平台逆向 API）及可用方法（含是否需要登录） |
| `skill_run` | 执行 skill 方法办理业务（skill=平台，method=方法，params=参数） |
| `ask_user` | 向用户提问/收集信息（12320 账号密码、图形验证码、手机号、确认等） |
| `web_search` | 博查联网搜索通用信息（新闻/政策/电话） |
| `done` | 办理完成，汇报结果 |

## 当前进度

- ✅ 项目骨架 + App 资产（ui.html / MainActivity.java / 内置浏览器）
- ✅ 云端主代理（LLM + skill 工具）+ skill 注册表
- ✅ nj12320 skill 查询链路实测通过（医院/科室/医生/排班/时段）
- ✅ 预约闭环实测打通：RSA 加密登录（验证码人看）→ 预约规则 → 确认页 → 提交预约（2026-08-05 真挂号成功）
- ✅ 主代理真实对话跑通：AI 自动「搜医院→找科室→查排班→回复」（无模拟点击）
- ✅ 清理旧 UI 自动化残留（CeoLoop/brain/data.skills），仓库只保留 skill 消费一条链路
- 🔄 待办：已约查询/取消预约 skill（需摸「我的预约」接口）→ 接入 App 聊天 → 扩展其它平台 skill

## 启动云端（本地测试）

```bash
cd 个人助理5 && PYTHONPATH=. python -m cloud.cloud_orchestrator.main   # :19000
```

## 目录结构

```
cloud/cloud_orchestrator/
  main.py            FastAPI 入口（/health /api/v1/chat /api/v1/task /api/v1/ws …）
  core/              主代理（agent.py：LLM + skill 工具循环；master.py：后台任务）
  adapters/          skill 注册表（registry.py）+ 平台逆向 API（nj12320_api.py）
  channel/           WS 通道（App 连接；ask_user 交互 + 浏览器人工配合）
  store/             用户资料 / 流程日志持久化
  api/               HTTP 路由
```
