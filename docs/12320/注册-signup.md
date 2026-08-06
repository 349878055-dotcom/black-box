# Skill 功能包 · nj12320_signup（12320 注册账号）

> 三 skill 闭环第 3 环：用户说「注册太复杂不会填」→ 自动填注册表单（showRegUI.do）→ 图形验证码真人 → 提交（真注册需用户确认）。
> ⚠️ 真注册有副作用（占用户名/手机号），本 skill 默认**不自动提交**，需用户明确确认。

## 这是什么

12320 注册表单字段多（16 项）、必填校验严、还有日历生日 + 图形验证码，用户觉得太复杂。
本 skill：用户只提供**邮箱、密码、真实姓名、出生日期、证件号、手机号**（其余有默认值），
客服自动填表 → 用户看验证码图片输入 → 确认后提交 → 注册成功跳实名认证。

## 包结构

```
nj12320_signup/
  main.py     填表逻辑（fill_field 精确填）+ 验证码真人 + 提交检测
  meta.json   字段定义（邮箱/密码/姓名/生日/证件/手机/区县…）
  README.md   接口说明（本文件）
```

## 注册表单摸底（showRegUI.do，2026-08-04 curl 实测）

| name | id | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `patient.email` | email | text | ✅ | 用户名，AJAX 查重 |
| `patient.password` | password | password | ✅ | 密码 |
| `repassword` | repassword | password | ✅ | 确认密码（8~16，等于密码） |
| `patient.name` | name | text | ✅ | 真实姓名 |
| `patient.gender` | — | radio | ✅ | 男=0(默认)/女=1 |
| `patient.birthday` | birthday | text readonly+日历 | ✅ | 出生日期（Calendar 控件，readonly） |
| `patient.idtype` | idtype | select | ✅ | 身份证0/护照2/… |
| `patient.idnum` | idnum | text | ✅ | 证件号（大写） |
| `patient.homephone` | homephone | text | ✅ | 手机号（按手机校验，收短信） |
| `patient.mobile` | mobile | text | — | 移动电话 |
| `patient.city` | — | radio | ✅ | 南京市民 是=0(默认)/否=1 |
| `patient.area` | area | select | — | 玄武1/鼓楼2/…/非南京0 |
| `patient.address` | address | text | — | 地址 |
| `patient.linkman` | linkman | text | — | 联系人 |
| `patient.linkmanpho` | linkmanpho | text | — | 联系人电话 |
| `verifyCode` | verifyCode | text | ✅ | **图形验证码** `/njmine/authImg.do`（真人看） |
| `isAgree` | isAgree | checkbox | ✅ | 同意协议 |

提交：`<a id="r_submit" onclick="checkAgree()">立即注册</a>` → AJAX `POST /njmine/indexJson/register.do?ajax=true`
→ 成功弹「注册成功！」→ 跳 `gotoSMRZ.do`（实名认证）→ `showLoginUI.do`。

## 填表方式（两端差异处理）

- **电脑端**：`PcSkillDriver.fill_field(name/id, value)` 按字段精确定位填值（含 readonly 生日用 JS 设值兜底）
  ——解决 `fill()` 只填当前焦点框、多类型表单（radio/select 夹在中间）错位的问题。
- **手机端**：无 `fill_field`（ScriptSkillDriver），fallback `fill+Tab` 按 DOM 顺序，但**多类型长表单不可靠
  （根因 D5）** → skill 提示人工辅助，待手机端修复后可自动。

## 调试 / 发布

```bash
# 电脑端验证（headless；填表到「表单已填好」即达标，不真提交）
#   --answers 提供验证码（ask 用）；confirm_submit 留空 → 不提交
python -m skill_maker.pc_run nj12320_signup \
  --fields '{"email":"test_user@example.com","password":"abcd1234","realname":"张三","gender":"男","birthday":"1990-01-01","idnum":"320102199001011234","homephone":"13800000000","city":"是","area":"鼓楼区"}' \
  --answers '{"验证码":"1234"}' --auto

# 发布（会部署云端）
python skill_maker/publish.py nj12320_signup
```

## 注意

- **不自动真提交**：默认填表后停在「已填好、待确认」；用户回复『确认提交』（或提供 verifyCode + confirm_submit=yes）才点「立即注册」。
- 验证码一律真人看（authImg.do 图片）；`--answers` 仅用于电脑调试模拟。
- 提交后检测：「注册成功！/gotoSMRZ/showLoginUI」→ 成功；「验证码…不正确/已存在/失败」→ 失败原因。
- 生日是 readonly 日历控件：电脑端 `fill_field` 用 JS 设值兜底；若失败提示人工点日历。
- JSON 发布前必须 `status=verified`、`steps=[]`。
