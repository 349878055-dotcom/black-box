# Skill 功能包 · nj12320_register（12320 执行预约 / 挂号）

> 三 skill 闭环第 2 环：排班页点可约时段 → 登录检测（未登录引导登录）→ 预约确认页 → 填就诊人 → 验证码真人配合 → 提交（真提交需用户确认）。
> ⚠️ 本 skill 涉及**真预约（有副作用）**：无登录态 + 需验证码真人 + 需用户确认，故默认**不自动提交**。

## 这是什么

接在 [`nj12320_doctor_query`](../nj12320_doctor_query/README.md)（查可约时间）之后：
告诉客服「医院 + 医生 + 想约的日期/时段」→ 客服在排班页点「预约」→ 若未登录弹出
「您还没有登录或登录已超时，请先登录！」→ 引导登录（账号密码 + 图形验证码真人）→
登录后到达预约确认页 `hos_toConfirm.do` → 填就诊人信息 → 提交前验证码真人 + 用户确认。

## 包结构

```
nj12320_register/
  main.py     硬编码：导航→排班解析→点预约→登录检测→引导登录→确认页
  meta.json   表格：医院/医生/科室/时段 + 可选登录态/就诊人字段
  README.md   接口说明（本文件）
```

## 表格（meta.json 字段）

| 字段 | label | 必填 | 说明 |
|---|---|---|---|
| `hosname` | 医院名称 | ✅ | 如：南京鼓楼医院 |
| `docname` | 医生姓名 | ✅ | 如：李洁 |
| `depname` | 科室名称 | — | 加快定位 |
| `when` | 想约日期/时段 | — | 如：周五上午；留空=最近可约 |
| `username`/`password` | 12320 账号密码 | — | 未登录时用于自动登录（验证码真人） |
| `patient_name`/`patient_idnum`/`patient_phone` | 就诊人信息 | — | 确认页填表（代人预约） |

## 页面链路（2026-08-04 curl/Playwright 实测）

| 步骤 | 页面/接口 | 关键点 |
|---|---|---|
| 医院→科室→医生 | hos_search → hos_showReservation → dep_detail → **doc_detail** | 复用查询 skill 导航 |
| 排班表 | doc_detail 排班表：7 列=日期、行=上午/下午 | 可约格子内 `<a onclick="toconfirm(schcode,docid,hoscode)">预约</a>`（id 前缀 `yuyue_{schcode}`）；已满=`<span class="doc_yiman">已满</span>`；空=未放号 |
| 点「预约」 | 触发 `toconfirm` → POST `reservationJson/checkResRule.do` {schcode} | `noLogin`→弹「您还没有登录…请先登录！」（#to_cssb）；`noPhone`→「您还没有完善手机号码」（#to_cssph）；`error`→预约限制；`success`→form.submit→`hos_toConfirm.do` |
| 登录检测 | 点预约后轮询 | 出现「您还没有登录」→未登录；URL 含 `hos_toConfirm`→已登录 |
| 引导登录 | `/njmine/showLoginUI.do` | `username`/`password`/`verifyCode`(图形码 authImg.do) + a 按钮 `submitLogin()` |
| 预约确认页 | `hos_toConfirm.do?schcode=...` | 未登录直接访问会被踢回挂号页；登录后到达，填就诊人→验证码→提交 |

## 登录检测（核心）

- 点「预约」后轮询页面文本：
  - 「您还没有登录或登录已超时」→ **未登录** → 引导登录（或提示用户登录后重跑）
  - URL 含 `hos_toConfirm` → **已登录** → 到确认页
- 未登录直接访问 `hos_toConfirm.do` 也会被踢回（登录检测生效）

## 填表兼容（两端差异关键）

- **电脑端 fill = 当前焦点框**（focused 优先）；**手机端 fill = 按 DOM 顺序**。
- skill 统一用「**先 `key_press("Tab")` 再 `fill()`**」：电脑端 Tab 移动焦点、手机端无害且按序 → 两端填表一致。
- 登录页/确认页多字段填表均走此策略。

## 调试 / 发布

```bash
# 电脑端验证（headless；无登录态 → 走到「排班解析 + 点预约 + 登录检测」即达标，不真提交）
python -m skill_maker.pc_run nj12320_register --fields '{"hosname":"南京鼓楼医院","depname":"产科","docname":"李洁"}' --auto
# 带想约时段
python -m skill_maker.pc_run nj12320_register --fields '{"hosname":"南京鼓楼医院","docname":"李洁","when":"周五上午"}' --auto
# 发布（会部署云端）
python skill_maker/publish.py nj12320_register
```

> 电脑端验证目标 = **跑到「排班页展示可约时段 + 点预约 + 登录检测」阶段**（无登录态时检测到「请先登录」即算成功）；真提交留到用户在场（登录 + 验证码 + 确认）。

## 注意

- **不自动真提交**：提交 = 登录态 + 图形验证码真人 + 用户明确确认，三缺一不可（铁律）。
- 无号（全部已满/未放号）时 skill 会如实报告，不硬点。
- 目标时段「精确点击」受 SkillDriver 接口限制（只能按文本点第一个「预约」），如需指定具体日期时段，由用户/客服在页面手动点选（wait_human 人工辅助），skill 负责登录检测与后续。
- JSON 发布前必须 `status=verified`、`steps=[]`。

## 注册挂接（重要）

**「注册」挂在预约脚本下**：点预约若未登录（弹「您还没有登录」）→ register 自动触发注册流程
（复用 `nj12320_signup` 的 run：自动填表 + 验证码真人 + 立即注册）→ 注册成功跳到登录页。
**没触发就不用注册**（已登录/有账号直接约）。注册邮箱/密码在需要时 `ask` 客户
（`signup_email`/`signup_password` 字段可后补），姓名/证件/手机复用就诊人信息。
