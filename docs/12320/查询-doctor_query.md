# Skill 功能包 · nj12320_doctor_query（12320 医生可约时间查询）⭐ 核心 skill

> 每个 skill = 一个功能包文件夹：**硬编码（main.py）+ 表格（meta.json）+ 接口说明（本 README）**。
> ⭐ 本项目当前**唯一**核心 skill：说医生名 → 立刻知道**确定的可约时间** + 怎么挂号。

## 这是什么

**只查确定的可约时间**（12320 网页独有的实时数据）：
说医生名字（+医院）→ 返回这位医生 **未来 7 天哪天有号、上午/下午哪个时段可约/已满**，以及**怎么挂号**。
**不查通用信息**（医生简介/职称等，豆包/DeepSeek 都知道，不用开网页）。

## 包结构

```
nj12320_doctor_query/
  main.py     硬编码：页面操作逻辑（run(d, ctx)）
  meta.json   表格：字段定义 / 规则 / guide
  README.md   接口说明（本文件）
```

## 表格（meta.json 字段）

| 字段 | label | 必填 | 规则 | 说明 |
|---|---|---|---|---|
| `docname` | 医生姓名 | ✅ | ≤20 字 | **核心**：要查的医生名 |
| `hosname` | 医院名称 | ✅ | ≤40 字 | 定位医生用（12320 无全局医生搜索） |
| `depname` | 科室名称（可留空） | — | ≤40 字 | 加快定位 |
| `when` | 想约的日期/时段（可留空） | — | ≤20 字 | 如：周五上午、08-10 上午 |

## 接口（编码 ↔ 表格）

```python
async def run(d: SkillDriver, ctx: SkillCtx):
    docname = str(ctx.get("docname", "")).strip()   # ← 从表格读字段（核心）
    hosname = str(ctx.get("hosname", "")).strip()
    depname = str(ctx.get("depname", "")).strip()
    when    = str(ctx.get("when", "")).strip()
    ...
    # 医院 → 科室 → 医生详情 → 未来7天排班（确定的可约时间）
    ctx.report([{"医生": docname, "可约排班(7天内)": [
        {"日期": "08-05", "星期": "周三", "上午": "可约", "下午": "—"},
        {"日期": "08-11", "星期": "周二", "上午": "已满", "下午": "可约"},
    ]}])
    ctx.report([{"怎么挂号": "12320平台预约（需登录+实名）；可约时段点击「预约」→ 填表 → 验证码真人配合"}])
```

- **入口**：模块级 `async def run(d, ctx)`
- **表格字段读取**：`ctx.get("字段名", "")` 或 `ctx["字段名"]`
- **汇报**：`ctx.report([{...}])` → 排班表（确定时间）回主 Agent / 打印
- **driver 原语**（`d.`）：`navigate` `page_text` `read`（含 `url`/`interactives`）`click_keyword`
  `wait_text` `wait_any` `scroll_to` `ask` `coop` 等（两端同接口）

## 调试 / 发布

```bash
# 医生可约时间（核心场景）
python -m skill_maker.pc_run nj12320_doctor_query --fields '{"hosname":"南京鼓楼医院","depname":"产科","docname":"李洁"}'
# 带想约时间过滤
python -m skill_maker.pc_run nj12320_doctor_query --fields '{"hosname":"南京鼓楼医院","depname":"产科","docname":"李洁","when":"周二上午"}'
# 发布（会部署云端）
python skill_maker/publish.py nj12320_doctor_query
```

## 注意

- 排班数据是**确定的可约时间**（可约/已满/无号），来自 12320 实时页面——这是本 skill 的价值
- 老站科室分页（8/页共 30 页）→ 自动翻页找；「查看科室」为 target=_blank → 强制当前页跳转
- 手机端跳转验证用 URL（`hos_showReservation`/`dep_detail`）而非文本（响应式差异）
- 真挂号（提交预约）需登录+验证码 → 真人配合（铁律）；本 skill 给「怎么挂号」指引，不代提交
- JSON 发布前必须 `status=verified`、`steps=[]`
