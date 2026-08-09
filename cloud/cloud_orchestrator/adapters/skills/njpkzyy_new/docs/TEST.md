# 南京市浦口区中医院 Skill 测试记录

## 已实测（源 skill 在 Skill 工作台审核区实测，2026-08-06）
- **查科室**：/api/public/basic/v3/depts 两级结构（pid 分组）与小程序页面一致
- **午别编码**：/api/public/v3/noon_code
- **科室医生**：/api/public/v3/dept/doctor/{dept_code}
- **可约日期**：/api/public/v3/schedule/check（默认今天~+7天）
- **排班**：/api/public/v3/schedule（含 detail 时段）
- **在线号判断**：/api/public/v3/schedule/online/judge（ONLINE_AGENT_ID）
- **在线时段**：/api/public/v3/schedule/online/detail
- **支付渠道**：/api/public/v3/pay_channel → WX_JSAPI
- **登录**：POST /api/session/wechat/ma 微信授权（真人配合）
- **在线挂号**：POST /api/public/v3/register/online（⚠️真挂号，请求体完整破解，走微信支付）

## 待手机通道实测（吸收后）
- [ ] 手机 App 在线时，查询类走手机通道拿真数据
- [ ] 微信授权登录 → token 存手机凭据库
- [ ] 在线挂号端到端（须真人确认）
