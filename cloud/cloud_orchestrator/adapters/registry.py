"""
skill 总注册表 — 主代理 skill_list / skill_run 的依据。

skill 挂在个人身上，签名 = owner_id/skill_id（各人各的，不互相覆盖）：
    store/archive_center/skill_archive/<owner_id>/skills/<skill_id>/
"""
from __future__ import annotations

import importlib
import logging
import os
import sys

logger = logging.getLogger("xiami.registry")

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILL_ARCHIVE = os.path.normpath(
    os.path.join(_HERE, "..", "store", "archive_center", "skill_archive")
)
_ROOT_PKG = __package__.rsplit(".", 1)[0]  # cloud_orchestrator

# key = "owner_id/skill_id"
ADAPTERS: dict[str, dict] = {}


def skill_sig(owner_id: str, skill_id: str) -> str:
    return f"{str(owner_id or '').strip()}/{str(skill_id or '').strip()}"


def get_adapter(skill_id: str, owner_id: str = "") -> dict | None:
    """按人签名取 skill。有 owner 时精确取；无 owner 时仅当全局唯一才返回。"""
    sid = str(skill_id or "").strip()
    oid = str(owner_id or "").strip()
    if not sid:
        return None
    if oid:
        return ADAPTERS.get(skill_sig(oid, sid))
    hits = [c for c in ADAPTERS.values() if str(c.get("id") or "") == sid]
    if len(hits) == 1:
        return hits[0]
    return None


def _load_skills() -> None:
    """扫描 skill_archive/<人>/skills/<skill>/register.py。"""
    global ADAPTERS
    ADAPTERS = {}
    if not os.path.isdir(_SKILL_ARCHIVE):
        logger.warning("skill 档案目录不存在: %s", _SKILL_ARCHIVE)
        return
    for owner in sorted(os.listdir(_SKILL_ARCHIVE)):
        if owner.startswith("_") or owner in ("seed",):
            continue
        person_dir = os.path.join(_SKILL_ARCHIVE, owner)
        skills_dir = os.path.join(person_dir, "skills")
        if not os.path.isdir(skills_dir):
            continue
        for entry in sorted(os.listdir(skills_dir)):
            d = os.path.join(skills_dir, entry)
            if not os.path.isdir(d) or entry.startswith("_"):
                continue
            if not os.path.isfile(os.path.join(d, "register.py")):
                continue
            try:
                mod_path = (
                    f"{_ROOT_PKG}.store.archive_center.skill_archive"
                    f".{owner}.skills.{entry}.register"
                )
                # 热更新（问题⑧）：import_module 对已加载模块走缓存，须 reload
                # 才能读到磁盘最新内容（改 contract/register 后进程内即时生效）。
                # 首次加载时模块不在 sys.modules → 不 reload（避免 register.py 被执行两遍、
                # 副作用重复触发）；二次扫描（reload_skills 热更新）才 reload。
                was_loaded = mod_path in sys.modules
                mod = importlib.import_module(mod_path)
                if was_loaded:
                    try:
                        mod = importlib.reload(mod)
                    except Exception as _re:
                        logger.debug("reload %s 失败（可能被删除/损坏）: %s", mod_path, _re)
                        continue
                meta = dict(getattr(mod, "REGISTER", {}) or {})
                cls = meta.get("class")
                if isinstance(cls, str):
                    cls = getattr(mod, cls)
                meta["class"] = cls
                meta["owner_id"] = owner
                sid = str(meta.get("id") or entry).strip() or entry
                meta["id"] = sid
                sig = skill_sig(owner, sid)
                if sig in ADAPTERS:
                    logger.error(
                        "skill 签名冲突，跳过后加载：%s（目录 %s/%s）",
                        sig, owner, entry,
                    )
                    continue
                ADAPTERS[sig] = meta
                logger.info(
                    "[registry] 加载 sig=%s methods=%d",
                    sig, len(meta.get("methods") or {}),
                )
            except Exception as e:
                logger.warning("加载 skill %s/%s 失败: %s", owner, entry, e)


def reload_skills() -> None:
    """重新扫描磁盘 skill_archive，刷新 ADAPTERS（热更新用，进程不重启）。"""
    _load_skills()


def skills_fingerprint() -> str:
    """skill_archive 磁盘指纹：所有 register.py 相对路径 + mtime + size 的 MD5。

    用于检测才艺是否新增/修改/删除；变了需重建向量索引（get_index 自动做，问题⑧）。
    """
    import hashlib

    h = hashlib.md5()
    if os.path.isdir(_SKILL_ARCHIVE):
        for root, dirs, files in os.walk(_SKILL_ARCHIVE):
            dirs.sort()  # 保证确定性顺序
            for fn in sorted(files):
                if fn != "register.py":
                    continue
                p = os.path.join(root, fn)
                try:
                    st = os.stat(p)
                    rel = os.path.relpath(p, _SKILL_ARCHIVE)
                    h.update(f"{rel}:{st.st_mtime_ns}:{st.st_size};".encode("utf-8", "ignore"))
                except OSError:
                    continue
    return h.hexdigest()


_load_skills()


def is_ai_visible(info: dict | None) -> bool:
    """对话 AI 菜单可见：非 system_only，且非 stage=intermediate。"""
    if not isinstance(info, dict):
        return False
    if info.get("system_only"):
        return False
    if info.get("stage") == "intermediate":
        return False
    return True


def _make_executor(email: str):
    """构造手机执行通道：async (blueprint) -> skill_result dict。"""
    async def executor(blueprint: dict) -> dict:
        from ..channel.bridge import bridge
        return await bridge.send_skill_request(email, blueprint or {})
    return executor


