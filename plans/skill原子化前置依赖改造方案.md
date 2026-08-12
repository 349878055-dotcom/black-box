# Skill 原子化 + 前置依赖 改造方案

> 目标：三个 skill（glyy / tuniu / njpkzyy_new）统一为「原子化方法 + 前置依赖声明」，删除所有聚合/连串动作方法（一键挂号、内部自动连串），根治 LLM 编排不稳定问题。

## ✅ 实施状态（2026-08-08 已完成）

| 步骤 | 文件 | 状态 |
|---|---|---|
| njpkzyy_new 补 provides/requires | `adapters/skills/njpkzyy_new/contract.json` | ✅ 已实施 |
| glyy 契约对齐 + 补标注 + 删 book | `adapters/skills/glyy/contract.json`、`api/visit.py`、`api/_base.py` | ✅ 已实施 |
| tuniu 拆 submit_order + 新增 train_booking_info | `adapters/skills/tuniu/api/order.py`、`api/api.py`、`contract.json` | ✅ 已实施 |
| 检索层展示 requires/provides | `retrieval/index.py` | ✅ 已实施 |
| agent 层 skill_run 代码自动补全 | `core/agent.py`（`_fill_requires` / `_pick_field`，删除 `_fill_credentials` 死代码） | ✅ 已实施 |

验证结果：
- 三个 contract.json 均合法；所有契约参数与 api.py 实现签名一致（校验脚本通过）。
- `_fill_requires` 递归补齐测试通过：njpkzyy_new 挂号链（dept_code→doctor/schedule→patient）、glyy patient 对象传递、tuniu submit_order（booking + 城市码）。
- 全部改动文件 py_compile 通过。

## ⚠️ 缺陷修复记录（推演发现 + 已修）

**缺陷**：初版 `_fill_requires` 取值用「取第一个」，会导致系统性挂错（缺 dept_code 取第一个科室、缺 doctor_code 取第一个医生、缺 schedule_id 取第一个排班）。

**修复**（已实施）：
- `requires` 新增 `match` 字段：`{源字段: 本方法参数名}`，用 LLM/用户已给的名字（医生名/科室名）在源头返回里**精确匹配**对应编码（支持嵌套结构如 glyy 排班的 `doctor.doctor_name`）。
- `requires` 新增 `pass_params` 字段：调源头方法时透传本方法相关参数（如 `train_num/date` 传给 `train_booking_info`、`dep/arr` 传给 `resolve_city_code`）。
- `_seen` 循环保护只对「源头自身也有 requires」的方法生效，允许无 requires 源头（resolve_city_code）按不同参数多次调用。
- 匹配不到/缺匹配键 → 返回 None（安全，不编造），如实缺参等用户提供。
- **名字由 AI 确定**：match 键值来自 AI 传的参数（AI 从用户话里理解的医生名/科室名），程序绝不自己瞎选。
- **匹配不到 → 明确报错给 AI**：skill_run 返回「按你提供的信息「doctor_name=汪医生」在 list_dept_doctors 结果中未找到匹配项」，附 note「请确认名称是否正确，或询问用户后重试」，不会真的去挂号。
- **字段名风格兼容（驼峰保险）**：`_pick_field`/`_match_value` 对 `dept_code ↔ deptCode`、`schedule_num_id ↔ scheduleNumId` 下划线/驼峰互认，服务器返回风格不一致也能找到编号。
- **从「一大坨」里提取**：靠「按名字过滤（筛 dept_name=骨科 那条）+ 按字段名取（只取该条的 dept_code 字段）」，其余字段不看；不是人眼翻。

**回归测试通过**：
- 李医生排在前面，用户要王医生 → 精确锁定 D001（不再取第一个 D002）✅
- 用户未给医生名 → 不乱补，如实缺参 ✅
- tuniu pass_params 透传 train_num/date；resolve_city_code 对出发/到达各调一次不被拦截 ✅

上线注意：向量检索已统一为本地 BGE（`retrieval` 模块），从各 skill 的 `contract.json` **自动构建**，契约改动后重启云端服务即自动用新方法（无需手动重建索引；旧的千问 `adapters/skill_index.json` 静态索引已废弃删除）。进程内热更新可调 `retrieval.register.rebuild()`；`/api/v1/skills/search` 也已改走本地检索，全程零网络、不依赖千问 key。

---

## 一、背景与目标

