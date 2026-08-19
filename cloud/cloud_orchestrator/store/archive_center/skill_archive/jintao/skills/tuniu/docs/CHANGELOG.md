# 途牛 Skill 变更记录

## v2.0.0（2026-08-08）原子化 + 前置依赖
- `submit_order` 改为**原子终结点**：拆除内部自动连串（不再内部调 `_resolve_train`），需要的内部编码全部来自前置原子查询
- 新增原子查询 `train_booking_info`（M 站 ticketList 查车次下单编码：trainId/seatId/resId/站点码/票价）；`_resolve_train` 升级为该方法
- contract.json 补齐 `provides`/`requires`/`pass_params`：submit_order 依赖 `train_booking_info`（booking）+ `resolve_city_code`（dep/arr 城市码）
- 缺前置编码时 submit_order 明确报错，由系统（agent `_fill_requires`）自动补齐，AI 无需抄编号

## v1.1.0（2026-08-08）
- 新增「查城市代码」`resolve_city_code`：内置 **989 城完整 cityCode 映射**（city_data.py，2026-08-08 从途牛 M 站火车票页完整数据集 `TRAIN_VUEX_STATION_CITYS.LISTS` 提取），支持去掉「市/省/自治区」后缀别名匹配 + 结果缓存
- `submit_order` / `_resolve_train` **缺城市代码时自动解析补齐**（方式②），南京/镇江等任意城市均可下单，不再因 CITY_CODES 缺条目报「未内置城市代码」
- 修复：南京→镇江（K4061 12.5元）下单因缺 CITY_CODES 卡死的问题

## v1.0.0（2026-08-07）
- 打通：查车次/下单/支付（拉起支付宝 App）/查订单/退票
- 已出票退票受限 → 转客服 400-797-6666 / 火车站窗口
- 登录态存手机授权中心，换窗口/重启复用
