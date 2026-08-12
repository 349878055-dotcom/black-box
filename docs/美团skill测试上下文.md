# 美团外卖 Skill（meituan_waimai）测试上下文

> 供新窗口/新会话交接用：目标 = **重点测试美团外卖 skill** 全链路。

## 一、现状（已完成，可直接测）

- ✅ 已从「工作台3.0」吸收到本项目：`cloud/cloud_orchestrator/adapters/skills/meituan_waimai/`（2026-08-11 同步最新版）
- ✅ 已补 `login` 配置（`sms_verify` 手机号+验证码），走云端 `login_flow` 通用登录编排
- ✅ 已部署到远程云端（140.143.144.28），health OK，美团注册成功（14 方法，login=sms_verify）
- ✅ agent `_direct_login` 已支持美团（说"登录美团外卖/美团"会直通触发登录）

## 二、美团能力

| 环节 | 方法 | 说明 |
|---|---|---|
| 搜店/看菜单 | `search_poi` / `get_poi_info` / `get_product_list` / `get_product_detail` | 公开查询；`search_poi` 已定位到 `apimobile.meituan.com/group/v4/poi/search/miniprogram/{city_id}` |
| 登录 | `login_apply` → `login` | 手机号+验证码（真人收码，可能先过 yoda 滑块/图形验证） |
| 下单 | `sync_cart` / `get_cart_info` / `get_address_list` / `preview_order` / `update_order_container` / `submit_order` | ⚠️真操作，须用户确认 |
| 查单/取消 | `get_orders` / `get_order_detail` / `cancel_order` | 需登录 |

- **接口来源**：微信小程序 wxapkg 解包（appid `wxde8ac0a21135c07d` v1563）
- **域名**：业务 `i.waimai.meituan.com`；登录 `passport.meituan.com`；搜索 `apimobile.meituan.com`
- **登录链**：`POST /api/v3/account/mobileloginapply`（发验证码）→ `POST /api/v3/account/mobilelogin`（登录）→ token 存手机凭据库（`refresh_token` 续期）

## 三、测试步骤建议（按顺序）

1. **登录**：手机 App 对话里说 `登录美团外卖，手机号 18912926603`
   → 应直通触发 `login_flow`：要手机号 → （若有滑块/图形验证则看图输入）→ 发短信 → 输验证码 → token 存手机
   → 观察：手机聊天是否显示图形码/提示、手机是否收到短信、登录是否成功
2. **搜店**：`搜索 附近的奶茶店` / `搜索 XXX 店` → 验证 `search_poi`（**接口新定位，待真机验证**）
3. **看菜单**：`看 XX 店的菜单` → `get_product_list` / `get_product_detail`
4. **下单**：加购 → 结算预览 → 提交订单（⚠️先确认，真操作）
5. **查单/取消**：`我的订单` / 取消订单

## 四、已知注意点（务必知道）

1. **api 状态更新（2026-08-11 实测）**：
   - `login.py`：**passport.meituan.com 登录接口云端可直连**（HTTP 200，非 403）→ 登录可能不用走手机通道
     - 失败返回结构 = `{"error": {"code", "message", "type"}}`（如空号 → `{"error":{"code":101012,"message":"请输入正确的手机号","type":"user_err_mobile_inval"}}`）
     - 登录参数方向：mobile + 验证码 + 可能 ticket（票据）；验证码前可能过滑块/图形
   - `search_poi`：已定位到 `apimobile.meituan.com/group/v4/poi/search/miniprogram/{city_id}`（调用在 search/pages/before-search），参数待真机验证
   - `submit_order`：请求体已从 wxapkg `order-submit-param.js` 还原（`wxapp_base_data` 风控 + `data{wm_poi_id, foodlist, user_id, recipient_*, addr_id, token...}` + `foodlist`）
   - 其余参数/请求头/签名仍待真机验证（禁 mock，以手机通道真实响应为准）
