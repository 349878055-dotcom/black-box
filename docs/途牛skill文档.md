# 途牛 Skill 文档（本地完整版）

> 独立完整文档（不依赖 Skill 工作台）。用途：描述途牛 skill 的每个功能、接口、请求、返回，供人读/维护/对接。
> 实现代码：`cloud/cloud_orchestrator/adapters/tuniu_api.py`；注册：`cloud/cloud_orchestrator/adapters/registry.py`。

---

## 1. 概述

| 项 | 值 |
|---|---|
| skill id | `tuniu` |
| 名称 | 途牛（途牛旅游网） |
| 分类 | 出行 |
| 能力 | 查车次/机票/酒店/门票（MCP 免费）→ 火车票下单 → 支付（拉起支付宝）→ 订单确认 → 退票 |
| 登录方式 | M 站 cookie（passport.tuniu.com 手机号+短信+腾讯滑块，真人配合登录一次，cookie 存手机授权中心复用） |
| 业务流程 | ① 查询 → ② 下单 → ③ 支付 → ④ 订单确认 → ⑤ 退票 |

---

## 2. 功能清单（工程化标准：功能 → 接口 → 请求 → 参数 → 正确返回 → 错误返回）

### 2.1 查车次 `search_train`

| 项 | 值 |
|---|---|
| 接口地址 | `POST https://openapi.tuniu.cn/mcp/train`（MCP，仅查询，免费） |
| 请求值 | `{"name":"searchLowestPriceTrain","arguments":{"departureCityName":"上海","arrivalCityName":"苏州","departureDate":"2026-08-11"}}` |
| 参数说明 | departure=出发城市；arrival=到达城市；date=日期 YYYY-MM-DD |
| 登录 | 不需要 |
| 正确返回 | `{ok, trains:[{trainNum, departureTime, arrivalTime, seat:{seatName, price, leftNumber}}]}` |
| 错误返回 | `{ok:false, error}` |

### 2.2 车次详情 `train_detail`

| 项 | 值 |
|---|---|
| 接口地址 | `POST https://openapi.tuniu.cn/mcp/train`（MCP） |
| 请求值 | `{"name":"queryTrainDetail","arguments":{"trainNum":"K738","departureDate":"2026-08-11"}}` |
| 参数说明 | train_num=车次号；date=日期；departure/arrival=城市（可选） |
| 登录 | 不需要 |
| 正确返回 | `{ok, train:{trainNum, stations, seats}}` |
| 错误返回 | `{ok:false, error}` |

### 2.3 机票搜索 `search_flight`

| 项 | 值 |
|---|---|
| 接口地址 | `POST https://openapi.tuniu.cn/mcp/flight`（MCP） |
| 请求值 | `{"name":"searchLowestPriceFlight","arguments":{"departureCityName":"上海","arrivalCityName":"北京","departureDate":"2026-08-11"}}` |
| 参数说明 | departure/arrival/date |
| 登录 | 不需要 |
| 正确返回 | `{ok, flights:[]}` |
| 错误返回 | `{ok:false, error}` |

### 2.4 酒店搜索 `search_hotel`

| 项 | 值 |
|---|---|
| 接口地址 | `POST https://openapi.tuniu.cn/mcp/hotel`（MCP） |
| 请求值 | `{"name":"tuniu_hotel_search","arguments":{"cityName":"南京","checkIn":"2026-08-11","checkOut":"2026-08-12"}}` |
| 参数说明 | city/check_in/check_out |
| 登录 | 不需要 |
| 正确返回 | `{ok, hotels:[]}` |
| 错误返回 | `{ok:false, error}` |

### 2.5 景点门票 `search_ticket`

| 项 | 值 |
|---|---|
| 接口地址 | `POST https://openapi.tuniu.cn/mcp/ticket`（MCP） |
| 请求值 | `{"name":"query_cheapest_tickets","arguments":{"scenic_name":"故宫"}}` |
| 参数说明 | scenic_name=景点名 |
| 登录 | 不需要 |
| 正确返回 | `{ok, tickets:[]}` |
| 错误返回 | `{ok:false, error}` |

### 2.6 下单创建订单 `submit_order` ⚠️ 真实购票

| 项 | 值 |
|---|---|
| 接口地址 | `POST https://api.tuniu.com/tcs/gtc/train/order/AddOrder`（body `d=` URL 编码 JSON） |
| 请求值 | ```{"trainId":20738,"trainNumber":"K738","resourceId":...,"seatId":9,"departDate":"2026-08-11","adultCount":1,"adultPrice":14.5,"departureCityCode":2500,"arrivalCityCode":1615,"departureCityName":"上海","arrivalCityName":"苏州","departureStations":[...],"arrivalStations":[...],"contactList":{"tel":"18912926603"},"touristList":[{"name":"刘良玺","psptId":"320122198504082439","tel":"18912926603","psptType":1,"birthday":"1985-04-08","sex":1}]}``` |
| 参数说明 | dep/arr=城市；date=日期；train_num=车次；seat_name=席别；passengers=乘客数组[{name,psptId,tel,birthday,sex}]；contact_tel=联系人手机 |
| 登录 | 需要（M 站 cookie，手机凭据库自动补） |
| 正确返回 | `{ok, order_id, order_amount, pay_url}` |
| 错误返回 | `{ok:false, error, need_login?}`（170001=参数错误；179998=未登录→need_login 触发登录引导） |

