"""临时：验证 agent done 反问拦截：只拦「向客户提问」，不误伤正常收束。"""
from __future__ import annotations

import sys

sys.path.insert(0, "cloud")

from cloud_orchestrator.core.agent import Agent  # noqa: E402

a = Agent()

CASES = [
    # (text, 期望拦截?)
    ("请问您要买什么票？", True),      # 问号 + 提问引导词 → 拦
    ("请告诉我您的身份证号？", True),  # 拦
    ("您的出行日期是几号？", True),     # 拦
    ("请确认是否继续？", True),        # 拦
    ("已为您办妥，祝您愉快。", False),  # 无问号 → 不拦
    ("查询失败，请稍后重试。", False),  # 无问号 → 不拦
    ("好的，done", False),             # 无问号 → 不拦
    ("？", False),                      # 只有问号无引导词 → 不拦（保守）
]

failed = 0
for text, want in CASES:
    got = a._needs_ask_user(text)
    mark = "✓" if got == want else "✗"
    if got != want:
        failed += 1
    print(f"{mark} 拦截={got} 期望={want}  text={text!r}")

print("\n✅ done 反问拦截逻辑验证通过" if failed == 0 else f"\n❌ {failed} 用例失败")
sys.exit(1 if failed else 0)
