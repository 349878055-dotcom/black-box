# 个人助理5 · 架构设计（skill 消费 / API 优先）

## 0. 决策背景

用户结论：**模拟点击是死路**。12320 实测证明核心业务可走 HTTP 接口。
个人助理5 以「skill = 平台逆向 API」为核心，AI 直接调用，稳定、快、可读。
**本仓库只消费 skill（注册 + 执行）；skill 的制作由专门项目负责。**

## 1. 总体分层

```
┌─ App（手机）───────────────────────────────┐
│  对话界面（复用 ui.html）                    │
│  内置浏览器（只用于：看页面 / 图形验证码 / 登录配合）│
│  个人资料中心（账号/就诊人/收货地址）          │
└───────────────┬───────────────────────────┘
                │ HTTP + WS
┌─ 云端（重写）───────────────────────────────┐
│  主代理（LLM）→ 工具：skill_list/skill_run    │
│  skill 注册表 adapters/registry.py           │
│  平台逆向 API adapters/*_api.py（HTTP 直调）  │
│  个人资料中心（云端备份 + 自动带入）            │
│  存储：users.json / flows                   │
└────────────────────────────────────────────┘
```

## 2. skill（平台逆向 API）规范（核心）

每个 skill 一个 `adapters/<platform>_api.py`，暴露统一接口：

```python
class XxxAPI:
    # 登录态（session/headers 保持）
    def check_login(self) -> str: ...
    def login(self, username, password, verify_code=None) -> dict: ...
    # 业务（查询无需登录；操作需登录）
    def search(...) -> list[dict]: ...
    def do_xxx(...) -> dict: ...
```

要求：
- 纯 HTTP（requests），返回**结构化 dict/list**（AI 可直接读）
- 验证码不自动破解：`login()` 需要 verify_code 时，主代理用 `ask_user` 让用户看图输入
- 登录态：skill 内 session 保持；需要登录的操作先 `check_login()`
- **不涉及网页自动化**：skill 的「制作」（逆向/自测/发布）在专门项目，本仓库只注册 + 执行

### skill 注册表 `adapters/registry.py`

```python
ADAPTERS = {
  "nj12320": {"class": Nj12320API, "name": "南京12320", "methods": [...]},
}
```
主代理 `skill_list` 读注册表，`skill_run(skill, method, params)` 执行。

## 3. 主代理（AI 编排）

工具集：
- `skill_list`：列出已接入的 skill（平台逆向 API）及可用方法
- `skill_run`：执行 skill 方法（skill=平台，method=方法，params=参数，返回 JSON 直接读）
- `ask_user`：问用户/收集验证码/确认（主代理与客户的核心交互）
- `web_search`：博查（查通用信息）
- `done`：收尾汇报

流程示例（挂号）：
1. 用户：「挂南京鼓楼医院 PICC门诊」
2. 主代理 `skill_run(nj12320, search_hospital, {name})` → 医院
3. `skill_run(nj12320, list_departments, {hoscode})` → 科室
4. `skill_run(nj12320, get_schedule, {...})` → 可约
5. `skill_run(nj12320, check_login)` → 未登录
6. `ask_user`：让用户看验证码输入 → `skill_run(nj12320, login, {账号,密码,验证码})`
7. `skill_run(nj12320, reserve, {...})` → 拿号（真提交前 ask_user 确认）

## 4. App（复用 + 微调）

- 复用 `ui.html`（对话）+ `MainActivity.java`（WebView 宿主）
- 内置浏览器用途：**只用于查看页面 / 展示图形验证码 / 登录人工配合**（主代理不驱动它做自动化）
- 个人资料中心保留：账号/就诊人/地址，云端同步，登录自动带入

## 5. 云端目录

```
cloud/cloud_orchestrator/
  main.py            FastAPI 入口（/health /api/v1/chat /api/v1/ws …）
  core/              主代理（agent.py：LLM + skill 工具循环；master.py：后台任务）
  adapters/          skill 注册表（registry.py）+ 平台逆向 API（nj12320_api.py）
  store/             用户/资料/流程存储
  api/               HTTP 路由
  channel/           WS 通道（App 连接；ask_user 交互 + 浏览器人工配合）
```

> 已清理旧体系：CeoLoop（core/ceo、brain/provider/llm_adapter）、旧 UI 自动化 skill 数据（data/skills）。
> 本仓库只保留「消费 skill」一条链路。

## 6. 路线（里程碑）

1. **M1**：项目骨架 + 迁移 App 资产 + nj12320 skill
2. **M2**：云端主代理（skill_list/skill_run）+ 登录（验证码人工）
3. **M3**：12320 完整闭环（查→约→拿号）真实跑通
4. **M4**：接入 App（聊天直接办事）+ 个人资料中心联动
5. **M5**：扩展其它平台 skill（闲鱼等）

## 7. 铁律

- DeepSeek 禁图：验证码展示给人看，不喂模型
- 真提交（挂号/下单）需用户明确确认
- skill 优先官方/HTTP 接口；无 API 的平台才考虑轻量自动化（降级）
- 本仓库不制作 skill；skill 由专门项目逆向制作后，本仓库注册即可消费