### 问题根源
- 医院/平台后端接口是「资源-ID 串联」模型：先查 A 拿编码，再用编码查 B，再查 C……（如 `list_depts → dept_code → get_schedule → schedule_id → register_online`）。
- 小程序前端把中间编码藏在「页面 + 用户点击」里；而 Agent 把方法平铺给 LLM，**LLM 要自己记编码、抄编码，语言模型容易抄错** → 表现为「编排不好」。
- 不是 MCP 问题，不是 skill 编错，是「状态维护的责任压给了 LLM」。

### 决策（已与用户确认）
1. **删除所有聚合/连串动作方法**（glyy `book`、tuniu `submit_order` 内部连串）。
2. **统一为原子化方法 + 前置依赖声明**。
3. **不做意图聚合**（意图无法枚举），只把「编码来源关系」用结构化字段点破。
4. 前置依赖声明（`provides` / `requires`）是**契约层**；「代码自动补全」是**执行层可选项**，两者不冲突，且都建立在「不枚举意图」基础上。

### 设计原则
- 方法 = 最小原子单元，任意组合覆盖所有意图。
- 依赖关系 = 声明式（不写死调用顺序），LLM / 代码都能用。
- 契约与实现必须一致（本次发现 glyy 契约与 api.py 参数严重脱节，一并修正）。

---

## 二、统一契约格式设计

在每个 skill 的 `contract.json` 方法里新增两个可选字段：

### 1. `provides`（源头方法声明）
声明「本方法返回哪些编码/对象，给谁用」：

```jsonc
{
  "name": "list_depts",
  "desc": "科室列表 → [{dept_code, dept_name, ...}]",
  "provides": {
    "dept_code": { "desc": "科室编码", "used_by": ["list_doctors", "get_schedule", "register"] }
  }
}
```

### 2. `requires`（依赖方方法声明）
声明「本方法需要哪些参数，来自哪个方法的哪个返回字段」：

```jsonc
{
  "name": "get_schedule",
  "desc": "某科室某天排班",
  "requires": [
    { "param": "dept_code", "from": "list_depts", "field": "dept_code", "note": "先调 list_depts 拿真实科室编码" }
  ]
}
```

### 字段语义
- `provides`: `{ 返回字段名: { desc, used_by: [方法名...] } }`
- `requires`: 数组，每项 `{ param: 本方法参数名, from: 源头方法, field: 源头返回字段, note: 说明 }`

### 消费方
- `retrieval/index.py`：拼小纸条/方法描述时，把 `requires` / `provides` 转成自然语言提示给 LLM。
- `core/agent.py` `skill_run`：可选做「代码自动补全」（见第六节）。
- `adapters/registry.py`：加载不受影响（只读已知字段，新增字段透传）。

---

## 三、glyy（鼓楼医院）拆解方案

### 3.1 删除
- `api/visit.py` 的 `book`（一键挂号，内部串 `list_depts → get_patient → get_schedule → register`）。无外部调用方，安全删除。

### 3.2 契约与实现对齐（重点修正脱节）
当前 `contract.json` 的 params 与 `api.py` 签名不一致，必须按 api.py 真实签名重写：

| 方法 | 现 contract params | 应改为（对齐 api.py） |
|---|---|---|
| `list_depts` | `{}` | `{}` ✅ |
| `list_doctors` | `{}` | `{dept_code}` |
| `get_available_dates` | `{begin_date, end_date, branch_code, business_type, res_src}` | `{dept_code, begin, end, business_type}` |
| `get_schedule` | `{begin_date, end_date, schedule_type, type, branch_code, need_detail, business_type, res_src}` | `{dept_code, date, business_type, schedule_type, type}` |
| `get_patient` | `{}` | `{}` ✅ |
| `register` | `{}` | `{dept_code, dept_name, doctor_code, doctor_name, appointment_time, noon_code, schedule_id, schedule_num_id, start_hour, reg_type, reg_name, res_title_code, res_title_name, reg_fee, business_type, patient}` |
| `login` | `{phone}` | `{phone, code}`（短信验证码） |

> 注意：glyy 查询端**不需要** `branch_code/res_src` 前置（这些是固定常量），真正的依赖是 `dept_code`。`register` 的 `patient` 是**对象**（来自 `get_patient`），不是单个编码。

