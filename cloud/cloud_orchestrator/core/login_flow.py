"""通用登录编排器（云端）——登录方式由 skill 在 contract.json/register.py 的 `login` 配置声明。

设计目标（2026-08-11 用户铁令：登录独立成模块，删除手机端 LoginCoordinator，登录全在云端）：
- 每个平台 API 的登录方式不同，统一用「skill 声明 login 配置 + 云端通用执行」表达；
- agent 不再为每个 skill 硬编码 _login_xxx，只调 run_login(skill, login_cfg, ...)；
- 登录态只存手机本地凭据库（蓝图带 store/credential 字段，手机 SkillExecutor 自动存），云端不持有。

支持登录方式（method）：
  sms_verify — 短信验证码纯 API：手机号 → 图形码 → 短信码 → login（走手机通道，registry.run）
  browser   — 内置浏览器真人登录：navigate 打开 → 真人操作 → 导出 cookie/token（走 bridge cmd）

交互：图形码图经 ask(question, image) 推 App 聊天显示；手机号/短信码由 ask 收集。
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("xiami.login_flow")

REFRESH_CAPTCHA = "🔄 看不清，换一张"
MAX_CAPTCHA_TRIES = 3
# 登录流程整体总超时（问题15）：即使单步 ask 有 600s 超时，整个登录流程
# （sms_verify 多轮图形码 / browser + export）也必须在总超时内完成，
# 覆盖「用户一直不回复又卡在 export / 循环换图」等极端情况。
LOGIN_TOTAL_TIMEOUT = 900


async def run_login(skill: str, login_cfg: dict, email: str,
                    ask, phone: str = "", owner_id: str = "") -> bool:
    """按 skill 声明的 login 配置执行登录。ask = async (question, image=None) -> str。

    整体包一层 asyncio.wait_for(LOGIN_TOTAL_TIMEOUT)：超时后提示并返回 False，
    让 agent 走「登录未完成」分支，而不是无限期挂着。
    """
    cfg = login_cfg or {}
    method = cfg.get("method", "")
    try:
        if method == "sms_verify":
            return await asyncio.wait_for(
                _sms_verify(skill, cfg, email, ask, phone, owner_id=owner_id),
                timeout=LOGIN_TOTAL_TIMEOUT)
        if method == "browser":
            return await asyncio.wait_for(
                _browser(skill, cfg, email, ask, owner_id=owner_id),
                timeout=LOGIN_TOTAL_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("登录流程总超时 skill=%s method=%s（>%ss）",
                       skill, method, LOGIN_TOTAL_TIMEOUT)
        try:
            await ask(f"登录超时（超过 {LOGIN_TOTAL_TIMEOUT} 秒），请稍后重试。")
        except Exception:
            pass
        return False
    logger.warning("不支持的登录方式 skill=%s method=%s", skill, method)
    return False


def _fill(tpl, vars: dict) -> str:
    """{phone}/{captcha_code}/{sms_code} 占位符替换。"""
    for k, v in vars.items():
        tpl = tpl.replace("{" + k + "}", str(v or ""))
    return tpl


def _pick(obj, path: str):
    """点分路径取值，如 data.imageBase64；找不到返回空串。"""
    cur = obj
    for part in (path or "").split("."):
        if part and isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return ""
    return str(cur or "")


def _is_refresh_captcha(text: str) -> bool:
    """点了「换一张」或短回复里写看不清 / 换一张。"""
    t = (text or "").strip()
    if not t:
        return False
    if t == REFRESH_CAPTCHA:
        return True
    compact = t.replace("🔄", "").replace(" ", "").replace("，", ",")
    if compact in ("看不清,换一张", "看不清换一张"):
        return True
    return len(t) <= 16 and any(x in t for x in ("看不清", "换一张", "换张图"))


async def _sms_verify(skill: str, cfg: dict, email: str, ask, phone: str = "",
                      owner_id: str = "") -> bool:
    """短信验证码登录：手机号 → 图形码(图) → 短信码 → login，全程走手机通道。"""
    from ..adapters.registry import run as skill_run
    steps = cfg.get("steps") or {}
    interact = cfg.get("interact") or {}
    display = cfg.get("display", skill)

    # 1) 手机号
    if not phone:
        phone = (await ask(interact.get("phone", f"请输入手机号，完成{display}登录"))).strip()
    if not phone:
        logger.warning("登录取消：未提供手机号 skill=%s", skill)
        return False
    vars_map = {"phone": phone}

    # 2) 图形验证码（可选）：最多 3 次。点「换一张」或 send_sms 失败 → 自动换图
    cap_step = steps.get("captcha")
    sms_step = steps.get("send_sms")
    gcode = ""
    sms_sent = False
    if cap_step:
        cap_prompt = interact.get("captcha_image", "请输入图形验证码（看上方图片里的字符）")
        last_err = ""
        for attempt in range(1, MAX_CAPTCHA_TRIES + 1):
            cap_params = {k: _fill(str(v), vars_map)
                          for k, v in (cap_step.get("params") or {}).items()}
            cap = await skill_run(skill, cap_step["method"], cap_params, email,
                                  owner_id=owner_id)
            cap_data = cap.get("data") or {}
            if not cap.get("ok") or not cap_data.get("ok"):
                err = str(cap_data.get("error") or cap.get("error") or "获取图形验证码失败")
                logger.warning("登录图形验证码失败 skill=%s: %s", skill, err[:200])
                await ask(f"获取图形验证码失败：{err}（可稍后重试或回复「放弃」）")
                return False
            img = str(_pick(cap_data, cap_step.get("image_field", "image_base64")) or "")
            prompt = cap_prompt if attempt == 1 else f"（第{attempt}次）{cap_prompt}"
            gcode = (await ask(prompt, image=img or None,
                               options=[REFRESH_CAPTCHA])).strip()
            if not gcode:
                return False
            if _is_refresh_captcha(gcode):
                logger.info("登录换图形码 skill=%s attempt=%s", skill, attempt)
                last_err = "看不清，已换图"
                continue
            if not sms_step:
                break
            v2 = dict(vars_map)
            v2["captcha_code"] = gcode
            sms_params = {k: _fill(str(v), v2)
                          for k, v in (sms_step.get("params") or {}).items()}
            sms = await skill_run(skill, sms_step["method"], sms_params, email,
                                  owner_id=owner_id)
            sms_data = sms.get("data") or {}
            if sms.get("ok") and sms_data.get("ok"):
                sms_sent = True
                break
            last_err = str(sms_data.get("error") or sms.get("error") or "发送短信失败")
            logger.warning("登录发送短信失败 skill=%s attempt=%s: %s",
                           skill, attempt, last_err[:200])
            if attempt < MAX_CAPTCHA_TRIES:
                continue
            await ask(f"发送短信失败：{last_err}（图形码已试满 {MAX_CAPTCHA_TRIES} 次）")
            return False
        else:
            await ask(f"图形验证码已换满 {MAX_CAPTCHA_TRIES} 次仍未通过（{last_err or '未输入有效验证码'}）")
            return False

    # 3) 无图形码时单独发短信
    if sms_step and not sms_sent:
        v2 = dict(vars_map)
        v2["captcha_code"] = gcode
        sms_params = {k: _fill(str(v), v2) for k, v in (sms_step.get("params") or {}).items()}
        sms = await skill_run(skill, sms_step["method"], sms_params, email,
                              owner_id=owner_id)
        sms_data = sms.get("data") or {}
        if not sms.get("ok") or not sms_data.get("ok"):
            err = str(sms_data.get("error") or sms.get("error") or "发送短信失败")
            logger.warning("登录发送短信失败 skill=%s: %s", skill, err[:200])
            await ask(f"发送短信失败：{err}")
            return False

    # 4) 短信验证码 → 登录（token 由手机 SkillExecutor 按蓝图 store 自动存凭据库）
    login_step = steps.get("login")
    if login_step:
        code = (await ask(interact.get("sms_code", "短信已发送，请输入收到的验证码"))).strip()
        if not code:
            return False
        v3 = dict(vars_map)
        v3["sms_code"] = code
        login_params = {k: _fill(str(v), v3) for k, v in (login_step.get("params") or {}).items()}
        login = await skill_run(skill, login_step["method"], login_params, email,
                                owner_id=owner_id)
        login_data = login.get("data") or {}
        if not login.get("ok") or not login_data.get("ok"):
            err = str(login_data.get("error") or login.get("error") or "登录失败")
            logger.warning("登录失败 skill=%s: %s", skill, err[:200])
            await ask(f"登录失败：{err}")
            return False
    logger.info("登录成功 skill=%s（token 已存手机凭据库）", skill)
    return True


async def _browser(skill: str, cfg: dict, email: str, ask, owner_id: str = "") -> bool:
    """内置浏览器真人登录：清 cookie / 预检 → navigate 打开登录页 → 真人登录 →
    导出登录态 →（可选）verify 校验真登录；支持「没登上」重试循环。

    设计（供应商自治）：打开登录页/存 cookie 是手机通用原子能力，登录编排是云端通用
    解释器；skill 只在本平台 login.json 里声明 url / export / verify / max_attempts /
    interact，云端不为任何一家写死登录逻辑。
    """
    from ..channel.bridge import bridge
    interact = cfg.get("interact") or {}
    export = cfg.get("export") or {}
    url = cfg.get("url", "")
    domain = (export.get("domain") or url or "").strip()
    max_tries = int(cfg.get("max_attempts") or 3)
    verify_method = str(cfg.get("verify") or "").strip()
    guide = interact.get("guide",
                         "已在内置浏览器打开登录页，请完成登录后回复「已登录」。")
    fail_hint = interact.get(
        "fail_hint",
        "若登录失败，可直接在浏览器刷新重来，或回复「没登上」，我重新打开登录页。")

    # 可选：先清残留 cookie（防登录页重定向回首页）
    if email and cfg.get("clear_cookies"):
        try:
            await bridge.send_cmd(email, "clear_cookies", {"domain": domain})
        except Exception as e:
            logger.warning("%s clear_cookies 失败: %s", skill, e)

    # 可选：预检是否已登录（如 export_cookies）
    precheck = cfg.get("precheck") or ""
    if email and precheck:
        try:
            pre = await bridge.send_cmd(email, precheck, {"domain": domain})
            logger.info("%s precheck %s: %s", skill, precheck, str(pre)[:200])
        except Exception as e:
            logger.warning("%s precheck 失败: %s", skill, e)

    for attempt in range(1, max_tries + 1):
        # navigate 打开登录页（失败要明确提示，不假装已打开）
        if email and url:
            # 诊断日志：记录 navigate 发出与返回，用于定位「浏览器不弹」的根因
            logger.info("%s [诊断] 准备 navigate 打开登录页 url=%s（第 %d/%d 次）",
                        skill, url, attempt, max_tries)
            nav_res = {}
            try:
                nav_res = await bridge.send_cmd(email, "navigate", {"url": url})
            except Exception as e:
                logger.warning("%s navigate 异常: %s", skill, e)
            logger.info("%s [诊断] navigate 返回: %s", skill, str(nav_res)[:300])
            if isinstance(nav_res, dict) and not nav_res.get("ok"):
                err = str(nav_res.get("error") or "") if isinstance(nav_res, dict) else ""
                await ask(f"内置浏览器打开登录页失败（{err or '未知原因'}），请稍后重试或检查网络。")
                return False

        # ask 引导（第 1 次用标准话术；重试时提示次数）
        prompt = guide if attempt == 1 else f"（第{attempt}次）请再次完成登录：\n{guide}"
        prompt = f"{prompt}\n{fail_hint}"
        reply = (await ask(prompt)).strip()
        # 客户明确表示没登上 → 重新打开登录页再试
        if reply and any(x in reply for x in ("没登上", "没登录", "登录失败", "登不上", "不行", "重来", "再来")):
            logger.info("%s 客户反馈未登录成功（第 %d 次），重新打开登录页", skill, attempt)
            continue

        # 导出登录态（cookie/token 存手机凭据库）
        if email and export.get("cmd"):
            exp_params = {k: v for k, v in export.items() if k != "cmd"}
            if not exp_params.get("skill"):
                exp_params["skill"] = skill
            res = {}
            try:
                res = await bridge.send_cmd(email, export["cmd"], exp_params)
            except Exception as e:
                logger.warning("%s export 失败: %s", skill, e)
            logger.info("%s export: %s", skill, str(res)[:200])
            # 导出失败 → 可能是没真登录，回循环重试（不假装成功）
            if not (isinstance(res, dict) and res.get("ok")):
                err = str(res.get("error") or "") if isinstance(res, dict) else ""
                await ask(f"登录态保存失败（{err or '手机未返回成功'}），请确认已登录后重试一次。")
                continue

        # 可选：verify 真登录校验（skill 在 login.json 声明校验方法，防假登录）
        if verify_method:
            if not await _verify_login(skill, verify_method, email, owner_id=owner_id):
                await ask("还没检测到登录成功，请确认已在浏览器完成登录后重试（或回复「没登上」）。")
                continue

        logger.info("登录成功 skill=%s（登录态已存手机凭据库）", skill)
        return True

    await ask(f"登录未完成（已尝试 {max_tries} 次），请稍后重试或检查网络。")
    return False


async def _verify_login(skill: str, method: str, email: str, owner_id: str = "") -> bool:
    """调 skill 声明的「校验是否已登录」方法，确认真登录（防假登录）。

    判定规则：返回 need_login / 未登录类错误 → 未登录；否则视为已登录
    （能调通需要登录态的接口且未报未登录，即 cookie/token 有效）。
    """
    from ..adapters.registry import run as skill_run
    try:
        res = await skill_run(skill, method, {}, email=email, owner_id=owner_id)
    except Exception as e:
        logger.warning("登录校验异常 skill=%s method=%s: %s", skill, method, e)
        return False
    if not isinstance(res, dict):
        return False
    if res.get("need_login"):
        return False
    err = str(res.get("error") or "")
    if res.get("ok") is False and any(k in err for k in ("未登录", "登录", "401", "token")):
        return False
    return True
