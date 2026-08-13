# 浦口中医院（pkqzyy）Skill · 更新与避坑日志汇总

> 汇总日期：2026-08-13
> 目的：把浦口中医院（pkqzyy）skill 的更新日志与避坑日志汇总到一个文件，便于共享与维护。
> 数据来源：工作区真实日志（`pkqzyy_token_test.md`、`skill发布/.../pkqzyy/docs/README.md`、`black-box/README.md` 等），非编造。

---

## 一、昨天（2026-08-12）更新日志

### 1. `list_depts` 返回科室列表混入子科室（已修复）
- **现象**：`list_depts` 返回的列表混入子科室（如 `2010 皮肤科`、`2034 心内科`），同时漏掉部分顶级科室。
- **根因**：接口返回全部 243 个科室（含顶级 `pid=0` 和子科室 `pid!=0`），LLM 没有正确按 `pid` 过滤。
- **修复**：`list_depts` 默认只返回 `pid=0` 的顶级科室（共 32 个）。

### 2. skill 缺「获取子科室」方法，LLM 无法下钻查号源（已修复）
- **现象**：用户问「内科有什么子分类、明天有哪些号」，LLM 看不到内科（S103462）的 4 个子分类。
- **根因**：接口是两级结构（pid=0 顶级 + pid!=0 子科室），号源挂在子科室上，但 contract 没暴露「获取子科室」方法。
- **修复**：`list_depts` 增加 `parent_code` 参数——传顶级科室代码 → 返回该科室下的子科室。

### 3. 云端存在重复 skill `njpkzyy_new` 导致 LLM 用错（已移除）
- **现象**：科室列表混入子科室，且把不同顶级科室误当成「内科相关」。
- **根因**：云端存在两个重复的浦口中医院 skill（`pkqzyy` 已修复 + `njpkzyy_new` 未修复）。
- **修复**：彻底删除云端 `njpkzyy_new` skill 目录，重启云端服务。向量索引重建为 4 平台 69 条。
- **通用教训**：同一医院只保留一个 skill，避免重复注册。

### 4. LLM 凭科室名称主观归类，把 6 个顶级科室误归为内科子科室
- **现象**：LLM 只列出 26 个顶级科室，遗漏 6 个（呼吸科/肺病科、脾胃科/消化科等），并错误注释「这些属于内科下的子科室」。
- **根因**：LLM 凭语义主观归类，没有严格依据接口返回的 `pid` 字段。
- **建议**：contract 描述明确「严格按 pid 字段区分层级，pid=0 就是顶级科室，不要凭名称主观归类」。

### 5. `get_schedule` 描述未写「下午/夜间」时段，LLM 只解析上午（已修复）
- **现象**：用户问「无痛中心明天下午/夜间有没有号」，LLM 回复「下午/夜间查询无排班数据」，但后端实际下午和夜间都有号。
- **根因**：`normal` 数组里每条记录是一个「号别+时段」组合，contract 描述没告诉 LLM 要遍历所有时段。
- **修复**：contract 描述明确「必须遍历数组里所有时段，把上午/下午/夜间各自的号源都展示出来」。

### 6. LLM 未下钻内科子科室，误判「内科无号源」（已修复）
- **现象**：用户问「帮我挂内科明天」，LLM 回复「内科无可用号源」，但后端实际内科子科室明天有号。
- **根因**：LLM 直接对顶级科室 `S103462` 调 `get_schedule`（返回空，因为号源在子科室），就误判「内科无号源」。
- **修复**：contract 描述强制「查号源必须下钻」——先 `parent_code` 下钻到子科室，再逐个查排班。

### 7. 打开虾米提示「对话平台是 glyy」（小纸条平台锁定机制，非 bug）
- **现象**：用户打开虾米 App，提示「对话平台是南京鼓楼医院互联网医院（glyy）」，但用户实际想用浦口中医院（pkqzyy）。
- **原因**：小纸条「平台锁定 + 防抖」机制——若之前对话锁定了 glyy，打开 App 时沿用 glyy。
- **处理**：用户直接说「我要去浦口中医院」，小纸条检测到意图切换后切到 pkqzyy。

### 8. 微信登录后仍拿不到 token（手机端 SkillExecutor 问题，云端无法修复）
- **现象**：用户手机微信授权登录后，虾米 App 仍提示「缺少登录态（token）」。
- **根因**：云端配置了 `login` 配置（`kind: wechat_ma`），云端不编排登录，交给手机端处理；但手机端 SkillExecutor 没有正确完成微信授权登录。

### 9. 手机端需实现「通用 wechat_ma 微信授权登录」（配置驱动）
- **背景**：手机端 LoginCoordinator 没有实现通用的 `wechat_ma` 微信授权登录。
- **正确架构**：手机端只实现一次通用的 `wechat_ma` 登录，每家医院的差异通过云端下发的 login 配置区分。

### 10. 手机端无法直接实现 wechat_ma 登录（根本性难点）
- **背景**：虾米 App（com.xiami.host）是独立的 Android App，不是微信小程序。微信小程序授权需要 `code/encrypted_data/iv` 三个参数，虾米 App 无法获取。
- **可行方案**：改 pkqzyy 登录方式为手机号+短信登录（sms_verify）。

---

## 二、今天（2026-08-13）更新日志

### 1. 方式 4（手机号+短信登录）接口已确认
- **探测结果**：浦口中医院支持手机号+短信验证登录，正确接口路径为：
  - 发短信：`GET /api/sms/code?phone=<手机号>` → `code:0 OK`
  - 登录：`POST /api/v4/session/phone?phone=<手机号>&code=<验证码>` → `code:0 + data.access_token`
  - 密码登录：`POST /api/v4/session`（OauthInfoV2，需 role/username/password/device/grant_type）