### 3.3 依赖标注
- `list_depts`：`provides: {dept_code, dept_name}`
- `get_schedule`：`provides: {schedule_id, reg_type, reg_name, res_title_code, res_title_name, reg_fee, business_type, doctor_code, doctor_name, noon_code, detail.schedule_num_id, detail.time_part}`
- `get_patient`：`provides: {patient}`（患者信息对象）
- `list_doctors`：`requires: [dept_code ← list_depts]`
- `get_available_dates`：`requires: [dept_code ← list_depts]`
- `get_schedule`：`requires: [dept_code ← list_depts]`
- `register`：`requires: [dept_code/dept_name ← list_depts, schedule_id/reg_*/fee/doctor_* ← get_schedule, schedule_num_id/time_part ← get_schedule.detail, patient ← get_patient]`

### 3.4 特别提醒
- `register` 是「15+ 参数汇聚」+「对象传递（patient）」，**纯 LLM 抄字段风险最高** → 强烈建议配合 agent 层代码自动补全（第六节）。
- `flow` 步骤 ① 需保持与原子方法一致（book 本来不在契约里，无需改 flow 结构，但需复查）。

---

## 四、tuniu（途牛）拆解方案

### 4.1 现状
- 查询类（MCP）：`search_train / train_detail / search_flight / search_hotel / search_ticket` —— 已是原子，参数用自然语言（城市名/景点名），**无前置依赖** ✅ 保留。
- 下单类（M 站）：`submit_order` 是聚合方法，内部串 `_ensure_city_codes`（自动补城市码）+ `_resolve_train`（自动调 M 站 ticketList 拿 trainId/resId/seatId/departCode/arriveCode）+ 组装 AddOrder。

### 4.2 拆解动作
1. **新增原子方法 `train_booking_info(dep, arr, date, train_num)`**
   - 把私有 `_resolve_train`（`api/order.py`）升级为公开原子方法。
   - 调 M 站 ticketList，返回该车次内部编码：`{ok, train: {trainId, trainNum, depart, arrive, departCode, arriveCode, seats: [{seatName, seatId, resId, price, leftNumber}]}}`。
   - ⚠️ MCP 的 `train_detail` 是另一套接口（官方开放平台），**其返回字段不能用于 AddOrder**，`train_booking_info` 必须独立存在（内部走 M 站 ticketList）。

2. **`submit_order` 原子化**
   - 去掉内部自动调 `_resolve_train` / `_ensure_city_codes`。
   - 参数改为显式编码：`{train_id, seat_id, res_id, depart_station_code, arrive_station_code, dep_city_code, arr_city_code, passengers, contact_tel}`。
   - 保留 `passengers`（乘客数组，自然语言可填）。
   - `requires` 标注：
     - `train_id / seat_id / res_id / depart_station_code / arrive_station_code` ← `train_booking_info`
     - `dep_city_code / arr_city_code` ← `resolve_city_code`
   - `pay / order_detail / cancel_order` 需要 `order_id` ← `submit_order` 返回值 或 `order_list` 返回的 `orderId`，补 `requires`。

3. **保留**：`resolve_city_code`（途牛城市码是静态表 `city_data.py`，特例，保留）。

### 4.3 依赖标注
- `resolve_city_code`：`provides: {city_code}`
- `train_booking_info`：`provides: {trainId, seatId, resId, departCode, arriveCode}`
- `submit_order`：`requires: [train_id/seat_id/res_id/... ← train_booking_info, city_code ← resolve_city_code]`

### 4.4 特别提醒
- `submit_order` 拆原子后编码参数多达 7 个，纯 LLM 抄风险高 → 建议配 agent 代码自动补全。
- `flow` 步骤 ③「下单」需更新描述：由「自动查码下单」改为「先 train_booking_info 取码，再 submit_order」。

---

## 五、njpkzyy_new（浦口中医院）补标注方案

无内部聚合方法，只需补 `provides` / `requires` 标注：

### 5.1 编码源头点破
- `list_depts`：`provides: {dept_code}`
- `get_schedule`：`provides: {schedule_id, schedule_num_id, time_part, noon_code}`
- `get_medical_card`：`provides: {patient_code, patient_name, id_card}`

### 5.2 依赖方标注
- `list_dept_doctors`：`requires: [dept_code ← list_depts]`
- `get_available_dates`：`requires: [dept_code ← list_depts]`
- `get_schedule`：`requires: [dept_code ← list_depts]`
- `judge_online`：`requires: [dept_code ← list_depts]`（doctor_code ← list_dept_doctors 可选）
- `get_schedule_detail`：`requires: [schedule_id ← get_schedule]`
- `register_online`：`requires: [dept_code/dept_name ← list_depts, doctor_code ← list_dept_doctors, schedule_id/schedule_num_id/time_part/noon_code ← get_schedule, patient_code/patient_name/id_card ← get_medical_card]`