2. **yoda 滑块/图形验证风控**（`risk_app=216` + 设备指纹 uuid）：**业务/下单必须走手机通道**（Device-as-Proxy）；登录接口实测云端可直连，但业务接口云端直连仍可能被拦
3. **真下单有副作用**（占单/可能扣款），提交前须用户确认；支付在手机端完成
4. 登录/下单需真人配合收短信、过滑块；**这是 operate_sms 能力**（非微信独占授权）
5. **⚠️ 手机端隐患**：蓝图 `deviceid: {{deviceid}}` 占位符在 `SkillExecutor.replaceHeaderPlaceholders()` 未替换（只处理 timestamp/nonce/sign/token/api_key/session_id），真机会把字面量 `"{{deviceid}}"` 原样发出；若美团风控要验 deviceid，真机测试可能失败——待确认
6. **下单接口双版本**：`/order/submit` 与 `/weapp/v1/order/submit`（wxapkg 接口表两者都有），真机验证确认用哪个后固定

## 五、环境信息

- 远程云端：`140.143.144.28`，systemd 服务 `shimeban-cloud.service`，端口 19000
- 虾米账号：`349878055@qq.com` / 密码 `jintao0341`
- 手机设备通道键：`349878055@qq.com`（App 在线即 device 在线）
- 远程 SSH：`ubuntu@140.143.144.28`，密码 `Jtao_8505`
- 应用日志：远程 `/home/ubuntu/xiami/cloud/service.log`

## 六、相关文件

- skill：`cloud/cloud_orchestrator/adapters/skills/meituan_waimai/`
  - `contract.json`（含 login 配置）/ `register.py`（透传 login）
  - `api/_base.py`（常量/蓝图）/ `api/login.py`（登录，含实测记录）/ `api/query.py`（搜索/菜单）/ `api/order.py`（下单/订单，含 submit 请求体）
- 云端登录编排：`cloud/cloud_orchestrator/core/login_flow.py`
- agent 登录触发：`cloud/cloud_orchestrator/core/agent.py`（`_direct_login` / `_ensure_login`）
- 部署工具：`tools/deploy_meituan.py`（美团 skill）、`tools/deploy_agent_glyy.py`（agent/login_flow/skill 配置）
- 文档：`cloud/cloud_orchestrator/adapters/skills/meituan_waimai/docs/README.md`（骨架说明）
- 来源（工作台3.0）：`/home/jintao/桌面/工作台3.0/skills/meituan_waimai/`（权威源）；`cloud/knowledge/产出/meituan_waimai/`（产出副本）

## 七、登录触发链路（测试时对照）

```
用户说「登录美团外卖，手机号 xxx」
  → agent._direct_login 命中 meituan_waimai（确定性代码，非 AI）
  → _ensure_login → login_flow.run_login（读 contract.login 配置，sms_verify）
  → login_apply（发短信，可能需滑块/图形）→ 用户输码 → login → token 存手机
业务撞出 need_login → 系统自动触发同样登录 → 重试业务
```

## 八、登录请求格式（实测确认）

**① 发短信验证码 `login_apply`**：`POST https://passport.meituan.com/api/v3/account/mobileloginapply`
- 请求头：`User-Agent`(微信 UA) / `Content-Type: application/json` / `deviceid` / `timestamp` / `nonce`（登录接口 `bearer=False` 不带 token）
- 请求体（JSON）：`{"mobile": "18912926603"}`

**② 验证码登录 `login`**：`POST https://passport.meituan.com/api/v3/account/mobilelogin`
- 请求体（JSON）：`{"mobile": "18912926603", "verifyCode": "123456"}`
- 成功 → 手机端按蓝图 `store` 回写 `data.access_token` / `data.refresh_token` / `data.expires_in` 到本地凭据库（target=`meituan_waimai`）
- 失败结构：`{"error": {"code", "message", "type"}}`

**③ 续期（可选）`refresh_token`**：`POST https://passport.meituan.com/refresh_token`（字段名待真机验证）