- **之前探测脚本错在路径**：探测的是 `/api/session/phone`、`/api/session/sms`，而正确路径是 `/api/v4/session/phone`（带 `v4`）。
- **后端**：chinacaring 系统（`com.chinacaring.user.controller.v4.SessionController`），与鼓楼医院（glyy）同厂商。

### 2. 登录方式写死问题记录
- **问题**：pkqzyy 无法用手机号+短信登录，因为登录流程在源码里写死，pkqzyy 没有对应的登录编排方法。
- **根因**：
  1. 云端 `agent.py` 的 `_ensure_login` 按 skill 名写死分发，pkqzyy 无 `_login_pkqzyy`
  2. 云端 login 配置是 `wechat_ma`（手机端不支持）
  3. 手机端 LoginCoordinator 的 `sms_verify` 流程写死（为途牛定制）
- **方案**：走云端编排登录（`_login_pkqzyy`），手机端源码不用改。

### 3. 代码改动（本次任务）
- 修改 `login.py`：新增 `get_sms_code` + `login_by_sms`
- 修改 `contract.json`：新增方法 + aliases
- 修改 `register.py`：移除 login 配置（让云端编排）
- 修改 `agent.py`：新增 `_login_pkqzyy`
- 全部部署到腾讯云并验证通过

### 4. 向量检索误匹配问题（已修复）
- **问题**：用户说「脾胃科专家门诊明天有没有号」时，向量检索错误匹配到鼓楼医院（glyy），而不是浦口中医院（pkqzyy）。
- **根因**：pkqzyy 的 contract.json 没有 `aliases`（别名）字段，向量检索无法通过「浦口」等别名识别出是浦口中医院。
- **修复**：给 pkqzyy 的 contract.json 添加 `aliases`（浦口/浦口中医院/浦口区中医院等）。
- **验证**：所有浦口中医院相关查询正确匹配 pkqzyy（如「脾胃科专家门诊」pkqzyy 0.6149 > glyy 0.5901）。

---

## 三、避坑日志

### 1. pkqzyy 后端要点（踩过的坑）
- **域名端口**：`https://hzfw.njpkzyy.com:18086`（端口 18086，443 超时）
- **签名**：`sign = SHA1(hex(MD5(appKey + timestamp + nonce)))`，`appKey=1202patient`（先 MD5 再 SHA1）
- **请求头必须带 `agent_id`**（缺它返回 400）
- **agent_id 区分**（用错返回"应用系统繁忙"）：
  - 查询类 → `AGENT_ID = 6396cb2be4b0dc1899f48fe7`
  - 在线号/挂号类 → `ONLINE_AGENT_ID = 62da65d4e4b0e0a247890d84`
- **登录**：微信小程序授权 `POST /api/session/wechat/ma` → `access_token`（JWT）
- **退号接口**：`POST /api/public/v3/cancel_register`；`/api/public/order/cancel` 不是退号入口（返回 30002）
- **微信小程序包是 V1MMWX 加密**，解不开时直接用签名头直连后端

### 2. black-box 踩坑记录（统一汇总）
1. **抓包 token 被截断**（glyy）：抓包工具对 authorization/token 头只保留前 400 字符，JWT 被截断 → 改 2000 并重启
2. **漏抓科室子分类**（glyy 江北）：只抓一级科室，没展开子分类 → 必须逐个点开所有科室分类
3. **token 过期误判**（glyy）：仅凭"Token expired"就判断过期，实际是请求方式问题 → 先验证 token 是否没变
4. **微信登录名 ≠ 就诊人**（重要）：微信登录账号（刘良玺）≠ 就诊人（刘贤才）→ 挂号前必须确认就诊人
5. **挂号接口参数差异**（glyy）：成功请求有 `section_id: 7`、`business_type: 2` 等关键参数 → 完全复制成功请求
6. **小程序复用缓存 token**（glyy）：重新登录不生成新 token → 走短信登录 `POST /v4/session/phone`
7. **抓包进程不稳定 / 系统代理未恢复**：mitmdump 反复退出 → 频繁重启 + 确认代理恢复
8. **排班响应被截断**（resp_body 限制 6000 字符）→ 用 API 直调
9. **is_enable=0 但 left_reg_num>0**（glyy）：`is_enable` 不代表最终可约状态 → 以登录后真实状态为准
10. **排班数据查看不完整，误判无号**（glyy）：只看到部分午别 → 必须完整解析所有午别，信任用户说法

### 3. 另一个 AI 容易踩的坑
- 坑 1：凭猜测写请求，不抄成功请求
- 坑 2：仅凭服务器一句话就下结论（token 过期误判）
- 坑 3：漏抓数据，不完整展开
- 坑 4：被抓包工具的截断限制坑到
- 坑 5：抓包进程/代理环境不稳定
- 坑 6：不理解登录态机制（token 从哪来）
- 坑 7：误判号源状态（is_enable / remaining_num）
- 坑 8：院区/分支参数硬编码错

---

## 四、测试环境

- 后端：`https://hzfw.njpkzyy.com:18086`
- 签名：`sign = SHA1(hex(MD5(appKey + timestamp + nonce)))`，appKey=`1202patient`
- 查询类 AGENT_ID：`6396cb2be4b0dc1899f48fe7`
- 在线号/挂号类 AGENT_ID：`62da65d4e4b0e0a247890d84`
- 微信小程序 appid：`wxca05bc9d9f69226c`
- 医院代码：`1202`
- 虾米平台：手机 App（com.xiami.host）连接腾讯云 140.143.144.28
