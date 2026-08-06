"""
index — 两级向量索引（平台级 + 功能级）+ 检索 + 小纸条生成。

设计（与用户确认的方案）：
- 第一级「平台向量」：每个 skill（平台）一条向量，描述词 = 平台名 + 一句话 + flow 步骤标题
- 第二级「功能向量」：每个方法一条向量，描述词 = 平台名 + 方法名 + desc + params + 所属流程步骤
- 客户一句话 → 平台级检索 top-1（+top-3 备选）→ 功能级检索 top-1~3 方法
- 输出「小纸条」：当前平台名 + 当前功能方法（方法名/desc/need_login/params）+ 流程地图 + 备选

降级：模型不可用（未安装/加载失败）时 get_prompt 返回 None，主代理回退到旧 skill_list 全量。
"""
from __future__ import annotations

import logging

import numpy as np

from . import embedder

logger = logging.getLogger("xiami.retrieval.index")


class RetrievalIndex:
    def __init__(self) -> None:
        # 平台级
        self.platform_items: list[dict] = []      # [{platform, text}]
        self.platform_vecs: np.ndarray | None = None  # N x D（归一化）
        # 功能级（每个方法一条）
        self.method_items: list[dict] = []        # [{platform, method, text, info, step}]
        self.method_vecs: np.ndarray | None = None    # M x D（归一化）
        self._ready = False

    # ─────────── 构建 ───────────
    def build(self, adapters: dict) -> bool:
        """从 registry.ADAPTERS 构建两级索引。返回是否成功（模型可用）。"""
        self.platform_items, self.method_items = self._collect(adapters)
        texts_p = [it["text"] for it in self.platform_items]
        texts_m = [it["text"] for it in self.method_items]

        # 一次编码全部（快）；模型不可用则返回 None
        pv = embedder.embed(texts_p)
        mv = embedder.embed(texts_m)
        if pv is None or mv is None:
            self._ready = False
            return False
        self.platform_vecs = np.array(pv, dtype=np.float32)
        self.method_vecs = np.array(mv, dtype=np.float32)
        self._ready = True
        logger.info("向量索引构建完成：平台 %d 个，方法 %d 条", len(texts_p), len(texts_m))
        return True

    @staticmethod
    def _collect(adapters: dict):
        """从 ADAPTERS 收集平台/方法文本。"""
        platform_items = []
        method_items = []
        for pid, cfg in adapters.items():
            name = cfg.get("name", pid)
            flow = cfg.get("flow") or []
            flow_titles = "；".join(f.get("title", "") for f in flow) or ""
            # 平台描述：平台名 + 别名 + 一句话 + 流程地图（别名让"鼓楼/途牛"等客户说法命中）
            aliases = cfg.get("aliases") or []
            alias_str = "、".join(aliases) if aliases else ""
            platform_text = f"{name}（{pid}）。别名：{alias_str}。业务流程：{flow_titles}"
            platform_items.append({"platform": pid, "text": platform_text})

            # 方法描述：平台名 + 方法名 + desc + params
            methods_map = dict(cfg.get("methods") or {})
            # 同一平台第二套实现（web_*）
            if cfg.get("web_methods"):
                methods_map = {**methods_map, **cfg["web_methods"]}
            for mname, minfo in methods_map.items():
                desc = minfo.get("desc", "")
                params = minfo.get("params") or {}
                param_str = "，".join(f"{k}={v}" for k, v in params.items())
                # 检索关键词（用户常见说法）→ 让"挂个号/查报告/买票"等命中
                kws = minfo.get("keywords") or []
                kw_str = "、".join(kws) if kws else ""
                # 找所属流程步骤
                step_title = ""
                for f in flow:
                    if mname in (f.get("methods") or []):
                        step_title = f.get("title", "")
                        break
                method_text = (f"{name}（{pid}）的「{mname}」功能：{desc}。"
                               f"用户常这样说：{kw_str}。参数：{param_str}。属于流程步骤：{step_title}")
                method_items.append({
                    "platform": pid,
                    "method": mname,
                    "text": method_text,
                    "info": {
                        "desc": desc,
                        "need_login": bool(minfo.get("need_login")),
                        "params": params,
                        "step": step_title,
                    },
                })
        return platform_items, method_items

    # ─────────── 检索 ───────────
    def search_platform(self, query: str, top_k: int = 3) -> list[dict]:
        """平台级检索：方法级聚合（先全平台方法检索，按平台聚合得分）。

        比「平台向量」更准：方法描述含丰富业务词（如"火车票搜索"），
        按方法命中聚合成平台 → "买票"必然落在途牛。
        返回 [{platform, score, text}] 按相似度降序。
        """
        if not self._ready:
            return []
        qv = self._embed_one(query)
        if qv is None:
            return []
        scores = self.method_vecs @ qv  # 已归一化 → 余弦
        # 每个平台取该平台方法中的最高分（命中即代表该平台相关）
        best: dict[str, float] = {}
        for i, item in enumerate(self.method_items):
            pid = item["platform"]
            s = float(scores[i])
            if pid not in best or s > best[pid]:
                best[pid] = s
        ranked = sorted(best.items(), key=lambda kv: -kv[1])[:top_k]
        # 平台名（从平台 items 找）
        name_map = {it["platform"]: it["text"].split("（")[0] for it in self.platform_items}
        return [{"platform": pid, "score": sc, "text": name_map.get(pid, pid)} for pid, sc in ranked]

    def search_method(self, query: str, platform: str | None = None, top_k: int = 3) -> list[dict]:
        """功能级检索：可限定平台。返回 [{platform, method, score, info, text}]。"""
        if not self._ready:
            return []
        qv = self._embed_one(query)
        if qv is None:
            return []
        scores = self.method_vecs @ qv
        idx = np.argsort(-scores)
        out = []
        for i in idx:
            item = self.method_items[i]
            if platform and item["platform"] != platform:
                continue
            out.append({"platform": item["platform"], "method": item["method"],
                        "score": float(scores[i]), "info": item["info"],
                        "text": item["text"]})
            if len(out) >= top_k:
                break
        return out

    def _embed_one(self, text: str):
        vecs = embedder.embed([text])
        if vecs is None:
            return None
        v = np.array(vecs[0], dtype=np.float32)
        n = np.linalg.norm(v)
        return v / n if n > 0 else v

    # ─────────── 小纸条 ───────────
    def make_note(self, user_text: str, current_skill: str | None = None,
                  top_platform: int = 3, top_method: int = 4) -> dict | None:
        """生成「小纸条」给主代理。返回 None 表示模型不可用（降级全量 skill_list）。

        返回：{
          "top_skill": 平台id, "top_name": 平台名,
          "note": 给 AI 的小纸条文本（当前平台 + 当前功能方法 + 流程地图 + 备选）
          "current_skill": 锁定的平台（可能没变）
          "changed": 是否切换了平台
        }
        """
        if not self._ready:
            return None
        plats = self.search_platform(user_text, top_k=top_platform)
        if not plats:
            return None
        top = plats[0]
        top_skill = top["platform"]
        changed = (current_skill is not None and top_skill != current_skill)

        # 功能级检索：在 top-1 平台内找最相关方法
        methods = self.search_method(user_text, platform=top_skill, top_k=top_method)
        # 平台名
        top_name = ""
        for it in self.platform_items:
            if it["platform"] == top_skill:
                top_name = it["text"].split("（")[0]
                break

        lines = [f"【当前平台】{top_name}（skill={top_skill}）",
                 f"【客户意图匹配到的方法】（按相关度）"]
        for m in methods:
            info = m["info"]
            params = "，".join(f"{k}={v}" for k, v in info["params"].items()) or "无"
            lines.append(f"- {m['method']}：{info['desc']}（需登录：{'是' if info['need_login'] else '否'}，参数：{params}）")
        # 平台流程地图
        from ..adapters.registry import ADAPTERS
        cfg = ADAPTERS.get(top_skill)
        if cfg and cfg.get("flow"):
            lines.append("【流程地图】" + " → ".join(f.get("title", "") for f in cfg["flow"]))
        # 备选平台
        if len(plats) > 1:
            alt = "、".join(f"{p['platform']}" for p in plats[1:])
            lines.append(f"【备选平台】{alt}（如客户意图不符可切换）")
        if changed:
            lines.append(f"【已从 {current_skill} 切换到 {top_skill}】")

        return {
            "top_skill": top_skill,
            "top_name": top_name,
            "note": "\n".join(lines),
            "current_skill": top_skill,
            "changed": changed,
        }

    def make_note_for(self, skill: str, user_text: str, top_method: int = 4) -> dict | None:
        """按指定平台生成小纸条（防抖时沿用当前平台用）。"""
        if not self._ready:
            return None
        from ..adapters.registry import ADAPTERS
        cfg = ADAPTERS.get(skill)
        if not cfg:
            return None
        methods = self.search_method(user_text, platform=skill, top_k=top_method)
        top_name = cfg.get("name", skill)
        lines = [f"【当前平台】{top_name}（skill={skill}）",
                 f"【客户意图匹配到的方法】（按相关度）"]
        for m in methods:
            info = m["info"]
            params = "，".join(f"{k}={v}" for k, v in info["params"].items()) or "无"
            lines.append(f"- {m['method']}：{info['desc']}（需登录：{'是' if info['need_login'] else '否'}，参数：{params}）")
        if cfg.get("flow"):
            lines.append("【流程地图】" + " → ".join(f.get("title", "") for f in cfg["flow"]))
        lines.append(f"【备选平台】其它平台（如客户意图明显不符可切换）")
        return {
            "top_skill": skill,
            "top_name": top_name,
            "note": "\n".join(lines),
            "current_skill": skill,
            "changed": False,
        }


# 全局单例
_index: RetrievalIndex | None = None


def get_index() -> RetrievalIndex | None:
    """全局单例索引（首次调用构建）。模型不可用返回 None。"""
    global _index
    if _index is None:
        _index = RetrievalIndex()
        from ..adapters.registry import ADAPTERS
        ok = _index.build(ADAPTERS)
        if not ok:
            _index = None
    return _index