def _get_instance(cfg: dict, executor=None):
    cls = cfg.get("class")
    if isinstance(cls, str):
        return None
    if not cls:
        return None
    return cls(executor=executor)


def list_skills(owner_id: str = "") -> list[dict]:
    """skill_list：已挂到个人身上的 skill；可按 owner_id 只看某人。"""
    want = str(owner_id or "").strip()
    out = []
    for sig, cfg in ADAPTERS.items():
        oid = str(cfg.get("owner_id") or "")
        if want and oid != want:
            continue
        sid = str(cfg.get("id") or "")
        methods = [{"name": m, **info} for m, info in (cfg.get("methods") or {}).items()
                   if is_ai_visible(info)]
        out.append({
            "skill": sid,
            "owner_id": oid,
            "sig": sig,
            "name": cfg.get("name", sid),
            "category": cfg.get("category", ""),
            "aliases": list(cfg.get("aliases") or []),
            "methods": methods,
            "rules": cfg.get("rules") or [],
            "capability": cfg.get("capability", ""),
            "capability_note": cfg.get("capability_note", ""),
            "deliver": cfg.get("deliver", ""),
            "payment": cfg.get("payment") or {},
        })
    return out


def skills_for_owner(owner_id: str) -> list[str]:
    """某人 skill 档案下已注册的 skill id 列表。"""
    oid = str(owner_id or "").strip()
    if not oid:
        return []
    return [str(cfg.get("id") or "") for cfg in ADAPTERS.values()
            if str(cfg.get("owner_id") or "") == oid and cfg.get("id")]


def get_contract(skill_id: str, owner_id: str = "") -> dict | None:
    """读某 skill 的契约全文（read_skill 精读用）。支持拆分的 meta/login/methods/payment 多文件。

    有 owner 时精确取；无 owner 时仅当 id 全局唯一才返回。
    返回原始契约 dict：methods(含参数说明/requires)/auth/login/payment/
    human_touch/not_deliver/notes 等，供 AI 精读与边界。
    """
    sid = str(skill_id or "").strip()
    cfg = get_adapter(sid, owner_id)
    if not cfg:
        return None
    own = str(cfg.get("owner_id") or "") or str(owner_id or "").strip()
    skill_dir = os.path.join(_SKILL_ARCHIVE, own, "skills", sid)
    try:
        from ..store.archive_center.skill_archive import load_contract_parts
        return load_contract_parts(skill_dir)
    except Exception as e:
        logger.warning("读取契约失败 %s: %s", skill_dir, e)
        return None


async def run(skill: str, method: str, params: dict | None = None,
              email: str = "", owner_id: str = "") -> dict:
    """skill_run：按人签名查找 → 手机直连平台 → 回传解析。

    transport 只认 phone_only：无手机通道直接报错，绝不云端直发。
    """
    cfg = get_adapter(skill, owner_id)
    if not cfg:
        hint = f"（owner={owner_id}）" if owner_id else "（需指定 owner 或保证 id 全局唯一）"
        return {"ok": False, "error": f"才艺不存在：{skill or '空'}{hint}"}
    methods_map = cfg.get("methods") or {}
    if method not in methods_map:
        return {"ok": False, "error": f"才艺 {skill} 无方法：{method}"}
    transport = str(cfg.get("transport") or "phone_only").strip() or "phone_only"
    if transport != "phone_only":
        return {"ok": False, "skill": skill, "method": method,
                "error": f"才艺 {skill} 的 transport={transport} 已废弃，只允许 phone_only（云端不直连平台）"}
    if not email:
        return {"ok": False, "skill": skill, "method": method,
                "error": "未指定手机（email 为空），已停止执行避免云端直发"}
    try:
        from ..channel.bridge import bridge
        online = bridge.online_devices()
        if not bridge.has(email):
            logger.warning("[registry] 手机离线拦截 skill=%s method=%s device=%s 在线=%s",
                           skill, method, email, online)
            return {"ok": False,
                    "error": "手机未在线（请打开 App 保持在线），已停止执行避免云端直发",
                    "skill": skill, "method": method}
    except Exception as e:
        logger.warning("[registry] bridge 检查异常: %s", e)
        return {"ok": False, "skill": skill, "method": method,
                "error": f"手机通道检查失败：{e}"}
    logger.info("[registry] run sig=%s method=%s device=%s",
                skill_sig(cfg.get("owner_id", ""), skill), method, email)
    try:
        inst = _get_instance(cfg, _make_executor(email))
        if inst is None:
            return {"ok": False, "error": f"才艺 {skill} 适配器加载失败"}
        fn = getattr(inst, method)
        data = await fn(**(params or {}))
        if isinstance(data, dict) and data.get("need_login"):
            return {"ok": False, "need_login": True, "skill": skill, "method": method,
                    "error": str(data.get("error") or "需要登录")}
        # 业务失败/网络失败：skill 返回 {ok:false, ...} → 外层 ok=false + 透传原因给 AI，
        # 不再伪装成成功（原逻辑 data.ok=false 时仍返回 ok:true，AI 只看到空 data）
        if isinstance(data, dict) and data.get("ok") is False:
            err = str(data.get("error") or data.get("message") or "业务执行失败")
            return {"ok": False, "skill": skill, "method": method,
                    "error": err, "data": data}
        return {"ok": True, "skill": skill, "method": method, "data": data}
    except Exception as e:
        return {"ok": False, "error": f"{skill}.{method} 异常：{e}"}
