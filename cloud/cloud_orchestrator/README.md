# 云端怎么看（给人看的总入口）

打开代码只记 **三块**。

```
cloud/cloud_orchestrator/
│
├── ① 客户档案中心     store/archive_center/
│   │                  ※ 每个客户自己的档案，个人是个人的
│   ├── 消费者档案     consumer_archive/     会话、账号…
│   └── skill 档案     skill_archive/<人>/   此人挂的才艺（完整 skill）
│         ├── card.json                     上台展示
│         └── skills/<skill_id>/            对接就在这里（contract + api）
│
├── ② 对话大脑         core/ + retrieval/    雇人后怎么点菜办事
│
└── ③ 入口/手机通道    api/ + channel/       HTTP；连手机
```

## skill 是什么（别拆乱）

**skill = 挂在某个人身上的完整才艺包**，里面就有平台怎么对接（`contract/` 四文件 + `api/`）。  
不是「档案里只挂个 id、对接另放一处」。

```
张医生（zhang）
└── skills/glyy/     ← 鼓楼怎么请求、怎么解析，都在张的档案里

刘姐（liu）
└── skills/njpkzyy/  ← 浦口怎么对接，在刘的档案里
```

甲的 skill ≠ 乙的 skill。注册签名是 `人/skill_id`（如 `zhang/glyy`），互不覆盖。

密钥：`cloud/config.json` → `skills.<id>.api_key`（通用，不再为每个平台单独开顶层字段）。

| 你想找 | 进哪 |
|---|---|
| 某客户的会话/账号 | `store/archive_center/consumer_archive/` |
| 某人的上台卡 + 其 skill | `store/archive_center/skill_archive/<人>/` |
| AI 怎么选方法 | `core/`、`retrieval/` |

总览：[根 README](../../README.md)  
Skill 接入：[plans/contract-v2-接口说明.md](../../plans/contract-v2-接口说明.md)
