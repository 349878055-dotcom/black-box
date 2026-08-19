# 个人助理5 · 虾米

手机只执行 JSON 蓝图；云端只编排；Skill 只声明并组蓝图。云端不直连平台，证件和登录态只留手机，不代付。

```
客户说话
  → 云端 Agent 按契约点菜（search / read_skill / skill_run / ask_user / 登录 / 支付交付）
  → Skill 组请求蓝图（不直连平台）
  → 手机补凭据、签名，用真实 IP 打平台
  → 统一餐盒 {ok, data, error, need_login} 回云端
```

本仓库只**消费** skill。制作（抓包/逆向/自测）在独立项目 Skill 工作台；交过来的包挂在 `skill_archive/<人>/skills/<id>/`。

Skill 接入约定：[`plans/contract-v2-接口说明.md`](plans/contract-v2-接口说明.md)  
引擎怎么消费：[`plans/contract-v2-内部实现.md`](plans/contract-v2-内部实现.md)  
目录索引（按问题跳文件）：[`INDEX.md`](INDEX.md)

## 已接入（金涛名下）

| skill | 平台 | 能力 | 登录 | 交付 |
|---|---|---|---|---|
| `glyy` | 鼓楼医院互联网医院 | 查科室/排班 + 代挂号 | `sms_verify`（图形码+短信 → Bearer token 存手机） | `pay_url` |
| `tuniu` | 途牛 | MCP 查票 + M 站代下单 | 查询用 `config.json` 的 `skills.tuniu.api_key`；下单走 `browser` 导出 cookie | `pay_url` |
| `meituan_waimai` | 美团外卖 | 查店/菜单，不代登录下单 | 无（客户在美团 App 里自己登） | `imeituan://` scheme |
| `njpkzyy` | 浦口中医院 | 查科室/排班，不代挂号 | 无（客户在支付宝里自己登） | `alipays://` scheme |

登录哪条路通走哪条（`sms_verify` / `browser`），不强制一律浏览器。微信授权不当客户交付。

## 对话工具（代码里实际挂的）

雇了才艺人（会话挂了上台卡）才能办事。闲聊对话不能 `skill_run`。

| 工具 | 谁能用 | 作用 |
|---|---|---|
| `search` | 都有 | `scope=skill` 搜名下才艺/方法（向量或关键词，top-3）；`scope=web` 博查公开信息。**没有 `skill_list`。** |
| `read_skill` | 雇人后 | 精读某 skill 契约（方法/参数/登录/表单还缺什么/边界） |
| `skill_run` | 雇人后 | 执行方法；`requires` 自动补编码；`need_login` 则走 `login_flow` 后只重试这一步 |
| `ask_user` | 都有 | 问客户；可带图（图形码）和选项按钮 |
| `update_step` | 雇人后 | 多步任务进度，落在会话上 |
| `done` | 都有 | 收尾 |

检索失败直接报错，**不降级**成全量方法列表。

## 登录态

只存手机 `CredentialStore`（按邮箱+skill 隔离，Keystore 加密）。云端不持 token/cookie。

| skill | 形式 | 怎么拿到 |
|---|---|---|
| glyy | Bearer token | 短信 API：图形码最多换 3 次 → 短信码 → 蓝图 `store` 写入手机 |
| tuniu 下单 | cookie | 内置浏览器打开登录页 → 真人滑块+短信 → `export_cookies` |
| tuniu 查询 | api_key | 云端 `config.json` → `skills.tuniu.api_key`，请求时由手机占位符填 |
| 美团 / 浦口 | 无 | 不代登；scheme 拉起对方 App |

## 启动

```bash
# 云端（默认 :19000；手机直连腾讯云，不要拿本机当代理）
cd 个人助理5 && PYTHONPATH=. python -m cloud.cloud_orchestrator.main

# App
cd app/project && ./gradlew :app:assembleDebug
```

配置：`cloud/config.json`（不入库）—— LLM、JWT、博查、`skills.<id>.api_key`。

文件往哪找：[`INDEX.md`](INDEX.md)。手机能力声明：[`app/src/core/README.txt`](app/src/core/README.txt)。
