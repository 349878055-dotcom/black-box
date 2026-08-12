# 南京市浦口区中医院 Skill 变更记录

## v2.0.0（2026-08-08）原子化 + 前置依赖
- contract.json 补齐 `provides`/`requires`/`match`/`pass_params`：list_depts/get_schedule/get_medical_card 点破编码源头；register_online 的 11 个参数标注来源
- 系统自动按名字精确补齐编码（科室名/医生名匹配），匹配不到明确报错给 AI，AI 无需抄编号
- get_order 支持不传 order_id 返回订单列表

## v1.0.0（2026-08-07）
- 吸收自 Skill 工作台审核区 `njpkzyy_new`（新版，科室两级结构与页面一致）
- 打通：查科室/医生/排班/可约日期/在线号/时段/支付渠道
- 微信授权登录（真人配合）+ 在线挂号 + 就诊卡/订单
- 仅走手机通道（禁云端直连，复用手机端 glyy_sha1_md5 签名，无需改 App）
