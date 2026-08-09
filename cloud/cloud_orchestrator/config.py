"""
配置管理 — 从 config.json + 环境变量加载。

本项目 = 手机端 + 云端编排（仅执行 skill，无探索/browser-use）。
配置项：服务（host/port/debug）、LLM（主代理大脑）、认证/配对。
"""
import json
import os
import pathlib

# 项目根目录（cloud/cloud_orchestrator/ 的父目录的父目录 = 项目根）
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# 默认配置
_CONFIG = {
    # ── 服务 ──
    "host": os.environ.get("ORCH_HOST", "0.0.0.0"),
    "port": int(os.environ.get("ORCH_PORT", 19000)),
    "debug": os.environ.get("ORCH_DEBUG", "false").lower() == "true",

    # ── LLM（主代理大脑）──
    "llm_api_key": "",
    "llm_base_url": "https://api.deepseek.com/v1",
    "llm_model": "deepseek-v4-flash",

    # ── 认证 / 配对 ──
    "jwt_secret": "",
    "auth_enabled": True,
    "pair_password": os.environ.get("PAIR_PASSWORD", "123456"),

    # ── 博查搜索（web_search 工具：快速查最新/通用信息）──
    "bocha_api_key": "",
    # ── 途牛 MCP（买票/订酒店，apiKey 请求头）──
    "tuniu_api_key": "",
}


def _load_config():
    """从 config.json 加载配置。"""
    cfg_path = PROJECT_ROOT / "cloud" / "config.json"
    if not cfg_path.exists():
        return
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    # LLM 提供方：qwen（千问）优先，其次 deepseek（均 OpenAI 兼容）
    prov = data.get("qwen") or data.get("deepseek") or {}
    if prov.get("api_key"):
        _CONFIG["llm_api_key"] = prov["api_key"]
    if prov.get("base_url"):
        _CONFIG["llm_base_url"] = prov["base_url"]
    if prov.get("model"):
        _CONFIG["llm_model"] = prov["model"]
    _CONFIG["llm_provider"] = "qwen" if data.get("qwen", {}).get("api_key") else "deepseek"

    auth = data.get("auth", {})
    if auth.get("api_key"):
        _CONFIG["jwt_secret"] = auth["api_key"]
    if auth.get("pair_password"):
        _CONFIG["pair_password"] = str(auth["pair_password"])
    if "auth_enabled" in auth:
        _CONFIG["auth_enabled"] = bool(auth["auth_enabled"])

    # 博查搜索 key（web_search 工具）
    bocha = data.get("bocha", {}) or {}
    if bocha.get("api_key"):
        _CONFIG["bocha_api_key"] = str(bocha["api_key"])

    # 途牛 MCP key
    tuniu = data.get("tuniu", {}) or {}
    if tuniu.get("api_key"):
        _CONFIG["tuniu_api_key"] = str(tuniu["api_key"])

    # 千问 Qwen / 百炼（routes 向量搜索 / vision 共用，与 LLM 同一 key；云端配置键可能是 qwen 或 bailian）
    qwen = data.get("qwen") or data.get("bailian") or {}
    if qwen.get("api_key"):
        _CONFIG["qwen_api_key"] = str(qwen["api_key"])
        _CONFIG["bailian_api_key"] = str(qwen["api_key"])
        _CONFIG["vision_api_key"] = str(qwen["api_key"])


def get(key: str, default=None):
    """获取配置项（首次调用时加载 config.json）。"""
    if not _CONFIG.get("llm_api_key"):
        _load_config()
    return _CONFIG.get(key, default)


# 应用启动时加载一次
_load_config()
