"""SkillLock：强实体词锁定才艺，防止鼓楼→浦口漂移。"""
from __future__ import annotations

from typing import Any

# 强实体词 → skill（泛词如「挂号」「买票」只用于路由，不用于 LOCK）
STRONG_ENTITIES: dict[str, str] = {
    "鼓楼": "glyy",
    "浦口": "njpkzyy",
    "中医院": "njpkzyy",
    "美团": "meituan_waimai",
    "外卖": "meituan_waimai",
    "途牛": "tuniu",
}


def detect_lock(text: str, allowed_skills: list[str] | None = None) -> tuple[str, str, dict] | None:
    """从用户话里检测强实体 → (skill, reason, lock_entity)。"""
    t = (text or "").strip()
    if not t:
        return None
    allowed = set(allowed_skills or [])
    hits: list[tuple[str, str, int]] = []
    for entity, skill in STRONG_ENTITIES.items():
        if entity not in t:
            continue
        if allowed and skill not in allowed:
            continue
        hits.append((skill, entity, t.index(entity)))
    if not hits:
        return None
    # 取最早出现的实体
    hits.sort(key=lambda x: x[2])
    skill, entity, _ = hits[0]
    reason = f"user_said_{entity}"
    lock_entity: dict[str, Any] = {}
    if entity in ("鼓楼", "浦口", "中医院"):
        lock_entity["hospital"] = entity
    elif entity in ("美团", "外卖"):
        lock_entity["platform"] = "meituan"
    elif entity == "途牛":
        lock_entity["platform"] = "tuniu"
    return skill, reason, lock_entity


def reinforce_lock(text: str, locked_skill: str | None) -> bool:
    """用户拒绝换 skill（「我就要鼓楼」）→ 强化锁定。"""
    if not locked_skill:
        return False
    t = (text or "").strip()
    if not t:
        return False
    neg = ("不要", "不去", "不是", "就要", "必须", "坚持")
    if any(n in t for n in neg):
        for entity, skill in STRONG_ENTITIES.items():
            if entity in t and skill == locked_skill:
                return True
    return False


def enforce(locked_skill: str | None, target_skill: str) -> str | None:
    """已 lock 时 skill_run/search 目标 skill 必须匹配。返回 error 或 None。"""
    if not locked_skill:
        return None
    if str(target_skill or "").strip() == str(locked_skill).strip():
        return None
    return (f"当前任务已锁定才艺「{locked_skill}」，不能切换到「{target_skill}」。"
            f"若客户坚持换办事对象，请先 done 收尾再开新任务。")
