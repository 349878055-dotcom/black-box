# 美团外卖 Skill（meituan_waimai）—— 唯一说明文档

> **以 2026-08-12 真机实测为准**。所有结论来自真机验证，不含未验证推断。
> 历史调试中间结论（"工程师太忙"/F404/IP地域 等）已被最终实测推翻，一律不采纳。

## 一、能力与实测状态

| 环节 | 实现方式 | 实测状态 |
|---|---|---|
| 搜店/看菜单 | **浏览器 H5**（`h5.waimai.meituan.com`） | ✅ 已通 |
| 登录 | 手机号+验证码（H5，`18913300200`） | ✅ 已通 |
| 加购/购物车 | 浏览器 H5 | ✅ 已通 |
| 结算预览 | `i.waimai.meituan.com/openh5/order/v2/preview` | ✅ 200 |
| **提交订单** | `i.waimai.meituan.com/openh5/order/v2/submit` | ❌ **403** |
| 查单 | `wx-shangou.meituan.com/wxapp/v1/order/getuserorders` | ✅ 200 `[]` |
| **支付** | 微信小程序 JSAPI（`wx.requestPayment`） | ❌ 虾米 WebView 无法触发 |

**结论**：看店/菜单/加购/结算/查单 已通；**提交订单被 openh5 风控拦（403）**；**支付必须真微信环境**。

## 二、域名（实测确认）

| 域名 | 用途 | 实测 |
|---|---|---|
| `h5.waimai.meituan.com` | H5 页面（唯一 H5 入口） | ✅ 打开 |
| `i.waimai.meituan.com` | H5 后端（openh5）：preview 200 / **submit 403** | ✅/❌ |
| `wx.waimai.meituan.com` | 微信小程序（weapp）：submit/pay **200**（PC微信） | ✅ |
| `wx-shangou.meituan.com` | 小程序业务（wxapp）：getuserorders 200 / **search 403** | ✅/❌ |
| `web.meituan.com` | 无效入口 | 404 |

## 三、核心结论（实测为准，无冲突）

1. **提交订单 403 根因 = openh5 通道 mtgsig 风控签名**（绑定浏览器指纹），虾米 WebView 算不出有效签名。
   - 已排除：UA（wv/browser）、指纹伪装、注入、餐具未选 —— 均仍 403。
   - **走 weapp 通道（真微信）能下单**（`wx.waimai.meituan.com/weapp/v6/order/submit` 实测 200，海外 IP 也行）。
2. **支付 = 微信小程序 JSAPI**（`wx.requestPayment`），必须真微信；虾米 WebView 无法触发。
3. **搜店 API 被 403 拦**，实际靠浏览器 H5 实现。
4. **登录态**：H5 cookie（openh5）/ 微信小程序态（weapp）/ App token 三通道**不互通**，别混用。

## 四、登录态

- **H5**：手机号 `18913300200` + 验证码；cookie 存凭据库 `meituan_waimai`（含 userId/u/token/JSESSIONID）
- **微信**：真微信环境登录态（PC 微信实测可下单）
- **App**：真机美团 App 登录 + 抓通信拿 token/uuid（后期方向）
- **坑**：别删 dfp 设备指纹；位置需 pickedpoi/geopoi（海外 mock 南京雨山美地 32.055946,118.607651）

## 五、环境坑（实测速查）

| 坑 | 解法 |
|---|---|
| 默认 UA 进店菜单"出现点问题" | 用**微信 UA**（交易环节必需） |
| onPageStarted 注入 JS 破坏 H5（首页"网络不给力"） | 用 **eval 按需注入** mock 定位 |
| JS 模拟点击对按钮无效 | 需**真实触摸**（isTrusted=true） |
| 海外手机拿不到国内定位 | eval 注入 mock 定位 |
| 清缓存破坏美团 | 只清购物车/订单类，**别删 dfp** |

## 六、后续方向（以"客户只点支付确认"为目标）

- **下单/支付**：API 生成订单链接 → 返回客户 → 客户微信/Safari 打开 → 确认订单+支付（客户唯一动作）
- **自动下单暗号**：unidbg（`irabbit666666/unidbg-mt-server23`）服务端生成 mtgsig（App 版），或走 weapp 通道
- **登录态**：App 版 token（真机美团 App 登录 + 抓通信）

## 七、环境信息

- 远程云端：`140.143.144.28`，端口 19000，systemd `shimeban-cloud.service`
- 虾米账号：`349878055@qq.com`（设备通道键同账号）
- 应用日志：远程 `/home/ubuntu/xiami/cloud/service.log`

## 八、使用流程（老百姓视角）

问（想吃什么/哪家店）→ 查（H5 搜店→菜单）→ 手机号验证码登录 → 加购→结算（已通）→ 生成订单链接 → 客户打开确认+支付。
