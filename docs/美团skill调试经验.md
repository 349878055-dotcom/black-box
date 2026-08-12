# 美团外卖 Skill · 调试经验总结（登录态 + 接口反馈）

> 目的：沉淀 2026-08-11~12 真机调试的全部经验，重点 = **登录态** 与 **每个接口的反馈**。
> 后续开发主要围绕：登录态获取/复用、各通道接口反馈、支付触发方式。
> 关联：[`美团skill真机测试进度.md`](美团skill真机测试进度.md)（实时进度）、[`美团skill测试上下文.md`](美团skill测试上下文.md)（交接）

---

## 一、登录态（核心）

### 1.1 通道与形态（重要区分）
美团有**三种登录态/通道**，互不相同，别混用：

| 通道 | 登录态形态 | 获取方式 | 用于 |
|---|---|---|---|
| **H5 网页（openh5）** | cookie（`userId/u/token/JSESSIONID` 等） | 虾米浏览器手机号+验证码登录 | 看店/菜单/加购/结算预览 |
| **微信小程序（weapp）** | 微信 openid + 小程序登录态 | **真微信环境**（PC微信/手机微信） | 下单/支付（JSAPI） |
| **美团 App** | App token/uuid（`wm_uuid/msid` 等设备参数） | 真机美团 App 登录 | 直接调 App 版 API（需 mtgsig） |

**关键**：三个通道登录态**不互通**。H5 cookie 不能用在小程序/App 接口，反之亦然。

### 1.2 H5 登录态（已打通）
- **账号**：手机号 `18913300200`（选城市北京 `w_cid=110100/w_cpy=beijing`；后续 mock 定位用南京雨山美地）
- **登录方式**：虾米内置浏览器 → `h5.waimai.meituan.com` → 手机号+验证码（sms: 协议已在 App 拦截不崩页）
- **存储**：已导出到手机凭据库 `meituan_waimai`
  - `token_..._meituan_waimai` = access_token
  - `cookie_..._meituan_waimai` = 完整 cookies（含 token/uuid/userId/JSESSIONID）
- **复用**：SkillExecutor 自动带 token；H5 浏览器登录态存在 WebView cookie/localStorage（pickedpoi/geopoi 位置、addstore 地址）

### 1.3 登录态关键坑
1. **别删 dfp 设备指纹**（dfpId/dfp_params_list/dfp_idb_token）——删了美团 H5 接口异常；只该清购物车/订单缓存（cached_cart_data/oldOrder/orderCreate/deliverypoi）
2. **位置数据**：H5 需要 `pickedpoi/geopoi`（雨山美地 32.055946,118.607651），海外手机需注入 mock 定位
3. **App 版登录态**：需真机美团 App 登录抓 token（沙盒读不出，靠抓通信）

---

## 二、接口/域名反馈（重点，逐条实测）

### 2.1 域名体系（4 个真实后端）
| 域名 | 用途 | 备注 |
|---|---|---|
| `h5.waimai.meituan.com` | H5 页面（唯一 H5 入口） | 跳 `waimai.mindex/home`；`waimai.meituan.com`/`i.waimai.meituan.com/home` 都跳它 |
| `i.waimai.meituan.com` | **H5 后端 API（openh5）** | `openh5/order/v2/preview`（200）、`openh5/order/v2/submit`（403） |
| `wx.waimai.meituan.com` | **微信小程序 API（weapp）** | PC 微信真实通道；`weapp/v6/order/submit`（200）、`weapp/v1/payment/pay`（200） |
| `wx-shangou.meituan.com` | 小程序业务 API（wxapp） | `wxapp/v1/order/getuserorders`（200）；search 系 403 |
| `web.meituan.com` | 无效入口 | 404 / Whitelabel Error |

### 2.2 逐接口反馈表

#### ✅ 已通（200）
| 接口 | 方法 | 结果 | 说明 |
|---|---|---|---|
| `wx-shangou.meituan.com/wxapp/v1/order/getuserorders` | GET | 200 `[]` | 订单查询，手机通道+token 全链路通 |
| `i.waimai.meituan.com/openh5/order/v2/preview` | POST | 200 `code:0` | 结算预览（商品/地址/金额/coupon 全正常） |
| `wx.waimai.meituan.com/weapp/v6/order/submit` | POST | 200 | PC 微信下单成功（`call_type=0&ui=<userId>&region_id=`） |
| `wx.waimai.meituan.com/weapp/v1/payment/pay` | POST | 200 | PC 微信拿支付参数 → `wx.requestPayment` |

