# 美团外卖 Skill（meituan_waimai）

搜店铺/看菜单 → 手机号验证码登录 → 下单 → 查订单/取消订单。

## 能力（capability = operate_sms）
- 查询：**搜店**（`apimobile.meituan.com/group/v4/poi/search/miniprogram/{cityId}`）/ 店铺信息 / 菜单 / 菜品
- 登录：**手机号+验证码**（真人配合收码；可能需过 yoda 滑块/图形验证）
- 下单：加购 / 结算预览 / 提交订单（⚠️真操作须确认）→ 查单 / 取消 / 退款

## 接口来源
- **微信小程序 wxapkg 解包**（appid `wxde8ac0a21135c07d` v1563）
- 业务：`https://i.waimai.meituan.com`（weapp/v7/poi、order/*）；搜店：`apimobile.meituan.com`；登录：`passport.meituan.com`
- 登录链：`POST passport.meituan.com/api/v3/account/mobileloginapply`（发验证码）→ `/api/v3/account/mobilelogin`（登录）

## ⚠️ 重要事项
- **业务接口（apimobile/i.waimai）必须走手机通道**（Device-as-Proxy）：实测云端直连被 403/502 拦（风控 jsguard/设备指纹）
- **登录接口 passport.meituan.com 云端可直连**（实测 HTTP 200）——登录可能不用走手机通道
- **返回结构 = `{"error": {code, message, type}}`**（passport 失败时）；成功结构待真机验证
- **真下单有副作用**（占单/可能扣款），提交前须用户确认；支付在手机端完成

## 下单请求体（已从 order-submit-param.js 还原）
```
wxapp_base_data（风控 jsguard）+ data{
  wm_poi_id, poi_id_str, foodlist(购物车菜品), user_id, wm_order_pay_type:"2",
  recipient_name/address/phone/gender/house_number, addr_id, addr_longitude/latitude,
  caution(备注), token(购物车), coupon_view_id, ...
}
```
前置依赖：购物车(foodlist) + 地址(recipient_*) + 风控(wxapp_base_data)。
⚠️ 下单接口双版本：`/order/submit` 与 `/weapp/v1/order/submit`（真机确认后固定）。

## 骨架状态（待真机验证）
- 接口路径来自解包（真实存在）；请求参数/请求头字段/签名待真机验证（禁 mock）
- `search_poi` 已实现真实接口；`login`/`submit_order` 请求体结构已还原，字段待真机补全

## 使用流程（老百姓视角）
问（想吃什么/哪家店）→ 查（搜店→菜单→菜品）→ 手机号验证码登录 → 下单（加购→结算→提交订单，编码由系统补齐）→ 查订单/取消。
