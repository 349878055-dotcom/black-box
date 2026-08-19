"""工具级联调：search（统一检索）——skill 向量/关键词 + web 博查 + 闸门。

验证 Agent._run_tool("search", ...) 全部分支（问题⑩ 的 AI 主动检索）：
  - hired + skill/vector：典型说法命中候选（挂个号 / 高铁票 / 外卖）
  - hired + skill/vector + 乱码：返回干净 dict，不抛异常
  - hired + skill/keyword：显式平台名/方法名/触发词找字面（美团/挂号/高铁/途牛/专家号）
  - hired + skill/keyword + 乱码：0 命中，干净返回
  - 空 query（skill / web）：ok=false + 明确错误
  - 闲聊模式 skill：闸门拦截；闲聊模式 web：博查
  - hired + web：博查
只读本地（向量模型在 cloud/models，BGE 离线），不连手机、不部署。

用法（项目根）：
    PYTHONPATH=cloud python3 tools/verify_search_tool.py [owner_id]

退出码：0=全 PASS（web 按 INFO 不计失败）；1=有 FAIL。
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))

from cloud_orchestrator.adapters.registry import skills_for_owner  # noqa: E402
from cloud_orchestrator.core.agent import Agent  # noqa: E402

OWNER = sys.argv[1] if len(sys.argv) > 1 else "jintao"

_results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f"  → {detail}" if detail else ""))


def record_info(name: str, detail: str) -> None:
    _results.append((name, True, detail))  # INFO 计为通过
    print(f"[INFO] {name}" + (f"  → {detail}" if detail else ""))


def _brief(r) -> str:
    if not isinstance(r, dict):
        return f"{type(r).__name__}: {str(r)[:120]}"
    if not r.get("ok"):
        return f"ok=false error={str(r.get('error'))[:120]}"
    cands = r.get("candidates") or []
    top = r.get("top_skill") or ""
    names = ",".join(c.get("name", "") for c in cands[:3]) or "-"
    return f"top={top or '-'} 候选={len(cands)} [{names}]"


def hired_agent() -> Agent:
    a = Agent(device_id="verify-search")
    a.hired = True
    a.person_id = OWNER
    a.allowed_skills = skills_for_owner(OWNER)
    return a


async def main() -> int:
    print(f"owner={OWNER}  名下 skills={skills_for_owner(OWNER)}")
    a = hired_agent()

    # ── 1. skill/vector：典型说法 → 应有候选 + 可读 note ──
    for q in ["帮我挂个号", "帮我订张高铁票", "帮我点个外卖"]:
        r = await a._run_tool("search", {"query": q, "scope": "skill", "method": "vector"})
        ok = isinstance(r, dict) and r.get("ok") and bool(r.get("candidates")) and bool(r.get("note"))
        record(f"vector「{q}」有候选且带 note", ok, _brief(r))

    # ── 2. skill/vector + 乱码/无关话：相似度低于阈值 → 干净返回"未找到"，不硬塞候选（待定 2）──
    for q in ["abcdefgXYZ完全不相关", "讲故事给我听", "今天天气怎么样"]:
        r = await a._run_tool("search", {"query": q, "scope": "skill", "method": "vector"})
        ok = (isinstance(r, dict) and r.get("ok")
              and not r.get("candidates") and "相关度不足" in str(r.get("note", "")))
        record(f"vector「{q}」被阈值拦（未找到）", ok, _brief(r))

    # ── 2.5 单才艺 + vector：bug1 修复验证（只挂 1 个才艺也要能命中）──
    # bug1 修复前：make_note_for 返回缺 platforms → top_score 恒 0 → 永远"相关度不足"。
    # 修复后：统一走一套，用平台名去搜必然命中本才艺。
    all_skills = skills_for_owner(OWNER)
    if all_skills:
        single = all_skills[0]
        from cloud_orchestrator.adapters.registry import get_adapter  # noqa: E402
        name_q = str((get_adapter(single, OWNER) or {}).get("name") or single)
        sa = Agent(device_id="verify-single")
        sa.hired = True
        sa.person_id = OWNER
        sa.allowed_skills = [single]
        print(f"  单才艺用例：allowed_skills=[{single}] name={name_q}")
        r = await sa._run_tool("search", {"query": name_q, "scope": "skill", "method": "vector"})
        ok = isinstance(r, dict) and r.get("ok")
        if ok:
            cands = r.get("candidates") or []
            hit = (any(c.get("skill") == single for c in cands if isinstance(c, dict))
                   or r.get("top_skill") == single)
            record(f"单才艺 vector「{name_q}」命中本才艺（bug1 修复）", hit, _brief(r))
        else:
            record(f"单才艺 vector「{name_q}」ok=false（异常）", False, _brief(r))

    # ── 3. skill/keyword：显式平台名/方法名/触发词找字面 ──
    keyword_cases = [
        ("美团", {"meituan_waimai"}),
        ("外卖", {"meituan_waimai"}),
        ("挂号", {"glyy", "njpkzyy"}),
        ("专家号", {"glyy", "njpkzyy"}),
        ("高铁", {"tuniu"}),
        ("途牛", {"tuniu"}),
    ]
    for q, want in keyword_cases:
        r = await a._run_tool("search", {"query": q, "scope": "skill", "method": "keyword"})
        got = {c.get("skill") for c in (r.get("candidates") or []) if isinstance(c, dict)}
        hit = bool(got & want)
        record(f"keyword「{q}」命中", hit,
               f"want={sorted(want)} got={sorted(got)} | " + _brief(r))
        if not hit and isinstance(r, dict) and not r.get("ok"):
            record_info(f"keyword「{q}」返回 error（本应命中，见上）", str(r.get("error"))[:120])

    # ── 4. skill/keyword + 乱码：0 命中，干净返回 ──
    r = await a._run_tool("search", {"query": "完全不相关zzz", "scope": "skill", "method": "keyword"})
    ok = isinstance(r, dict) and r.get("ok") and not r.get("candidates") and "未命中" in str(r.get("note", ""))
    record("keyword「乱码」0 命中且干净", ok, _brief(r))

    # ── 5. 空 query：ok=false + 明确错误 ──
    r = await a._run_tool("search", {"query": "", "scope": "skill", "method": "vector"})
    ok = isinstance(r, dict) and not r.get("ok") and "缺少" in str(r.get("error", ""))
    record("空 query（skill）拦截", ok, _brief(r))

    r = await a._run_tool("search", {"query": "  ", "scope": "web"})
    ok = isinstance(r, dict) and not r.get("ok") and "缺少" in str(r.get("error", ""))
    record("空 query（web）拦截", ok, _brief(r))

    # ── 6. 闲聊模式 skill：闸门拦截 ──
    chat = Agent(device_id="verify-chat")
    chat.hired = False
    r = await chat._run_tool("search", {"query": "挂号", "scope": "skill", "method": "vector"})
    ok = isinstance(r, dict) and not r.get("ok") and "闲聊" in str(r.get("error", ""))
    record("闲聊模式 scope=skill 被闸门拦", ok, _brief(r))

    # ── 7. web 博查：闲聊 + hired（信息性，离线/无 key 记为 INFO）──
    for label, agent in (("闲聊 web", chat), ("hired web", a)):
        try:
            r = await agent._run_tool("search", {"query": "南京今天天气", "scope": "web"})
            if isinstance(r, dict) and r.get("ok"):
                pages = r.get("pages") or []
                ts = "有" if (r.get("top_summary") or "") else "无"
                record_info(f"{label} 博查成功",
                            f"pages={len(pages)} top_summary={ts} answer={str(r.get('answer'))[:40]}")
            else:
                err = str((r or {}).get("error", "未知")) if isinstance(r, dict) else str(r)
                if "未配置" in err or "搜索失败" in err or "connect" in err.lower():
                    record_info(f"{label} 博查（环境不可用）", err[:120])
                else:
                    record(f"{label} 博查异常返回", False, err[:120])
        except Exception as e:  # 意料外的异常 → FAIL
            record(f"{label} 博查抛异常", False, f"{type(e).__name__}: {e}")

    # ── 汇总 ──
    fails = [r for r in _results if not r[1]]
    print("\n===== 汇总 =====")
    print(f"用例 {len(_results)} 个，FAIL {len(fails)} 个")
    for name, ok, _ in _results:
        if not ok:
            print(f"  ✗ {name}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