### 5.3 待确认缺口
- `get_order` 需要 `order_id`，但当前 skill **没有订单列表方法**，`order_id` 无来源。
  - `api.py` 实现：`get_order(order_id)` 不传 `order_id` 时返回列表（`/api/order/order/v2/order`）。
  - 建议：调整 `get_order` 契约为「不传 order_id 返回订单列表，传则返回详情」，或新增 `list_orders` 方法（若接口支持）。

---

## 六、检索层 + Agent 层配合

### 6.1 检索层 `retrieval/index.py`
- `_collect` 拼 `method_text` 时，读取 `requires`，追加「【依赖】本方法需要 param，来自 from 方法的 field」。
- 读取 `provides`，在源头方法描述追加「【提供】dept_code 供 xxx 使用」。
- `make_note` / `make_note_for` 的方法行追加依赖说明 → 小纸条直接告诉 LLM 依赖关系。
- 契约改动后需触发索引重建：`retrieval.register.rebuild()` 或删除 `skill_index.json` 缓存使其重建（确认 `skill_index.json` 是否为运行时唯一来源）。

### 6.2 Agent 层 `core/agent.py` `skill_run`（可选但推荐）
在 `_run_tool` 的 `skill_run` 分支加一段「代码自动补全」（与 `_fill_credentials` 同套路）：
1. 调用前读取方法的 `requires`。
2. 对每个 `requires`，检查 `params` 是否缺 `param`。
3. 缺 → 代码自动调 `from` 方法（现查接口）→ 从返回的 `field` 取值 → 填进 `params`。
4. 自动补失败则如实报错，交 LLM 处理。

> 效果：LLM 不用抄编码（导诊台机制），根治「抄错编号/字段」。这是执行层兜底，**不属于聚合方法，不违反原子化原则**。
> 顺带：清理 `_fill_credentials` 里针对已删除 `book` 方法的死代码（`if method not in ("book",)`）。

---

## 七、分步实施顺序（按风险从低到高）

1. **njpkzyy_new 补标注**（纯 contract.json 改动，最低风险）→ 触发索引重建 → 验证。
2. **glyy 契约与实现对齐 + 删 book + 补标注** → 验证。
3. **tuniu 拆 submit_order + 新增 train_booking_info + 补标注** → 验证。
4. **检索层 index.py 展示 provides/requires** → 让 LLM 看得见依赖。
5. **agent 层 skill_run 代码自动补全**（可选，根治抄错）→ 验证。

---

## 八、风险与注意事项

- **glyy 契约与实现脱节是隐藏大坑**：改契约必须以 `api.py` 真实签名为准，否则 LLM 传参依旧对不上。
- **tuniu MCP `train_detail` 与 M 站 ticketList 是两套接口**：不能混用，`train_booking_info` 必须独立调 M 站。
- **`register` / `register_online` / `submit_order` 是「参数汇聚 + 对象/多编码传递」**：纯 LLM 抄字段风险高，建议配代码补全。
- **删除 `book` / `submit_order` 内部连串前**：确认无其他调用方（已排查：`book` 无外部调用，`submit_order` 仅内部使用；`_fill_credentials` 中的 `book` 分支为死代码）。
- **`skill_index.json` 缓存**：契约改动后需重建索引，否则检索仍是旧文本。
- **兼容性**：`provides` / `requires` 为新增字段，registry 只读已知字段，不影响现有加载。

---

## 附：统一契约示例（njpkzyy_new）

```jsonc
{
  "name": "get_schedule",
  "desc": "某科室某天排班 → [{schedule_id, reg_name, noon_code, doctor, detail}]",
  "need_login": false,
  "params": { "dept_code": "真实科室代码", "begin_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD" },
  "requires": [
    { "param": "dept_code", "from": "list_depts", "field": "dept_code",
      "note": "先调 list_depts 拿到目标科室的真实 dept_code，禁止编造" }
  ],
  "provides": {
    "schedule_id": { "desc": "排班 id，供 get_schedule_detail/register_online 使用" },
    "schedule_num_id": { "desc": "时段号 id，供 register_online 使用" }
  }
}
```