### 2.7 支付 `pay`

| 项 | 值 |
|---|---|
| 接口地址 | `GET https://m.tuniu.com/api/train/payment/order/{order_id}` → 重定向途牛收银台 `cashier.tuniu.com/cashier/m/...` |
| 请求值 | order_id=订单号；order_type=订单类型（默认 38） |
| 说明 | 收银台选「支付宝」→ 途牛返回 `alipays://` → 虾米 App WebViewClient 拦截 → **拉起手机支付宝 App**（桌面弹出）→ 支付宝内付款 |
| 登录 | 需要 |
| 正确返回 | `{ok, pay_url, pay_ways:[]}` |
| 错误返回 | `{ok:false, error}` |

### 2.8 订单详情 `order_detail`（确认单子/出票状态）

| 项 | 值 |
|---|---|
| 接口地址 | `GET https://m.tuniu.com/api/train/order/orderDetail?d={"orderId":"...","orderType":38}` |
| 请求值 | order_id=订单号；order_type=订单类型（默认 38） |
| 登录 | 需要 |
| 正确返回 | `{ok, order:{statusName(待出票/购票成功), orderStatusCode, payStatusName, canPay, canCancel, ticketInfo(车次/座位), touristsInfo(乘客), refundServiceFee}}` |
| 错误返回 | `{ok:false, error}` |

### 2.9 订单列表 `order_list`（查询票务）

| 项 | 值 |
|---|---|
| 接口地址 | `GET https://m.tuniu.com/api/train/order/orderList?d={"pageNo":1,"pageSize":10}` |
| 请求值 | page_no=页码（默认1）；page_size=每页条数（默认10） |
| 登录 | 需要 |
| 正确返回 | `{ok, orders:[{orderId, beginTime(乘车日期), productName, status, amount}]}` |
| 错误返回 | `{ok:false, error}` |

### 2.10 退票/取消订单 `cancel_order` ⚠️ 真实退票（能力边界见 §4）

| 项 | 值 |
|---|---|
| 接口地址 | 未支付/占座：`GET https://m.tuniu.com/api/train/order/newCancelOrder?d={"orderId":"...","orderType":38}` |
| 请求值 | order_id=订单号；order_type=订单类型（默认 38） |
| 登录 | 需要 |
| 正确返回 | `{ok, data:{success:true}}` |
| 错误返回 | `{ok:false, error}`（已出票→711001 取消失败，需转客服/窗口） |

---

## 3. 登录态管理

- 登录：`passport.tuniu.com` 手机号 + 短信验证码 + 腾讯滑块（真人配合，滑块必现不可跳过）。
- 登录态 = cookie（`isLogined` / `ssoUser` / `muser` / `TUNIUmuser` / `tuniuuser_id`，domain `.tuniu.com` / `.m.tuniu.com`）。
- 存手机授权中心（`CredentialStore "tuniu"`）；换窗口/重启自动复用（实测：重启后直接下单，不重新登录）。
- 未登录时下单 → AddOrder 返回 179998 → agent 自动弹内置浏览器登录页 → 登录后 `export_cookies` 存凭据 → 重试下单。

## 4. 能力边界

| 项 | 说明 |
|---|---|
| MCP 查询 | 免费，仅查询不能下单 |
| 下单 | 必须登录；乘客直接传 `touristList`，免网页「添加乘客」弹窗 |
| 支付 | 内置浏览器收银台 → 点支付宝 → 拉起支付宝 App；**付款在支付宝内完成（真人操作）** |
| 退票（未支付/占座） | `newCancelOrder` 自动退（实测成功） |
| 退票（已出票） | 途牛网页无自助退票入口（平台限制）；需途牛客服 400-797-6666 / 火车站窗口 / 途牛 App，按铁路规则扣手续费（开车前 8 天以上免、48h+ 5%、24-48h 10%、<24h 20%） |

## 5. 已实测记录

- 下单成功：订单 1259153040 / 1259153485 / 1259153490 / 1259153534 / 1259153465 等。
- 支付拉起支付宝 App 成功：订单 1259153534（K738 08-11，购票成功，24.5 元已付）。
- 退票成功（未支付订单）：1259153465。
- 已出票退票受限：1259153534 退票失败（711001），确认途牛平台限制。
