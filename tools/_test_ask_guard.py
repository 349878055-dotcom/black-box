"""收尾硬闸（Bug 1 根治）验证：_needs_ask_user 判定 + 自定义 ReAct 图打回行为。"""
import asyncio
import sys

sys.path.insert(0, "cloud")

from cloud_orchestrator.core.agent import Agent


def test_needs_ask_user():
    a = Agent()
    cases = [
        # (文字, 期望是不是「在向客户索取办事信息」)
        ("要买什么票？出发地、目的地、日期？", True),   # Bug 1 主句式
        ("请把出发地、目的地、日期发我。", True),       # 无问号命令式索取
        ("请问您想买什么票？", True),
        ("请提供您的手机号", True),                    # 无问号索取短语
        ("还需要我帮您做什么吗？", False),              # 客套收尾不误伤
        ("东京热不热？", False),                        # 闲聊不误伤
        ("你吃了吗？", False),
        ("好的，我来帮您处理。", False),                # 零工具但非索取（交给零工具补丁）
    ]
    ok = True
    for text, exp in cases:
        got = a._needs_ask_user(text)
        mark = "PASS" if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"[{mark}] _needs_ask_user({text!r}) = {got}  (期望 {exp})")
    return ok


def test_looks_like_task():
    a = Agent()
    cases = [
        ("我要买票", True),
        ("帮我订明天的机票", True),
        ("挂个号", True),
        ("东京热不热", False),   # 咨询不是办事
        ("今天天气怎么样", False),
    ]
    ok = True
    for text, exp in cases:
        got = a._looks_like_task(text)
        mark = "PASS" if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"[{mark}] _looks_like_task({text!r}) = {got}  (期望 {exp})")
    return ok


async def test_graph_guard():
    """统一闸逻辑已迁入 LangGraph 图（graph_native._after_model）；此处测 Agent 判定函数。"""
    checks = [
        ("统一闸·索取句", "要买什么票？出发地、目的地、日期？", True),
        ("咨询放行", "今天东京28度。", False),
    ]
    a = Agent()
    ok = True
    for name, text, exp in checks:
        got = a._needs_ask_user(text)
        mark = "PASS" if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"[{mark}] {name}: _needs_ask_user={got} (期望 {exp})")
    return ok


async def test_ask_user_then_plain_still_rebuke():
    """ask_user 走 LangGraph interrupt；纯文字索取仍由 _needs_ask_user 判定。"""
    a = Agent()
    ok = a._needs_ask_user("请把您的目的地发我")
    print(f"[{'PASS' if ok else 'FAIL'}] 纯文字索取判定: {ok} (期望 True)")
    return ok


async def main():
    r1 = test_needs_ask_user()
    r2 = test_looks_like_task()
    r3 = await test_graph_guard()
    r4 = await test_ask_user_then_plain_still_rebuke()
    print("\n全部通过" if (r1 and r2 and r3 and r4) else "\n存在 FAIL")


if __name__ == "__main__":
    asyncio.run(main())
