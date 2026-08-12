# 美团外卖 Skill（meituan_waimai）—— 唯一说明文档

> 本文件是美团 skill 的**唯一**文档：能力 / 登录态 / 接口反馈 / 核心难点 / 使用流程 / 环境。
> （其他美团相关文档已合并进本文件并删除，避免多文档不一致。）

## 一、能力（capability = operate_sms）

| 环节 | 方法 | 状态 |
|---|---|---|
| 搜店/看菜单 | `search_poi` / `get_poi_info` / `get_product_list` / `get_product_detail` | 查询已通（浏览器H5） |
| 登录 | `login_apply` → `login` | ✅ 手机号+验证码已通（H5） |
| 下单 | `sync_cart` / `get_cart_info` / `get_address_list` / `preview_order` / `submit_order` | 加购/结算已通；**submit 被拦** |
| 查单/取消 | `get_orders` / `get_order_detail` / `cancel_order` | ✅ `get_orders` 已通（返回[]） |

**一句话现状**：看店/菜单/加购/结算预览已打通；**下单 submit 403**；**支付必须真微信**。

## 二、接口来源 / 域名体系（4 个真实后端）

- **来源**：微信小程序 wxapkg 解包（appid `wxde8ac0a21135c07d` v1563）
- 登录：`passport.meituan.com`（`mobileloginapply` 发码 → `mobilelogin` 登录，云端可直连 HTTP 200）
- 登录链失败结构：`{"error":{"code","message","type"}}`

| 域名 | 用途 |
|---|---|
| `h5.waimai.meituan.com` | H5 页面（唯一 H5 入口；`waimai.meituan.com`/`i.waimai.meituan.com/home` 都跳它） |
| `i.waimai.meituan.com` | **H5 后端 API（openh5）**：preview 200 / submit 403 |
| `wx.waimai.meituan.com` | **微信小程序 API（weapp）**：PC 微信真实通道，下单/支付 200 |
| `wx-shangou.meituan.com` | 小程序业务 API（wxapp）：getuserorders 200 / search 403 |
| `web.meituan.com` | 无效入口（404） |

## 三、登录态（三通道不互通，重点）

| 通道 | 形态 | 用途 | 状态 |
|---|---|---|---|
| H5（openh5） | cookie（userId/u/token/JSESSIONID） | 看店/菜单/加购/结算 | ✅ 已通 |
| 微信小程序（weapp） | 微信 openid + 小程序态 | 下单/支付（JSAPI） | ✅ PC微信已通 |
| 美团 App | App token/uuid（wm_uuid/msid） | 直接调 App API（需 mtgsig） | 后期方向 |

- **H5 账号**：手机号 `18913300200`，验证码登录；cookie 存凭据库 `meituan_waimai`
- **坑**：三通道不互通；**别删 dfp 设备指纹**（删了美团 H5 接口异常）；位置要 pickedpoi/geopoi（mock 南京雨山美地）；App token 靠真机登录+抓通信

## 四、接口反馈（逐条实测）

**✅ 200：**
- `wx-shangou.../wxapp/v1/order/getuserorders` → 订单查询 `[]`
- `i.waimai.../openh5/order/v2/preview` → 结算预览 `code:0`
- `wx.waimai.../weapp/v6/order/submit` + `weapp/v1/payment/pay` → PC微信下单+支付

**❌ 403 / 9999：**
- `wx-shangou.../wxapp/v2/search/v9/poiwithfilter`、`/search/v8/suggest` → 403（search 系整体拦）
- `wx-shangou.../wxapp/v2/poi/homepage` → code:9999（cookie 域/参数）
- **`i.waimai.../openh5/order/v2/submit` → openresty 403（核心卡点）**

**submit 请求细节**：头带 `mtgsig`（a1~a10/x0/d1）；body `optimus_code=10&optimus_risk_level=71&data={wm_poi_id,poi_id_str,foodlist[skuId],preview_order_callback_info}`。

## 五、核心难点（3 个）

### 1️⃣ 下单 submit 403（最关键）
- 根因：openh5 submit 的 **mtgsig 风控签名**（绑定浏览器指纹/IP），虾米 WebView 算不出有效签名 → 403
- 排除过：wv UA / browser UA / 指纹伪装 / onPageStarted 注入 / 餐具未选 —— 全试过仍 403
- 打通路：**weapp 通道（真微信）** `wx.waimai.meituan.com/weapp/v6/order/submit` 已验证 200（海外 IP 也行）；或 **unidbg**（`irabbit666666/unidbg-mt-server23`）服务端生成 mtgsig 直连 App API

### 2️⃣ 支付 JSAPI（必须真微信）
- 支付 = `wx.requestPayment`（微信小程序原生 JSAPI），**虾米 WebView 触发不了**
- 方案：**API 生成订单链接 → 返回客户 → 客户微信/Safari 打开 → 确认订单+支付**（客户唯一动作）

### 3️⃣ 登录态三通道不互通
- H5 cookie / 微信小程序态 / App token 各管各的；App 版 token 需真机登录+抓包

## 六、环境坑速查

| 坑 | 解法 |
|---|---|
| 默认 UA 进店菜单"出现点问题" | 用**微信 UA**（交易环节必需） |
| onPageStarted 注入 JS 破坏美团 H5（首页"网络不给力"） | 用 **eval 按需注入** mock 定位 |
| JS 模拟点击（dispatchEvent）对按钮无效 | 需**真实触摸**（isTrusted=true） |
| 清缓存破坏美团 | 只清购物车/订单（cached_cart/oldOrder），**别删 dfp** |
| 海外手机拿不到国内定位 | 注入 mock 定位（南京雨山美地 32.055946,118.607651） |

## 七、下单请求体（骨架，待真机补全）

```
wxapp_base_data（风控 jsguard）+ data{
  wm_poi_id, poi_id_str, foodlist(购物车菜品), user_id, wm_order_pay_type:"2",
  recipient_name/address/phone/gender/house_number, addr_id, addr_longitude/latitude,
  caution(备注), token(购物车), coupon_view_id, ...
}
```
⚠️ 下单接口双版本：`/order/submit` 与 `/weapp/v1/order/submit`（真机确认后固定）。

## 八、使用流程（老百姓视角）

问（想吃什么/哪家店）→ 查（搜店→菜单→菜品）→ 手机号验证码登录 → 下单（加购→结算→提交，编码系统补齐）→ 查订单/取消。

## 九、环境信息

- 远程云端：`140.143.144.28`，systemd `shimeban-cloud.service`，端口 19000
- 虾米账号：`349878055@qq.com`；手机设备通道键同账号
- 应用日志：远程 `/home/ubuntu/xiami/cloud/service.log`

## 十、后续方向

- 登录态：App 版 token（真机美团 App 登录 + 抓通信拿 token/uuid）
- 下单/支付：API 生成订单链接 → 客户微信/Safari 打开确认+支付
- 自动下单暗号：unidbg 服务端生成 mtgsig（App 版），或走 weapp 通道
