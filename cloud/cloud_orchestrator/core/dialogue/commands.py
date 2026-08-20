"""resolve_reply 输出的业务命令种类。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CommandKind(str, Enum):
    ABANDON = "abandon"
    SET_SLOT = "set_slot"
    REASK = "reask"
    OFF_TOPIC_CHAT = "off_topic_chat"
    NEW_INTENT = "new_intent"
    LOCK_SKILL = "lock_skill"
    PAYMENT_RETURN = "payment_return"
    NOOP = "noop"


@dataclass
class Command:
    kind: CommandKind
    slot_field: str = ""
    value: str = ""
    reason: str = ""
    skill: str = ""
    extra: dict = field(default_factory=dict)
