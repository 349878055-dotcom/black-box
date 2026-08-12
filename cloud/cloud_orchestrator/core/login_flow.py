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

import logging

logger = logging.getLogger("xiami.login_flow")


async def run_login(skill: str, login_cfg: dict, device_id: str,
                    ask, phone: str = "") -> bool:
    """按 skill 声明的 login 配置执行登录。ask = async (question, image=None) -> str。"""
    cfg = login_cfg or {}
    method = cfg.get("method", "")
    if method == "sms_verify":
        return await _sms_verify(skill, cfg, device_id, ask, phone)
    if method == "browser":
        return await _browser(skill, cfg, device_id, ask)
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


async def _sms_verify(skill: str, cfg: dict, device_id: str, ask, phone: str = "") -> bool:
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

    # 2) 图形验证码（可选步骤）
    cap_step = steps.get("captcha")
    gcode = ""
    if cap_step:
        cap_params = {k: _fill(str(v), vars_map)
                      for k, v in (cap_step.get("params") or {}).items()}
        cap = await skill_run(skill, cap_step["method"], cap_params, device_id)
        cap_data = cap.get("data") or {}
        if not cap.get("ok") or not cap_data.get("ok"):
            err = str(cap_data.get("error") or cap.get("error") or "获取图形验证码失败")
            logger.warning("登录图形验证码失败 skill=%s: %s", skill, err[:200])
            await ask(f"获取图形验证码失败：{err}（可稍后重试或回复「放弃」）")
            return False
        img = str(_pick(cap_data, cap_step.get("image_field", "image_base64")) or "")
        gcode = (await ask(interact.get("captcha_image", "请输入图形验证码（看上方图片里的字符）"),
                           image=img or None)).strip()
        if not gcode:
            return False

    # 3) 发送短信验证码（可选步骤）
    sms_step = steps.get("send_sms")
    if sms_step:
        v2 = dict(vars_map)
        v2["captcha_code"] = gcode
        sms_params = {k: _fill(str(v), v2) for k, v in (sms_step.get("params") or {}).items()}
        sms = await skill_run(skill, sms_step["method"], sms_params, device_id)
        sms_data = sms.get("data") or {}
        if not sms.get("ok") or not sms_data.get("ok"):
            err = str(sms_data.get("error") or sms.get("error") or "发送短信失败")
            logger.warning("登录发送短信失败 skill=%s: %s", skill, err[:200])
            await ask(f"发送短信失败：{err}（可能图形码输错，可回复「重试」）")
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
        login = await skill_run(skill, login_step["method"], login_params, device_id)
        login_data = login.get("data") or {}
        if not login.get("ok") or not login_data.get("ok"):
            err = str(login_data.get("error") or login.get("error") or "登录失败")
            logger.warning("登录失败 skill=%s: %s", skill, err[:200])
            await ask(f"登录失败：{err}")
            return False
    logger.info("登录成功 skill=%s（token 已存手机凭据库）", skill)
    return True


async def _browser(skill: str, cfg: dict, device_id: str, ask) -> bool:
    """内置浏览器真人登录：navigate 打开 → 真人操作 → 导出登录态存手机。"""
    from ..channel.bridge import bridge
    interact = cfg.get("interact") or {}
    export = cfg.get("export") or {}
    url = cfg.get("url", "")
    if device_id and url:
        try:
            await bridge.send_cmd(device_id, "navigate", {"url": url})
        except Exception as e:
            logger.warning("%s navigate 打开登录页失败: %s", skill, e)
    await ask(interact.get("guide",
              "已在内置浏览器打开登录页，请完成登录后回复「已登录」。"))
    if device_id and export.get("cmd"):
        try:
            res = await bridge.send_cmd(device_id, export["cmd"],
                                        {"domain": export.get("domain", "")})
            logger.info("%s export: %s", skill, str(res)[:200])
        except Exception as e:
            logger.warning("%s export 失败: %s", skill, e)
    return True
