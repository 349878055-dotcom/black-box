"""云端看图员：把图片识别成文字（千问视觉 qwen3-vl-flash，OpenAI 兼容接口）。

设计（避免烧 token）：
- 图片只在客户发送的那一刻识别一次；
- 识别出的【文字】才进对话历史；图片本身不留存、不反复带。
这样每轮对话只多几十~几百 token，不会因为反复带 base64 图而爆 token。
"""
from __future__ import annotations

import json
import logging
import urllib.request

from ..config import get

logger = logging.getLogger("xiami.vision")

DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3-vl-flash"

DEFAULT_PROMPT = (
    "请识别这张图片里的全部文字信息并整理输出，包括姓名、证件号码、电话、地址等所有字段；"
    "如果是表格/卡片，按字段分行列出。只输出识别结果，不要解释。"
)


def _b64_to_data_url(b64: str, mime: str = "") -> str:
    b64 = (b64 or "").strip()
    if not b64:
        return ""
    if b64.startswith("data:"):
        return b64
    return f"data:{mime or 'image/jpeg'};base64,{b64}"


def describe_image(image_b64: str, prompt: str = "", mime: str = "") -> str:
    """把 base64 图片发给千问视觉模型识别，返回文字。失败/无 key 返回空串。"""
    api_key = get("vision_api_key") or get("bailian_api_key") or ""
    if not api_key:
        logger.warning("视觉模型 key 未配置（config.json 的 bailian.api_key）")
        return ""
    base_url = (get("bailian_base_url") or DEFAULT_BASE).rstrip("/")
    model = get("bailian_model") or DEFAULT_MODEL
    data_url = _b64_to_data_url(image_b64, mime)
    if not data_url:
        return ""

    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt or DEFAULT_PROMPT},
            ],
        }],
        "max_tokens": 800,
    }
    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.loads(r.read().decode())
        content = j["choices"][0]["message"]["content"]
        return str(content or "").strip()
    except Exception as e:
        logger.warning("视觉识别失败 model=%s: %s", model, e)
        return ""


if __name__ == "__main__":
    # 自测：传一张 base64 图（从文件读取）识别
    import sys
    import base64

    if len(sys.argv) < 2:
        print("用法: python -m cloud.cloud_orchestrator.core.vision <图片路径> [提示词]")
        raise SystemExit(1)
    with open(sys.argv[1], "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    prompt = sys.argv[2] if len(sys.argv) > 2 else ""
    out = describe_image(b64, prompt)
    print("== 识别结果 ==")
    print(out or "(无结果)")