#### ❌ 被拦（403 / 9999）
| 接口 | 方法 | 结果 | 原因 |
|---|---|---|---|
| `wx-shangou.meituan.com/wxapp/v2/search/v9/poiwithfilter` | POST | **403** | search 系被 openresty 整体拦（需完整小程序签名） |
| `wx-shangou.meituan.com/wxapp/v1/search/v8/suggest` | GET | **403** | 同 search 系 |
| `wx-shangou.meituan.com/wxapp/v2/poi/homepage` | GET | 不 403 但 **code:9999** | 首页店铺列表，疑 cookie 域不匹配/缺参数 |
| `apimobile.meituan.com/group/v4/poi/search/miniprogram/1` | GET | **403** | 路径错（旧接口） |
| `i.waimai.meituan.com/openh5/order/v2/submit` | POST | **openresty 403** | **核心卡点**：mtgsig 签名无效 + 环境（详见下） |

#### ⚠️ 页面/其他
| 项 | 结果 |
|---|---|
| `h5.waimai.meituan.com/waimai/mindex/home` | 可打开，需定位（mock 南京）；默认UA能看店，进店菜单需微信UA |
| 菜单页 `mindex/menu` | 默认 UA "出现点问题"；微信 UA 正常（19~11 spu） |
| 结算页 `mindex/preview` | 正常（合计¥44.8 塔斯汀 / ¥35.2 等） |
| 订单列表 `mindex/olist` | 正常（显示历史订单） |
| `web.meituan.com` | 404 Whitelabel |

### 2.3 submit 403 根因（最关键结论）
```
POST i.waimai.meituan.com/openh5/order/v2/submit
→ 请求头带 mtgsig（a1~a10/x0/d1 风控签名）
→ body: optimus_code=10&optimus_risk_level=71&data={wm_poi_id,poi_id_str,foodlist[skuId],preview_order_callback_info}
→ 仍 openresty 403
```
- **排除**：wv UA、browser UA、指纹伪装、onPageStarted 注入、餐具未选 —— 全试过仍 403
- **根因**：openh5 submit 的 **mtgsig 签名绑定浏览器指纹/IP 环境**，虾米 WebView 无法生成有效签名 → 403
- **对比**：weapp 通道（真微信）`wx.waimai.meituan.com/weapp/v6/order/submit` → **200 成功**（海外 IP 也行）
- **结论**：**"走 weapp 通道（真微信）能下单"；"openh5 通道（虾米）被 mtgsig 拦"**。支付是 JSAPI（`wx.requestPayment`）必须真微信。

### 2.4 支付（定论）
- 美团外卖支付 = **微信小程序原生 JSAPI**（`wx.requestPayment`），必须真微信环境
- 虾米 WebView **无法触发**（无微信 SDK）→ 支付必须在真微信/真浏览器完成
- 后期方向：**API 生成订单链接 → 返回客户 → 客户微信/Safari 打开 → 确认订单+支付**（客户唯一动作）

---

## 三、环境/浏览器关键经验

1. **微信 UA 必需**（交易环节）：菜单/加购/结算要微信 UA；默认 UA 进店菜单报"出现点问题"
2. **browser UA（去 `; wv`）**：submit 可发请求（不再 F404），但美团 H5 前端 JS 可能不初始化（首页接口空）——两难
3. **onPageStarted 注入 JS 会破坏美团 H5**（首页"网络不给力"）→ 必须**页面加载后用 eval 按需注入** mock 定位
4. **mock 定位**：海外手机注入南京坐标（`onPageStarted` 不可行，改 eval 注入）
5. **JS 模拟点击（dispatchEvent）对美团按钮无效**（isTrusted=false 被拒）→ 按钮操作需真实触摸/用户
6. **缓存清理**：只清购物车/订单类（cached_cart/oldOrder/orderCreate/deliverypoi），**别删 dfp**

## 四、下一步（用户方向）
- **登录态**：App 版登录态（真机美团 App 登录 + 抓通信拿 token/uuid）
- **下单/支付**：API 生成订单链接 → 返回客户 → 客户微信/Safari 打开确认+支付
- **自动下单暗号**：unidbg（`irabbit666666/unidbg-mt-server23`）服务端生成 mtgsig 2.3（App 版），或走 weapp 通道
