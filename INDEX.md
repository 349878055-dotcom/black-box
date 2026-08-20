# 目录索引

按「想找什么」跳。系统一句话见 [README.md](README.md)。

## 按问题找

| 想… | 去 |
|---|---|
| 系统怎么跑、四家 skill 是啥 | [README.md](README.md) |
| 写 / 改 skill 契约 | [plans/contract-v2-接口说明.md](plans/contract-v2-接口说明.md) |
| 引擎认哪些字段 | [plans/contract-v2-内部实现.md](plans/contract-v2-内部实现.md) |
| 手机蓝图能干什么 | [app/src/core/README.txt](app/src/core/README.txt) |
| 云端三块怎么拆 | [cloud/cloud_orchestrator/README.md](cloud/cloud_orchestrator/README.md) |
| 对话怎么点菜 | [plans/LangGraph原生架构改造说明.md](plans/LangGraph原生架构改造说明.md) |
| LangGraph 图结构 | [cloud/cloud_orchestrator/core/graph_native.py](cloud/cloud_orchestrator/core/graph_native.py) |
| 登录短信 / 浏览器 | [login_flow.py](cloud/cloud_orchestrator/core/login_flow.py) |
| 注册、下发手机 | [registry.py](cloud/cloud_orchestrator/adapters/registry.py) |
| 某家平台对接 | [skill_archive/jintao/skills/](cloud/cloud_orchestrator/store/archive_center/skill_archive/jintao/skills/) |
| 审核记录 | [docs/体检/](docs/体检/) |
| 同事 Windows 环境 / 给 AI 的交代 | [docs/同事接手指南-Windows.md](docs/同事接手指南-Windows.md) |
| Zoo 铁令 | [.zoo-rules/ZOO_RULES.md](.zoo-rules/ZOO_RULES.md) |

## 顶层

```
个人助理5/
├── README.md                 总览
├── INDEX.md                  本文件
├── plans/                    Skill 接入约定（对外接口 + 对内引擎）
├── cloud/                    云端
├── app/                      Android 手机端
├── docs/                     体检 / 归档文档
├── tools/                    本地诊断脚本（不含部署密钥）
├── .zoo-rules/               开发铁令
└── requirements.txt          云端 Python 依赖
```

`cloud/config.json`、会话数据、密钥不入库。

## 云端 `cloud/cloud_orchestrator/`

| 路径 | 干什么 |
|---|---|
| [main.py](cloud/cloud_orchestrator/main.py) | FastAPI 入口（默认 :19000） |
| [api/routes.py](cloud/cloud_orchestrator/api/routes.py) | HTTP：登录、对话、任务、/me、上台卡 |
| [auth.py](cloud/cloud_orchestrator/auth.py) | JWT |
| [config.py](cloud/cloud_orchestrator/config.py) | 读 `cloud/config.json` |
| [core/master.py](cloud/cloud_orchestrator/core/master.py) | 后台任务、interrupt/resume、会话进度 |
| [core/agent.py](cloud/cloud_orchestrator/core/agent.py) | 人设闸门、skill_run、补参、确认、付款 |
| [core/graph_native.py](cloud/cloud_orchestrator/core/graph_native.py) | LangGraph StateGraph + interrupt |
| [core/graph_engine.py](cloud/cloud_orchestrator/core/graph_engine.py) | 薄入口（run_agent_graph） |
| [core/graph_tools.py](cloud/cloud_orchestrator/core/graph_tools.py) | 工具 schema（phase gating） |
| [core/dialogue/](cloud/cloud_orchestrator/core/dialogue/) | resolve_reply / route / skill_lock 纯函数 |
| [core/login_flow.py](cloud/cloud_orchestrator/core/login_flow.py) | `sms_verify` / `browser` |
| [core/form_state.py](cloud/cloud_orchestrator/core/form_state.py) | 契约 `form` 会话状态 |
| [adapters/registry.py](cloud/cloud_orchestrator/adapters/registry.py) | 扫描 skill、强制 phone_only、注入手机通道 |
| [retrieval/](cloud/cloud_orchestrator/retrieval/) | BGE 向量：`search(scope=skill)` |
| [channel/](cloud/cloud_orchestrator/channel/) | 手机 WS：蓝图 / ask_user / 浏览器原语 |
| [store/archive_center/consumer_archive/](cloud/cloud_orchestrator/store/archive_center/consumer_archive/) | 账号、会话（聊天 messages；办事状态在 checkpoint） |
| [store/archive_center/skill_archive/](cloud/cloud_orchestrator/store/archive_center/skill_archive/) | 上台卡 + 各人 skill 包 |

## Skill 包（每人一份）

`store/archive_center/skill_archive/<人>/`

```
card.json                      上台展示
skills/<id>/
  contract/meta.json           平台说明
  contract/login.json          登录 + auth
  contract/methods.json        方法菜单
  contract/payment.json        交付 / 支付
  api/                         组蓝图、解析餐盒（函数名 = 方法名）
  register.py                  挂到 registry
  docs/                        该平台说明 / 测试
```

金涛名下：`glyy` 鼓楼 · `tuniu` 途牛 · `meituan_waimai` 美团 · `njpkzyy` 浦口。

## 手机 `app/`

| 路径 | 干什么 |
|---|---|
| [src/core/](app/src/core/) | Java：[`SkillExecutor`](app/src/core/java/com/xiami/host/SkillExecutor.java) 跑蓝图；[`CredentialStore`](app/src/core/java/com/xiami/host/CredentialStore.java) 凭据+资料卡；[`MainActivity`](app/src/core/java/com/xiami/host/MainActivity.java) 宿主 |
| [src/ui/](app/src/ui/) | [`ui.html`](app/src/ui/assets/ui.html) 对话；内置浏览器页 |
| [project/](app/project/) | Gradle：`cd app/project && ./gradlew :app:assembleDebug` |

## 文档

| 路径 | 干什么 |
|---|---|
| [docs/体检/四方向审核思路.md](docs/体检/四方向审核思路.md) | 审核尺子 |
| [docs/体检/体检报告-确定项.md](docs/体检/体检报告-确定项.md) | 已闭环 |
| [docs/体检/体检报告-待定项.md](docs/体检/体检报告-待定项.md) | 待定 / 已处理 |
| [docs/archive/](docs/archive/) | 旧实现说明、写 skill 第一规则、运维/上架（归档，以代码+plans 为准） |
