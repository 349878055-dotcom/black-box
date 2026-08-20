"""
配置管理 — 从 config.json + 环境变量加载。

本项目 = 手机端 + 云端编排（仅执行 skill，无探索/browser-use）。
配置项：服务、LLM、认证/配对、通用 skill 密钥（skills.<id>.api_key）。
"""
import json
import os
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

_CONFIG = {
    "host": os.environ.get("ORCH_HOST", "0.0.0.0"),
    "port": int(os.environ.get("ORCH_PORT", 19000)),
    "debug": os.environ.get("ORCH_DEBUG", "false").lower() == "true",

    "llm_api_key": "",
    "llm_base_url": "https://api.deepseek.com/v1",
    "llm_model": "deepseek-v4-flash",

    "jwt_secret": "",
    "auth_enabled": True,
    "pair_password": os.environ.get("PAIR_PASSWORD", "123456"),

    "bocha_api_key": "",
    # skill_id -> {api_key: "...", ...}；不再为每个平台单独开顶层字段
    "skill_secrets": {},
}

# config.json 是否已成功加载。未加载时 get()/skill_secret() 会触发 _load_config()；
# 成功加载后置 True，避免每次 get()（尤其 llm_api_key 未配置时）都重复解析 JSON。
_LOADED = False


def _load_config():
    """从 config.json 加载配置（成功后置 _LOADED，幂等）。"""
    global _LOADED
    cfg_path = PROJECT_ROOT / "cloud" / "config.json"
    if not cfg_path.exists():
        return  # 文件尚未出现：保持未加载，get() 会重试（文件探测很便宜）
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    _LOADED = True

    qwen = data.get("qwen") or data.get("bailian") or {}
    deepseek = data.get("deepseek") or {}
    if qwen.get("api_key") and qwen.get("base_url"):
        prov, provider = qwen, "qwen"
    elif deepseek.get("api_key"):
        prov, provider = deepseek, "deepseek"
    elif qwen.get("api_key"):
        prov, provider = qwen, "qwen"
    else:
        prov, provider = {}, "deepseek"
    if prov.get("api_key"):
        _CONFIG["llm_api_key"] = prov["api_key"]
    if prov.get("base_url"):
        _CONFIG["llm_base_url"] = prov["base_url"]
    if prov.get("model"):
        _CONFIG["llm_model"] = prov["model"]
    _CONFIG["llm_provider"] = provider

    auth = data.get("auth", {})
    if auth.get("api_key"):
        _CONFIG["jwt_secret"] = auth["api_key"]
    if auth.get("pair_password"):
        _CONFIG["pair_password"] = str(auth["pair_password"])
    if "auth_enabled" in auth:
        _CONFIG["auth_enabled"] = bool(auth["auth_enabled"])

    bocha = data.get("bocha", {}) or {}
    if bocha.get("api_key"):
        _CONFIG["bocha_api_key"] = str(bocha["api_key"])

    secrets: dict = dict(_CONFIG.get("skill_secrets") or {})
    # 新约定：skills.<skill_id>.api_key
    for sid, block in (data.get("skills") or {}).items():
        if not isinstance(block, dict):
            continue
        sid = str(sid or "").strip()
        if not sid:
            continue
        cur = dict(secrets.get(sid) or {})
        cur.update({k: v for k, v in block.items() if v is not None})
        secrets[sid] = cur
    # 兼容旧键 tuniu.api_key → skills.tuniu
    tuniu = data.get("tuniu", {}) or {}
    if tuniu.get("api_key"):
        cur = dict(secrets.get("tuniu") or {})
        cur.setdefault("api_key", str(tuniu["api_key"]))
        secrets["tuniu"] = cur
    _CONFIG["skill_secrets"] = secrets

    # qwen 复用上方第 43 行已解析的变量（不再重复 data.get）
    if qwen.get("api_key"):
        _CONFIG["qwen_api_key"] = str(qwen["api_key"])
        _CONFIG["bailian_api_key"] = str(qwen["api_key"])
        _CONFIG["vision_api_key"] = str(qwen["api_key"])
    # 视觉模型（云端看图员）单独从 bailian 段读：base_url/model（key 与 qwen 共用）
    bailian_cfg = data.get("bailian") or {}
    if bailian_cfg.get("api_key"):
        _CONFIG["bailian_base_url"] = str(
            bailian_cfg.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1")
        _CONFIG["bailian_model"] = str(
            bailian_cfg.get("model") or "qwen3-vl-flash")


def get(key: str, default=None):
    """获取配置项（首次调用/文件尚未出现时加载 config.json）。"""
    if not _LOADED:
        _load_config()
    return _CONFIG.get(key, default)


def skill_secret(skill_id: str, key: str = "api_key", default: str = "") -> str:
    """读某 skill 的密钥：config.json → skills.<id>.<key>（兼容旧 tuniu.api_key）。"""
    if not _LOADED:
        _load_config()
    block = (_CONFIG.get("skill_secrets") or {}).get(str(skill_id or "").strip()) or {}
    val = block.get(key)
    return str(val) if val not in (None, "") else default


_load_config()
