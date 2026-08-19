"""
index — 两级向量索引（平台级 + 功能级）+ 检索 + 小纸条生成。

设计（与用户确认的方案，2026 去 flow：流程不人工定义，靠方法 requires 自包含）：
- 第一级「平台向量」：每个 skill（平台）一条向量，描述词 = 平台名 + 别名 + 能力说明
- 第二级「功能向量」：每个方法一条向量，描述词 = 平台名 + 方法名 + desc + params + requires/provides
- 客户一句话 → 平台级检索 top-1（+top-3 备选）→ 功能级检索 top-1~3 方法
- 输出「小纸条」：当前平台名 + 当前功能方法（方法名/desc/need_login/params）+ 备选

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
        for sig, cfg in adapters.items():
            pid = str(cfg.get("id") or "")
            if not pid and "/" in str(sig):
                pid = str(sig).rsplit("/", 1)[-1]
            if not pid:
                pid = str(sig)
            owner = str(cfg.get("owner_id") or "")
            name = cfg.get("name", pid)
            # 去 flow（用户铁令）：平台描述不拼业务流程，只靠名字/别名/能力说明
            aliases = cfg.get("aliases") or []
            alias_str = "、".join(aliases) if aliases else ""
            capability = str(cfg.get("capability_note") or "").strip()
            platform_text = (f"{name}（{pid}）。别名：{alias_str}。{capability}"
                             if capability else f"{name}（{pid}）。别名：{alias_str}。")
            platform_items.append({
                "platform": pid, "owner_id": owner, "sig": sig, "text": platform_text,
            })

            # 方法描述：平台名 + 方法名 + desc + params
            methods_map = dict(cfg.get("methods") or {})
            # 同一平台第二套实现（web_*）
            if cfg.get("web_methods"):
                methods_map = {**methods_map, **cfg["web_methods"]}
            for mname, minfo in methods_map.items():
                # system_only / intermediate 不进小纸条（登录编排与自动补参）
                if minfo.get("system_only") or minfo.get("stage") == "intermediate":
                    continue
                desc = minfo.get("desc", "")
                params = minfo.get("params") or {}
                param_str = "，".join(f"{k}={v}" for k, v in params.items())
                # 检索关键词（用户常见说法）→ 让"挂个号/查报告/买票"等命中
                kws = minfo.get("keywords") or []
                kw_str = "、".join(kws) if kws else ""
                # 前置依赖（requires）→ 告诉 LLM 参数从哪个方法拿（原子化 + 前置依赖）
                reqs = [r for r in (minfo.get("requires") or []) if isinstance(r, dict)]
                req_str = "；".join(f"{r.get('param', '')}←{r.get('from', '')}.{r.get('field', '')}"
                                    for r in reqs) if reqs else ""
                # 提供编码（provides）→ 点破源头方法返回哪些编码给谁用
                provs = minfo.get("provides") or {}
                prov_str = "、".join(k for k in provs.keys()) if provs else ""
                extra = []
                if req_str:
                    extra.append(f"前置依赖：{req_str}（先调这些方法拿真实编码，禁止编造）")
                if prov_str:
                    extra.append(f"提供编码：{prov_str}（供后续方法使用）")
                method_text = (f"{name}（{pid}）的「{mname}」功能：{desc}。"
                               f"用户常这样说：{kw_str}。参数：{param_str}。")
                if extra:
                    method_text += "。" + "。".join(extra)
                method_items.append({
                    "platform": pid,
                    "owner_id": owner,
                    "sig": sig,
                    "method": mname,
                    "text": method_text,
                    "info": {
                        "desc": desc,
                        "need_login": bool(minfo.get("need_login")),
                        "params": params,
                        "requires": reqs,
                    },
                })
        return platform_items, method_items

    # ─────────── 检索 ───────────
    def search_platform(self, query: str, top_k: int = 3,
                        allowed_skills: list[str] | None = None,
                        owner_id: str | None = None) -> list[dict]:
        """平台级检索：方法级聚合（先全平台方法检索，按平台聚合得分）。

        问题⑦（搜索范围统一）：allowed_skills/owner_id 非空时，只在指定平台/人内检索，
        不再"全库检索再事后筛"——避免名下才艺被其它才艺挤出 top-k 而漏掉。

        返回 [{platform, owner_id, score, text}] 按相似度降序。
        """
        if not self._ready:
            return []
        qv = self._embed_one(query)
        if qv is None:
            return []
        allow = {str(s) for s in (allowed_skills or []) if str(s)}
        only_owner = str(owner_id or "").strip()
        scores = self.method_vecs @ qv  # 已归一化 → 余弦
        # 每个人的每个 skill 单独计分（签名隔离）；问题⑦：检索前先按平台/人收窄
        best: dict[tuple[str, str], float] = {}
        for i, item in enumerate(self.method_items):
            if only_owner and str(item.get("owner_id") or "") != only_owner:
                continue
            if allow and item["platform"] not in allow:
                continue
            key = (str(item.get("owner_id") or ""), item["platform"])
            s = float(scores[i])
            if key not in best or s > best[key]:
                best[key] = s
        ranked = sorted(best.items(), key=lambda kv: -kv[1])[:top_k]
        name_map = {
            (str(it.get("owner_id") or ""), it["platform"]): it["text"].split("（")[0]
            for it in self.platform_items
        }
        return [
            {"platform": pid, "owner_id": oid, "score": sc,
             "text": name_map.get((oid, pid), pid)}
            for (oid, pid), sc in ranked
        ]

    def search_method(self, query: str, platform: str | None = None, top_k: int = 3,
                      owner_id: str | None = None) -> list[dict]:
        """功能级检索：可限定平台与人。返回 [{platform, method, score, info, text}]。"""
        if not self._ready:
            return []
        qv = self._embed_one(query)
        if qv is None:
            return []
        scores = self.method_vecs @ qv
        idx = np.argsort(-scores)
        oid = str(owner_id or "").strip()
        out = []
        for i in idx:
            item = self.method_items[i]
            if platform and item["platform"] != platform:
                continue
            if oid and str(item.get("owner_id") or "") != oid:
                continue
            out.append({"platform": item["platform"], "method": item["method"],
                        "owner_id": item.get("owner_id", ""),
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
                  top_platform: int = 3, top_method: int = 4,
                  allowed_skills: list[str] | None = None,
                  owner_id: str | None = None) -> dict | None:
        """生成「小纸条」给主代理。返回 None 表示模型不可用（降级 skill_list）。

        allowed_skills：非空时只在这些人设名下平台内检索（找人会话）；
        owner_id：按人签名过滤，避免串到别人同名 skill。
        """
        if not self._ready:
            return None
        allow = [str(s).strip() for s in (allowed_skills or []) if str(s).strip()]
        allow_set = set(allow)
        oid = str(owner_id or "").strip()

        # 问题⑦：向量检索也限定在名下才艺范围内做（与 keyword 行为统一）
        plats = self.search_platform(
            user_text,
            top_k=max(top_platform, len(allow) or top_platform),
            allowed_skills=allow or None,
            owner_id=oid or None,
        )
        # 下面过滤作为双保险（检索已按平台/人收窄，通常全部通过）
        if oid:
            plats = [p for p in plats if str(p.get("owner_id") or "") == oid]
        if allow_set:
            plats = [p for p in plats if p["platform"] in allow_set]
        if not plats:
            return None
        top = plats[0]
        top_skill = top["platform"]
        changed = (current_skill is not None and top_skill != current_skill)

        def _name(skill: str) -> str:
            for it in self.platform_items:
                if it["platform"] == skill and (not oid or str(it.get("owner_id") or "") == oid):
                    return it["text"].split("（")[0]
            return skill

        def _block(skill: str, rank: int, score: float) -> tuple[list[str], dict]:
            """单个候选平台的方法块 + 精简信息。问题⑥⑦：3 个候选都带完整信息，AI 自己挑。

            score：平台级相似度，随候选返回，供上层做相似度阈值过滤（如乱码/无关话不硬塞候选）。
            """
            methods = self.search_method(user_text, platform=skill, top_k=top_method,
                                         owner_id=oid or None)
            name = _name(skill)
            lines = [f"【候选平台 {rank}】{name}（skill={skill}）",
                     "【该平台相关方法】（按相关度）"]
            for m in methods:
                info = m["info"]
                params = "，".join(f"{k}={v}" for k, v in info["params"].items()) or "无"
                dep = ""
                reqs = info.get("requires") or []
                if reqs:
                    dep = "；前置依赖：" + "、".join(
                        f"{r.get('param', '')}←{r.get('from', '')}"
                        for r in reqs if isinstance(r, dict))
                lines.append(f"- {m['method']}：{info['desc']}（需登录：{'是' if info['need_login'] else '否'}，参数：{params}{dep}）")
            return lines, {
                "skill": skill,
                "name": name,
                "score": round(float(score or 0), 4),
                "methods": [m["method"] for m in methods],
            }

        # 问题⑥⑦：把 top-3 候选平台各自的完整信息都列出（不再只给 top-1）
        lines: list[str] = []
        platforms: list[dict] = []
        for rank, p in enumerate(plats[:top_platform], start=1):
            block, info = _block(p["platform"], rank, p.get("score", 0))
            lines.extend(block)
            platforms.append(info)
            if rank < len(plats[:top_platform]):
                lines.append("")
        if changed:
            lines.append(f"【已从 {current_skill} 切换到 {top_skill}】")

        return {
            "top_skill": top_skill,
            "top_name": _name(top_skill),
            "note": "\n".join(lines),
            "current_skill": top_skill,
            "changed": changed,
            "platforms": platforms,
        }


# 全局单例
_index: RetrievalIndex | None = None
_INDEX_FP: str | None = None  # 构建索引时的磁盘才艺指纹（问题⑧热更新用）


def get_index() -> RetrievalIndex:
    """全局单例索引（首次调用构建；之后每次比对磁盘指纹，才艺变了自动重建）。

    问题⑧（热更新）：客户/运维新增、修改或删除才艺后无需重启进程——
    下次搜索自动发现磁盘变化、刷新注册表并重建索引。

    铁律（2026-08-16）：构建失败（如缺 torch / 模型加载失败）直接抛错暴露，
    不返回 None 降级——否则向量检索不可用会被静默掩盖。
    """
    global _index, _INDEX_FP
    from ..adapters import registry as reg

    fp = reg.skills_fingerprint()
    if _index is None or fp != _INDEX_FP:
        # 首次构建，或磁盘才艺变化（新增/修改/删除）→ 刷新注册表 + 重建索引
        reg.reload_skills()
        _index = RetrievalIndex()
        _index.build(reg.ADAPTERS)
        _INDEX_FP = fp
    return _index
