# 鼓楼医院 Skill 变更记录

## v2.2.0（2026-08-11）登录独立成云端通用模块（login_flow）
- **用户铁令**：登录独立成完整模块，删除手机端 LoginCoordinator，登录全放云端；AI/系统按需触发。
- **云端新增** `core/login_flow.py`：通用登录编排器，读 skill 声明的 `login` 配置执行。
  - `sms_verify`（glyy）：手机号→图形码→短信码→login，走手机通道（registry.run + ask_user 交互）
  - `browser`（tuniu）：内置浏览器真人登录（navigate→真人操作→导出登录态）
- **skill 声明**：`contract.json` 新增 `login` 配置块；`register.py` 透传 `login` 到 ADAPTERS。
- **agent 瘦身**：`_ensure_login` 只按 skill 读 login 配置调 `login_flow.run_login`，
  删除硬编码 `_login_glyy` / `_login_tuniu` / `_skill_has_login`；
  `_run_tool` 的 need_login 分支统一走云端登录（撞出未登录→隐藏错误→登录→自动重试业务）。
- **手机端删除** `LoginCoordinator.java`（及 MainActivity/SkillExecutor 引用），登录交互全由云端 ask_user 完成。

## v2.1.0（2026-08-11）登录改为纯 API（放弃网页登录）
- **用户铁令**：glyy 放弃网页（内置浏览器）登录，纯粹 API 登录。
- **根因**：`_login_glyy` 之前下发 navigate 打开 `GLYY_LOGIN_URL`（servicewechat 小程序 page-frame），
  非微信环境打不开；医院 H5 页打开也不稳（403/504/挂起）→ 网页登录不可靠。
- **云端**（`core/agent.py` `_login_glyy`）：重写为纯 API 登录编排，全程走手机通道：
  `_ask` 要手机号 → `get_graphical_captcha`（图形码图经 ask_user 推 App 聊天显示）→
  `send_sms`（带图形码）→ 用户输短信码 → `login`（token 由手机 SkillExecutor 自动存凭据库）。
- 删除浏览器登录专用常量 `GLYY_LOGIN_URL` / `GLYY_LOGIN_REFERER`。
- **微信 UA 结论**（实测）：API 层（ih.njglyy.com:9532/caring/api）带/不带微信 UA 均正常，
  非硬性要求（`_base.py` 保留 UA_WX 兼容风控）；医院 H5 网页默认 UA 也能打开。

## v2.0.1（2026-08-09）内置浏览器登录「进不了」修复
- **根因**：内置浏览器打开 glyy 登录页失败（老站 403/504/DNS 等）时，App 端 `navigate` 一直静默等 45s 超时，且超时仍回 `ok:true` → 云端 `_login_glyy` 误以为页面已打开，直接问「已在内置浏览器打开登录页」，用户看到的是打不开的页面（表现为"进不了"）。
- **App 端**（`MainActivity.java`）：浏览器 `WebViewClient` 新增 `onReceivedError` / `onReceivedHttpError` —— 主文档网络/HTTP 错误立刻回执 `navigate` 失败（`{ok:false, error}`），不再等超时误报成功；`ERROR_ABORTED`（重定向/取消）跳过不误判。
- **云端**（`core/agent.py` `_login_glyy`）：检查 `navigate` 结果，失败自动重试一次；仍失败则如实告知用户可回复「重试」或从左侧栏「浏览器」手动输入网址打开，再等「已登录」兜底导出登录态。
- 登录 URL / Referer 提为模块常量 `GLYY_LOGIN_URL` / `GLYY_LOGIN_REFERER`。

## v2.0.0（2026-08-08）原子化 + 前置依赖
- **删除 `book` 一键挂号**（聚合方法），统一为原子方法 + 前置依赖
- **契约与 api.py 参数对齐**（原 get_schedule/list_doctors/get_available_dates/register 的 params 与真实签名脱节，已修正）
- contract.json 补齐 `provides`/`requires`/`match`/`pass_params`：register 的 15 个参数标注来源（list_depts / get_schedule / get_patient），系统自动按名字精确补齐
- 登录三步（login/get_graphical_captcha/send_sms）标 `system_only`，登录由系统内置浏览器编排，AI 不参与

## v1.0.0（2026-08-07）
- 打通：登录/查号源/挂号/我的就诊/病历缴费
- 仅走手机通道（禁云端直连）
- 登录态 token 存手机授权中心
