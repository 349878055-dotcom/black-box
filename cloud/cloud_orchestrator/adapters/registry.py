"""
skill 总注册表（平台逆向 API）— 主代理 skill_list / skill_run 的依据。

本仓库只「消费 skill」：每个 skill = 一个平台逆向 API，按「每 skill 一个文件夹」组织：
    adapters/skills/<id>/
        contract.json   # 功能清单（methods / flow / capability / 正确返回 success_ret / 错误返回 error_ret）
        api.py          # 函数实现类（*API，requests 直调 HTTP 接口）
        register.py     # 注册接入：REGISTER = {id, name, class, flow, methods, ...}

总注册表扫描 skills/*/register.py 自动加载：供应商交付 skill（文件夹 + 3 文件）放进来即接入。
适配器实例全局保持（session 登录态不丢）。

2026-08-07 改造：
- 从「单一 ADAPTERS 大 dict」重构为「每 skill 文件夹 + 3 文件（contract/api/register）」；
- registry.py 只做总注册表：扫描加载 + 执行（skill_list / skill_run）。
"""
from __future__ import annotations

import importlib
import logging
import os

logger = logging.getLogger("xiami.registry")

_SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
ADAPTERS: dict[str, dict] = {}


def _load_skills() -> None:
    """扫描 skills/ 目录，加载每个 skill 的 register.py（REGISTER 元数据）。"""
    global ADAPTERS
    ADAPTERS = {}
    if not os.path.isdir(_SKILLS_DIR):
        logger.warning("skills 目录不存在: %s", _SKILLS_DIR)
        return
    for entry in sorted(os.listdir(_SKILLS_DIR)):
        d = os.path.join(_SKILLS_DIR, entry)
        if not os.path.isdir(d) or entry.startswith("_"):
            continue
        if not os.path.isfile(os.path.join(d, "register.py")):
            continue
        try:
            mod = importlib.import_module(f"{__package__}.skills.{entry}.register")
            meta = dict(getattr(mod, "REGISTER", {}) or {})
            cls = meta.get("class")
            if isinstance(cls, str):          # 兼容字符串类名
                cls = getattr(mod, cls)
            meta["class"] = cls
            ADAPTERS[meta.get("id", entry)] = meta
            logger.info("[registry] 加载 skill=%s methods=%d",
                        meta.get("id", entry), len(meta.get("methods") or {}))
        except Exception as e:
            logger.warning("加载 skill %s 失败: %s", entry, e)


_load_skills()


def _make_executor(device_id: str):
    """构造手机执行通道（第 2 条两段式）：async (blueprint) -> skill_result dict。

    绑定 bridge.send_skill_request：云端不再直发平台请求，
    手机真实 IP 直连平台，回传原始响应由云端 API 解析层处理。
    设备未在线 -> bridge 返回 {ok:False, error:...}，方法如实上报。
    """
    async def executor(blueprint: dict) -> dict:
        from ..channel.bridge import bridge
        return await bridge.send_skill_request(device_id, blueprint or {})
    return executor


def _get_instance(platform: str, executor=None):
    cls = ADAPTERS[platform]["class"]
    if isinstance(cls, str):
        cls = globals().get(cls)  # 兼容发布生成/手写的字符串类名
    if not cls:
        return None
    # 每次新建实例：executor 绑定设备；登录态从持久化文件/手机凭据恢复
    return cls(executor=executor) if executor else cls()


def list_skills() -> list[dict]:
    """skill_list：所有 skill（平台逆向 API）及其能力（含分层 flow 索引）。

    system_only 方法（如途牛登录 4 步）只供系统内部 _ensure_login 编排调用，
    对 LLM 不可见，避免 AI 自行调用登录方法导致流程混乱。
    """
    out = []
    for platform, cfg in ADAPTERS.items():
        methods = [{"name": m, **info} for m, info in cfg["methods"].items()
                   if not info.get("system_only")]
        out.append({
            "skill": platform,
            "name": cfg["name"],
            "flow": cfg.get("flow", []),   # 分层业务地图（先看这个，按步骤走）
            "methods": methods,
            # 能力边界（Skill工作台方法论 §1.55）：query=只能查 / operate_sms=手机号+短信能操作 / operate_wechat=需微信授权（我们 App 不能代做）
            "capability": cfg.get("capability", ""),
            "capability_note": cfg.get("capability_note", ""),
        })
    return out


async def run(skill: str, method: str, params: dict | None = None, device_id: str = "") -> dict:
    """skill_run（第 2 条两段式）：云端组装蓝图 -> 经 bridge 下发手机 -> 手机直连平台 ->
    回传 skill_result -> 云端解析成结构化数据返回（与旧直发返回一致）。

    device_id 非空 -> 平台请求全部由手机发出（云端不直发，防封机房）；
    device_id 为空 -> 传 executor=None：
        glyy 已删除云端直发降级（2026-08-06）→ 直接返回「未注入 executor」报错；
        tuniu MCP 保留原有降级（单机测试/无手机通道的 API 入口）。
    """
    cfg = ADAPTERS.get(skill or "")
    if not cfg:
        return {"ok": False, "error": f"skill 不存在：{skill or '空'}"}
    methods_map = cfg["methods"]
    if method not in methods_map:
        return {"ok": False, "error": f"skill {skill} 无方法：{method}"}
    # 第 7 条降级兜底：带 device_id（App 主代理路径）但手机离线 → 不执行也不云端直发
    if device_id:
        try:
            from ..channel.bridge import bridge
            online = bridge.online_devices()
            if not bridge.has(device_id):
                logger.warning("[registry] 手机离线拦截 skill=%s method=%s device=%s 在线=%s",
                               skill, method, device_id, online)
                return {"ok": False,
                        "error": f"手机未在线（请打开 App 保持在线），已停止执行避免云端直发",
                        "skill": skill, "method": method}
        except Exception as e:
            logger.warning("[registry] bridge 检查异常: %s", e)
    logger.info("[registry] run skill=%s method=%s device=%s", skill, method, device_id)
    try:
        executor = _make_executor(device_id) if device_id else None
        inst = _get_instance(skill, executor)
        if inst is None:
            return {"ok": False, "error": f"skill {skill} 适配器加载失败"}
        fn = getattr(inst, method)
        data = await fn(**(params or {}))
        # 登录态缺失/失效 → 返回 need_login 标记（供主代理自动触发登录）
        if isinstance(data, dict) and data.get("need_login"):
            return {"ok": False, "need_login": True, "skill": skill, "method": method,
                    "error": str(data.get("error") or "需要登录")}
        return {"ok": True, "skill": skill, "method": method, "data": data}
    except Exception as e:
        return {"ok": False, "error": f"{skill}.{method} 异常：{e}"}
