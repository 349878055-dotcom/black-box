"""
LLM 客户端 — DeepSeek API 统一入口

封装 API 调用、重试、超时、错误处理。
"""
import json
import time
import httpx
from ..config import get


class LLMClient:
    """DeepSeek / 兼容 OpenAI API 的 LLM 客户端"""

    def __init__(self):
        self.api_key = get("llm_api_key")
        self.base_url = get("llm_base_url")
        self.model = get("llm_model")
        self._client = httpx.Client(timeout=60)

    def chat(self, messages: list, **kwargs) -> str:
        """
        调用 LLM 聊天补全接口

        Args:
            messages: [{"role": "user"|"assistant"|"system", "content": "..."}]
            **kwargs: temperature, max_tokens, response_format 等

        Returns:
            模型回复文本

        Raises:
            RuntimeError: API 调用失败
        """
        data = self._chat_raw(messages, **kwargs)
        text = data["choices"][0]["message"].get("content") or ""
        return text.strip()

    def chat_tools(self, messages: list, tools: list, **kwargs) -> dict:
        """
        原生 function calling（Cursor / OpenAI 兼容）。

        Returns:
            {
              "message": 原始 assistant message（可直接追加进 messages）,
              "text": 纯文本（无 tool 时）,
              "tool_calls": [{"id","name","arguments"}, ...],
            }
        """
        if not tools:
            text = self.chat(messages, **kwargs)
            return {
                "message": {"role": "assistant", "content": text},
                "text": text,
                "tool_calls": [],
            }

        # 不要 json_object；与 tools 冲突
        kwargs.pop("response_format", None)
        raw = self._chat_raw(
            messages,
            tools=tools,
            tool_choice=kwargs.pop("tool_choice", "auto"),
            **kwargs,
        )
        msg = raw["choices"][0]["message"]
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args_raw = fn.get("arguments") or "{}"
            if isinstance(args_raw, str):
                try:
                    args = json.loads(args_raw) if args_raw.strip() else {}
                except json.JSONDecodeError:
                    args = {"_raw": args_raw}
            elif isinstance(args_raw, dict):
                args = args_raw
            else:
                args = {}
            tool_calls.append({
                "id": tc.get("id") or f"call_{len(tool_calls)}",
                "name": str(fn.get("name") or "").strip(),
                "arguments": args if isinstance(args, dict) else {},
            })
        text = (msg.get("content") or "").strip()
        # 规范化写回，便于追加 history
        out_msg = {
            "role": "assistant",
            "content": msg.get("content"),
        }
        if msg.get("tool_calls"):
            out_msg["tool_calls"] = msg["tool_calls"]
        return {"message": out_msg, "text": text, "tool_calls": tool_calls}

    def _chat_raw(self, messages: list, **kwargs) -> dict:
        """底层 chat/completions，返回完整 JSON。"""
        if not self.api_key:
            raise RuntimeError("LLM API Key 未配置，请检查 cloud/config.json 中的 deepseek.api_key")

        url = f"{self.rstrip(self.base_url)}/chat/completions"
        body = {
            "model": kwargs.pop("model", self.model),
            "messages": messages,
            "temperature": kwargs.pop("temperature", 0.7),
            "max_tokens": kwargs.pop("max_tokens", 4096),
            **kwargs,
        }
        body.setdefault("thinking", {"type": "disabled"})

        max_retries = 2
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                resp = self._client.post(url, json=body, headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                })
                if resp.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException as e:
                last_error = f"LLM 请求超时: {e}"
                time.sleep(1)
            except httpx.HTTPStatusError as e:
                last_error = f"LLM HTTP {e.response.status_code}: {e.response.text[:200]}"
                if e.response.status_code >= 500:
                    time.sleep(1)
                    continue
                break
            except Exception as e:
                last_error = f"LLM 调用异常: {e}"
                break
        raise RuntimeError(last_error or "LLM 调用失败")

    def chat_json(self, messages: list, **kwargs) -> dict:
        """
        调用 LLM 并期望返回 JSON

        会自动添加 response_format={type: "json_object"} 参数。
        兜底：若首次输出非合法 JSON（偶发夹带解释/代码块围栏），
        先尝试截取花括号范围抢救；再不行就让模型重出一次，只输出 JSON。
        """
        text = self.chat(messages, response_format={"type": "json_object"}, **kwargs)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        salvaged = self._salvage_json(text)
        if salvaged is not None:
            return salvaged

        retry_messages = messages + [
            {"role": "assistant", "content": (text or "")[:1000]},
            {"role": "user", "content": "上面的回复不是合法 JSON。请只输出一个合法的 JSON 对象，不要任何解释、不要代码块围栏。"},
        ]
        text2 = self.chat(retry_messages, response_format={"type": "json_object"}, **kwargs)
        return json.loads(text2)  # 仍失败则抛出，交上层展示真实错误（铁律：不包装）

    @staticmethod
    def _salvage_json(text: str):
        """从可能夹带围栏/解释的文本里抢救一个 JSON 对象；失败返回 None。"""
        if not isinstance(text, str):
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def rstrip(url: str) -> str:
        return url.rstrip("/")


# 全局单例
_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
