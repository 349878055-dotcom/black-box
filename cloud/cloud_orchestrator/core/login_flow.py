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


async def run_login(skill: str, login_cfg: dict, device_id: str,
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
                _sms_verify(skill, cfg, device_id, ask, phone, owner_id=owner_id),
                timeout=LOGIN_TOTAL_TIMEOUT)
        if method == "browser":
            return await asyncio.wait_for(
                _browser(skill, cfg, device_id, ask),
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


async def _sms_verify(skill: str, cfg: dict, device_id: str, ask, phone: str = "",
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
            cap = await skill_run(skill, cap_step["method"], cap_params, device_id,
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
            sms = await skill_run(skill, sms_step["method"], sms_params, device_id,
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
        sms = await skill_run(skill, sms_step["method"], sms_params, device_id,
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
        login = await skill_run(skill, login_step["method"], login_params, device_id,
                                owner_id=owner_id)
        login_data = login.get("data") or {}
        if not login.get("ok") or not login_data.get("ok"):
            err = str(login_data.get("error") or login.get("error") or "登录失败")
            logger.warning("登录失败 skill=%s: %s", skill, err[:200])
            await ask(f"登录失败：{err}")
            return False
    logger.info("登录成功 skill=%s（token 已存手机凭据库）", skill)
    return True


async def _browser(skill: str, cfg: dict, device_id: str, ask) -> bool:
    """内置浏览器真人登录：可选清 cookie / 预检 → navigate → 真人操作 → 导出登录态。"""
    from ..channel.bridge import bridge
    interact = cfg.get("interact") or {}
    export = cfg.get("export") or {}
    url = cfg.get("url", "")
    domain = (export.get("domain") or url or "").strip()

    # 可选：先清残留 cookie（防登录页重定向回首页）
    if device_id and cfg.get("clear_cookies"):
        try:
            await bridge.send_cmd(device_id, "clear_cookies", {"domain": domain})
        except Exception as e:
            logger.warning("%s clear_cookies 失败: %s", skill, e)

    # 可选：预检是否已登录（如 export_cookies）
    precheck = cfg.get("precheck") or ""
    if device_id and precheck:
        try:
            pre = await bridge.send_cmd(device_id, precheck, {"domain": domain})
            logger.info("%s precheck %s: %s", skill, precheck, str(pre)[:200])
        except Exception as e:
            logger.warning("%s precheck 失败: %s", skill, e)

    if device_id and url:
        try:
            await bridge.send_cmd(device_id, "navigate", {"url": url})
        except Exception as e:
            logger.warning("%s navigate 打开登录页失败: %s", skill, e)
    await ask(interact.get("guide",
              "已在内置浏览器打开登录页，请完成登录后回复「已登录」。"))
    if device_id and export.get("cmd"):
        try:
            # 透传 export 配置（domain/skill 等），缺 skill 时用当前平台 id，保证凭据写入正确卡片
            exp_params = {k: v for k, v in export.items() if k != "cmd"}
            if not exp_params.get("skill"):
                exp_params["skill"] = skill
            res = await bridge.send_cmd(device_id, export["cmd"], exp_params)
            logger.info("%s export: %s", skill, str(res)[:200])
            # 校验导出是否成功：手机端返回 {ok:true,...} 才视为登录态已保存；
            # 导出失败不能假装登录成功（否则 agent 重试业务仍未登录，用户只看到「需要登录」却不知导出失败）
            if not (isinstance(res, dict) and res.get("ok")):
                err = str(res.get("error") or "") if isinstance(res, dict) else ""
                await ask(f"登录态保存失败（{err or '手机未返回成功'}），请确认已登录后重试一次。")
                return False
        except Exception as e:
            logger.warning("%s export 失败: %s", skill, e)
            await ask("登录态保存失败，请稍后重试。")
            return False
    return True
