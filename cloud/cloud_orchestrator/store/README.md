# store = 客户档案相关落盘

真正的档案在 **`archive_center/`（客户档案中心）**：

```
archive_center/
├── consumer_archive/              ← 消费者档案
└── skill_archive/<人>/            ← 此人的 skill 档案
      ├── card.json
      └── skills/<skill_id>/       ← 完整 skill（含对接）
```

真实模块（无兼容层，直连）：
- `consumer_archive/users.py`（账号）、`consumer_archive/conversations.py`（会话）
- `skill_archive/cards.py`（上台卡）

公共：`persist.py`、`refresh_tokens.py`、`flows.py`。
