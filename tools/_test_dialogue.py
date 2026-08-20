#!/usr/bin/env python3
"""Dialogue 规则单元测试（resolve_reply / SkillLock / route）。"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))

from cloud_orchestrator.core.dialogue.resolve_reply import resolve_reply
from cloud_orchestrator.core.dialogue.commands import CommandKind
from cloud_orchestrator.core.dialogue.skill_lock import detect_lock, enforce
from cloud_orchestrator.core.dialogue.route_entry import route_entry, looks_like_chat


def test_abandon():
    pending = {"field": "departure", "label": "出发城市", "type": "text", "skill": "tuniu"}
    cmd = resolve_reply("算了不买了", pending)
    assert cmd.kind == CommandKind.ABANDON, cmd


def test_off_topic():
    pending = {"field": "departure", "label": "出发城市", "type": "text", "skill": "tuniu"}
    cmd = resolve_reply("今天几点了", pending)
    assert cmd.kind in (CommandKind.REASK, CommandKind.OFF_TOPIC_CHAT), cmd


def test_set_slot():
    pending = {"field": "departure", "label": "出发城市", "type": "text", "skill": "tuniu"}
    cmd = resolve_reply("北京", pending)
    assert cmd.kind == CommandKind.SET_SLOT and cmd.value == "北京", cmd


def test_skill_lock():
    hit = detect_lock("我要去鼓楼挂号", ["glyy", "njpkzyy"])
    assert hit and hit[0] == "glyy", hit
    err = enforce("glyy", "njpkzyy")
    assert err and "锁定" in err


def test_route_chat():
    d = {"phase": "idle"}
    assert route_entry("东京热不热", d, hired=True) == "chat"
    assert looks_like_chat("东京热不热")


def test_switch_not_set_city():
    pending = {"field": "departure", "label": "出发城市", "type": "text", "skill": "tuniu"}
    cmd = resolve_reply("算了帮我点外卖", pending, locked_skill="tuniu")
    assert cmd.kind == CommandKind.NEW_INTENT, cmd


def test_modify_date():
    from cloud_orchestrator.core.dialogue.slots import extract_slots, detect_modify
    schema = [
        {"field": "departure", "label": "出发城市", "source": "customer", "type": "text"},
        {"field": "date", "label": "出行日期", "source": "customer", "type": "date"},
    ]
    got = detect_modify("改成后天", schema, pending_field="departure")
    assert "date" in got, got


def test_bulk_route():
    from cloud_orchestrator.core.dialogue.slots import extract_slots
    schema = [
        {"field": "departure", "source": "customer"},
        {"field": "arrival", "source": "customer"},
        {"field": "date", "source": "customer", "type": "date"},
    ]
    got = extract_slots("明天北京到上海", schema)
    assert got.get("departure") == "北京", got
    assert got.get("arrival") == "上海", got
    assert got.get("date"), got


def test_option_index():
    from cloud_orchestrator.core.dialogue.slots import resolve_option
    opts = ["G123 二等座", "G456 一等座", "G789 商务座"]
    assert resolve_option("第二个", opts) == "G456 一等座"
    pending = {"field": "train_num", "label": "车次号", "type": "text", "skill": "tuniu",
               "options": opts}
    cmd = resolve_reply("2", pending)
    assert cmd.kind == CommandKind.SET_SLOT
    assert "G456" in cmd.value


def test_consult_not_task():
    d = {"phase": "idle"}
    assert route_entry("途牛能查国际机票吗？", d, hired=True) == "chat"


def test_ask_id_must_match():
    import asyncio
    from cloud_orchestrator.core import graph_native as gn

    email = "askid-test@local"
    gn._resume_waiters.pop(email, None)
    gn._active_ask_ids.pop(email, None)
    fut = asyncio.Future()
    gn._resume_waiters[email] = fut
    gn.register_active_ask(email, "aaa111")
    assert gn.feed_graph_resume(email, "北京", "bbb222") is False
    assert not fut.done()
    assert gn.feed_graph_resume(email, "北京", "aaa111") is True
    assert fut.result() == "北京"
    gn._resume_waiters.pop(email, None)
    gn._active_ask_ids.pop(email, None)


def test_empty_ask_id_still_feeds():
    import asyncio
    from cloud_orchestrator.core import graph_native as gn

    email = "askid-empty@local"
    gn._resume_waiters.pop(email, None)
    fut = asyncio.Future()
    gn._resume_waiters[email] = fut
    gn.register_active_ask(email, "ccc333")
    assert gn.feed_graph_resume(email, "上海", "") is True
    assert fut.result() == "上海"
    gn._resume_waiters.pop(email, None)
    gn._active_ask_ids.pop(email, None)


def main():
    tests = [test_abandon, test_off_topic, test_set_slot, test_skill_lock, test_route_chat,
             test_switch_not_set_city, test_modify_date, test_bulk_route, test_option_index,
             test_consult_not_task, test_ask_id_must_match, test_empty_ask_id_still_feeds]
    fails = 0
    for t in tests:
        try:
            t()
            print(f"[PASS] {t.__name__}")
        except Exception as e:
            fails += 1
            print(f"[FAIL] {t.__name__}: {e}")
    if fails:
        sys.exit(1)
    print("\n全部通过")


if __name__ == "__main__":
    main()
