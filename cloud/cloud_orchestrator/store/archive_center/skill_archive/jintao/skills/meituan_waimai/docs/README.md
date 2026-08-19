# 美团外卖（路径 B：只交美团 App 订单链接）

> 登录态、代下单、代支付全部砍掉。微信小程序 / H5 只探路。

## 三问（已定死）

| 问 | 答 |
|---|---|
| 探路用什么 | 微信缓存（wxapkg）挖**去缓存的 API**；H5 看店 |
| 登录态有什么 | **放弃**。真浏览器能过风控，我们内置浏览器过不了（mtgsig）；登录在美团 App 里 |
| 交付是什么 | `imeituan://www.meituan.com/takeout/food?poi_id=...`，壳原生拉起**美团 App** 进该店点餐页 |

## 为什么走 B

去缓存的 API 有，真浏览器甚至能下单。但过风控要**真实浏览器**，内置浏览器提交订单 403（mtgsig）；支付还锁微信 JSAPI。真 Chrome 能过 ≠ 我们能过 → 不冲 A，登录和支付全砍，只交美团 App 连接。

## 客户动作

搜店/看菜单 → 生成订单 scheme → 点一下 → 美团 App 弹出该店 → 客户自己登录、下单、付钱。

壳：Android `Intent` + `package=com.sankuai.meituan`；iOS `openURL`（声明 `imeituan`）。禁止丢进 WebView。未装美团可试外卖 App scheme（`meituanwaimai://`）；都没有才应用商店。

禁止只给美团首页。
