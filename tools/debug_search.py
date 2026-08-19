"""本地调试：search 工具的核心逻辑（make_note 候选 top-3 + 命中效果）。

用途（2026-08-16 检索改造后）：验证 4 个 skill 在"AI 主动 search"新架构下，
客户典型说法能否命中正确候选。只读本地，不连手机、不部署。

用法（项目根）：
    python3 tools/debug_search.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))

from cloud_orchestrator.retrieval.index import get_index  # noqa: E402


def main() -> None:
    idx = get_index()
    print("=== 索引构建 ===")
    print(f"平台数={len(idx.platform_items)} 方法数={len(idx.method_items)}")
    print()

    # 客户典型说法（对应 4 个 skill：glyy/njpkzyy/meituan_waimai/tuniu）
    cases = [
        "帮我挂个号",
        "挂个专家号",
        "我要看心内科",
        "帮我订张高铁票",
        "买张火车票去北京",
        "帮我点个外卖",
        "附近有什么吃的",
        "订个酒店",
        "查一下科室",
        "帮我查排班",
        "南京哪个医院医生比较好",
    ]

    for text in cases:
        print(f"===== 客户说：{text} =====")
        try:
            note = idx.make_note(text, allowed_skills=None, owner_id="jintao")
            if not note:
                print("  →（无候选）")
                continue
            plats = note.get("platforms") or []
            top = note.get("top_skill") or ""
            print(f"  top={top}  候选数={len(plats)}")
            for p in plats:
                print(f"    - {p.get('skill')}: {p.get('name')} 方法={p.get('methods')}")
        except Exception as e:
            print(f"  异常: {type(e).__name__}: {e}")
        print()


if __name__ == "__main__":
    main()
