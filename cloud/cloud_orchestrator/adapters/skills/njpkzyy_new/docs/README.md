# 南京市浦口区中医院 Skill

挂号：查科室/医生/排班/可约日期/在线时段 → 微信授权登录 → 在线挂号（微信支付）→ 订单/就诊卡。

## 功能
- 查科室（两级结构）/医生/午别/可约日期/排班/在线号/时段/支付渠道（公开）
- 微信授权登录（真人配合）
- 在线挂号（⚠️真操作，需确认）
- 就诊卡 / 订单 / 订单商品详情
- 公告/协议

## 接口来源
- **电脑微信小程序真实抓包**（appid wxca05bc9d9f69226c，后端 hzfw.njpkzyy.com:18086）
- HTTP JSON；sign=SHA1(MD5(appKey+ts+nonce))；appKey=1202patient；agent_id=6396cb2be4b0dc1899f48fe7（在线号/挂号须用 62da65d4e4b0e0a247890d84）

## ⚠️ 重要事项
- **在线挂号是真实操作会占号**，提交前须用户确认
- **登录 = 微信小程序授权**（真人配合，App 不能代做微信授权）
- 查询类接口公开免登录；就诊卡/挂号/订单需登录态

## 登录态说明（核心难点）
- 登录需**真人配合**：在微信小程序「南京市浦口区中医院」内授权产生 code/encrypted_data/iv（一次性、会过期）
- 登录态 = Bearer access_token，存手机授权中心；过期需重新授权

## 原子化 + 编码自动补全（本 skill 的设计）
- 全部方法都是**原子单元**，依赖关系写在 `contract.json` 的 `provides` / `requires` / `match` / `pass_params` 里。
- **编码由系统自动补齐**：`register_online` 需要的 dept_code / doctor_code / schedule_id 等，系统自动现调 `list_depts` / `list_dept_doctors` / `get_schedule` / `get_medical_card`，**用用户/ AI 给的名字（科室名/医生名）精确匹配**后填入，AI 不需要抄编号。
- **匹配不到就明确报错**：如医生名在名单里找不到，skill_run 返回「未找到匹配项，请确认名称」，不会真的挂号。
- 科室两级结构：匹配时先 list_depts 锁定科室，再查医生/排班（禁止跳过前置直接编造编码）。

## 核心难点 / 坑（给维护者看）
1. 科室是**两级结构**：查医生/排班必须先有真实 dept_code；系统自动用科室名在 list_depts 里精确匹配（父子），匹配不到不编造
2. 在线号/挂号类接口必须用 ONLINE_AGENT_ID（62da65d4e4b0e0a247890d84），用普通 agent 返回「应用系统繁忙」
3. 接口需微信 UA + sign 签名（SHA1(MD5(appKey+ts+nonce))），错一个就失败
4. 签名类型复用手机端 `glyy_sha1_md5`，手机 SkillExecutor 已支持，无需改 App
5. 患者姓名/身份证不从接口返回（get_medical_card 只给 patient_code），需用户提供或问询

## 使用流程（老百姓视角）
问（要看哪个科/医生）→ 查（科室→医生→可约日期→排班→时段）→ 微信授权登录 → 提交（在线挂号，编码由系统补齐）→ 查订单/就诊卡。

## 使用要求
- 手机 App 在线
- 挂号需患者信息齐全（姓名/身份证/就诊卡）
