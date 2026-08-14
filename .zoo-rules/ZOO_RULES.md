# Zoo 规则（唯一一套 · 全局 + Code 模式共用）

> 本文件是唯一权威规则；根目录 `~/.roo/rules/00-zoo-rules.md` 与本文件保持同一套。
> 严禁出现两套不同规则。

## 1. DeepSeek 禁图铁律（优先级最高）

> Zoo 主模型是 DeepSeek 纯文本，不支持图片输入。本规则优先级最高。

- **禁止** `adb screencap` / `adb exec-out screencap` / `screencap -p`，以及任何「截手机屏再喂模型」的流程
- **禁止** `read_file` 打开 `phone_*.png`、`*_screen.png`、`mac_screen.png` 等截图让模型分析
- **禁止** 聊天里粘贴 `data:image/...`、PNG/JPG/WebP 给 DeepSeek
- 网页自动化交给 `browse_web`（千问视觉），Zoo 不截图

**收到截图必须立即明确回应（禁止卡死 / 长时无响应）**：
- 用户一旦在聊天里贴图/截图（`data:image/...`、PNG/JPG/WebP，或说"看这张图/截图"），
  **必须立刻回复下面这段，不要等待、不要重试、不要假装能看图**：
  > 当前 DeepSeek 是纯文本模型，不支持图片输入，这张图我看不了。
  > ① 请用文字描述图里的内容；② 看手机/网页画面走 uiautomator dump（XML 文本）或 browse_web（千问视觉）；③ 图片可存到 /tmp 由你本地查看。
- 说完即结束本轮；若用户仍坚持发图，重复一句"DeepSeek 不支持图片"即可，**绝不挂起等待**。

看手机界面唯一方式（uiautomator dump + XML 文本）：
```bash
ADB=/home/jintao/Android/platform-tools/adb; DEV=D5F7N18C07007849
$ADB -s $DEV shell uiautomator dump /sdcard/ui.xml
$ADB -s $DEV pull /sdcard/ui.xml /tmp/ui.xml
```
解析 XML 文本 + bounds，用 `input tap` / ADBKeyboard 操作；图片只存 `/tmp/` 给用户看路径。

**停手铁律**：同一障碍最多试 2 次 → 停手说明；收到 400 /「提供商无法按此方式处理」→ 立刻停止当前策略；用户说「停/取消」→ 立即结束，不再开新命令。

## 2. glyy 禁云端直连铁律

> 用户铁令：不用云端直连，全走手机通道。

- **禁止** 云端 `requests`/`curl` 直连 glyy（`www.ih.njglyy.com:9532` 所有接口），禁止为测接口在云端跑直连脚本
- **必须** 云端组装蓝图 → `bridge.send_skill_request` 下发手机 → 手机真实 IP 直连 → 回传 `skill_result` → 云端解析
- 参考 `glyy_api.py` executor 分支（`_blueprint/_exec/_sms_blueprint/get_graphical_captcha/send_sms/login`）；手机引擎 `SkillExecutor.java`
- 适配器注入 executor：`GlyyAPI(executor=...)`；无 executor 仅限本地单机测试
- **自检**：写访问 glyy 的代码/命令前：是不是云端直连？是就停，改下发手机。

## 3. 本地仅开发，禁止当云端代理

> 用户铁令：本地电脑只用来写程序/改代码，手机直连腾讯云。

- **禁止** 把本地电脑当成云端代理：手机 App 连本地 IP（如 `192.168.1.175:19000`）做调试/测试
- **禁止** 为「测试」在本机常驻跑云端当手机通道
- **必须** 手机 App 直连腾讯云 `http://140.143.144.28`（生产云端）
- **必须** 本地改代码 → 部署到腾讯云 → 手机连腾讯云再测试
- 本地 Python/服务仅用于写、改、验证代码逻辑，不承担运行时云端职责
- **自检**：准备让手机连本地地址/本机跑云端时：停。手机只连腾讯云。

## 4. 模型分工与手机信息

- Zoo（DeepSeek）：只处理文字，禁任何图片输入
- 虾米 `browse_web`（千问 VL）：才可看网页截图；不要在 Zoo 手工截图喂主模型
- 手机设备：`D5F7N18C07007849`（华为 CLT-AL00 / P20 Pro）；ADB：`/home/jintao/Android/platform-tools/adb`
- 回复默认简体中文，简洁直接

## 5. 数据真实性

- **禁止** 假数据 / 模拟数据 / 编造结果
- 一切数据必须来自真实接口返回（skill_run / web_search 等真实结果），拿不到就如实说明，绝不伪造
- 演示/测试如需占位数据，须明确标注为 mock / 示例，不得冒充真实结果

## 6. 平台登录一律走内置浏览器，禁止再扯「微信授权」（用户铁令）

> 用户铁令（2026-08-10）：**禁止再提「微信授权」这条路**。App 内置浏览器代替不了微信授权，这条路已确认不走。

- **禁止** 建议 / 讨论 / 反复提及用「微信授权」（微信小程序 openid / wx.login code / 微信扫码授权）作为平台登录方案
- **禁止** 把「无法微信授权」当成登录障碍反复解释，用户已明确不接受这条路线
- **必须** 平台登录统一走：App 内置浏览器打开登录页（微信 UA + 小程序 Referer）→ 用户自己输手机号+短信验证码登录 → 自动导出登录态存手机凭据库
- **自检**：提到某 skill 登录时，若脑子里冒出「微信授权」→ 停，改说「内置浏览器登录」
