# 虾米办 · 手机 App 功能实现总结

> 定位：**云端大脑 + 手机执行**。App 是**纯执行器**——只执行云端传来的指令/蓝图，不认识任何平台；所有平台细节由 skill 约定，云端按约定编排。

---

## 一、核心架构分层

| 层 | 职责 | 说明 |
|---|---|---|
| **App（手机）** | 纯执行器 | 执行 skill 请求蓝图、登录原语、支付打开、凭据/资料读写、签名/上传/裁剪；**不编排、不判断平台、不执行 skill 代码** |
| **skill** | 约定一切平台细节 | 接口地址/参数、签名方式（sign_type+sign_content）、登录方式、支付产物、资料字段；写在 contract/register/api 里 |
| **云端** | 按 skill 约定编排 | 选方法、补前置参数、触发登录、交付支付产物；登录态不持有（只存手机） |

**红线**：App 不编排 / 不判断平台 / 不执行代码（只执行 JSON 蓝图）/ 不持有登录态（凭据只存本机、云端不聚合）。

---

## 二、已实现的核心功能

### 1. skill 执行通道（skill_request）
- 云端下发「请求蓝图」→ App 手机真实 IP 直连平台 → 回 skill_result 原始响应
- 蓝图支持：method / url / headers / body / body_type（json / form / **multipart**）/ sign_type / sign_content / sign_key / credential / store / auto_refresh / refresh / response / profile_card
- 占位符：`{{timestamp}} {{nonce}} {{sign}} {{appKey}}`、`{{token}} {{refresh_token}} {{cookie}} {{session_id}} {{api_key}} {{deviceid}}`、个人资料 `{{name}} {{idnum}} {{passport_no}} …`
- 连接失败自动重试、自签名证书兼容、凭据自动补全

### 2. 通用签名算法库（不绑平台）
`md5` / `sha1` / `sha256` / `hmac_md5` / `hmac_sha1` / `hmac_sha256` / `sha1_md5` / `none`
- 签名内容由 skill 在蓝图 `sign_content` 里提供模板（含占位符），App 只按 `sign_type` 求哈希
- **同一算法的所有平台都不用改 App**；时间戳由 App 发出请求那一刻生成

### 3. 凭据库（按邮箱隔离 + 加密）
- token / refresh_token / expires_at / cookie / session_id / api_key，按 active 邮箱隔离、互不串号
- **Android Keystore + AES/GCM 加密存储**，密钥不出硬件；换机后需重新登录
- 未登录时读写为空，绝不落到设备级公共 key

### 4. 个人资料卡（两张独立卡）
- **中文卡（zh）+ 英文卡（en）**，客户分别填，英文自己填不自动翻译
- 字段：姓名/性别/生日/国籍/省份/城市/区县/地址/邮编、身份证号（独立）、护照号（独立）、手机/邮箱/职业/紧急联系人
- **证件照**：资料卡「📷」拍照/相册选 → 复制到 App 沙盒（file:// 持久）→ skill 按 `{{idnum_photo}}`/`{{passport_no_photo}}` 上传
- skill 用蓝图 `profile_card` 选卡（zh/en），读不到为空、skill 再问客户

### 5. 文件上传（multipart，直连发平台不过云端）
- 蓝图 `body_type=multipart`，`files` 声明本地文件（/绝对路径、file://、content://）
- 证件照、附件从手机**直连发给平台**，文件内容**不经过云端**

### 6. 响应裁剪（避免全量回传过重）
- 蓝图 `response: { pick:[字段...], max_size:N }`，App 只回传指定字段 / 截断
- 附 `picked` / `truncated` 标记；不声明则全量回传

### 7. 登录能力（skill 在 contract 的 login 配置声明，App 只提供原语）
- **browser**（内置浏览器真人登录）：clear_cookies / navigate / export_cookies / export_token / check_ready
- **sms_verify**（API 短信登录）：验证码图推聊天室 → 用户看图输入回传
- 验证码图**只在手机显示、本地不存、云端不进、LLM 上下文无它**（多重隔离）

### 8. 支付（App 内零收款）
- skill 返回 pay_url / scheme → App 用系统浏览器/系统拉起（open_external），不进内置浏览器遥控

### 9. 多账号隔离
- 一切数据（凭据/资料/会话）挂 active email 维度，未登录读写为空；旧设备级 key 一次性清理不迁移

### 10. 网络诊断日志
- 直连失败 / 非 2xx 写本机 `logs/exec.log`（脱敏：skill/method/status/url/错误摘要），供云端排查

---

## 三、本轮实现/清理的具体事项

### 新增功能
- **多账号隔离**：凭据按 email 维度 + 一次性清理旧设备级 key
- **签名去平台化**：`glyy_sha1_md5` → `sha1_md5`，App 只留通用算法库
- **签名内容模板化**：sign_type + sign_content（skill 声明拼接，App 只哈希）
- **个人资料卡**：单份资料 → 中文卡 + 英文卡，身份证/护照独立、邮编、证件照上传
- **文件上传**：multipart/form-data，本地文件直连发平台
- **响应裁剪**：云端指定返还什么数据
- **凭据加密**：Android Keystore + AES/GCM
- **网络日志**：失败留痕
- **证件照入口**：资料卡拍照/相册选 → 沙盒 → skill 上传；补 CAMERA 权限
- **App 对外能力文档**：app/src/core/README.txt 重写为「客户端对外能力与资料全清单」

### 清理的死代码
- 浏览器遥控指令集（read/click/fill/scroll/select/slider 等 18 个指令 + 对应 JS 常量）——登录只需 5 个原语，其余无生产调用
- 支付 navigate 内置浏览器 → 改系统浏览器（open_external）
- ui.html 旧本地登录引擎残留（loginInput/__askLogin/loginWaiting）
- MainActivity 无调用 bridge（saveCredential/hideKeyboard）
- 平台名硬编码注释（glyy/tuniu/美团 等 32 处）

### 修复的关键细节
- **ws.py 透传 response / profile_card**（响应裁剪、资料卡选卡之前不生效）
- 支付默认 navigate 内置浏览器 → 系统浏览器
- 主请求/续期签名由 skill 蓝图下发（App 不再内置平台续期接口）

---

## 四、对外声明（做 skill 的人看这些）

| 文档 | 内容 |
|---|---|
| [`app/src/core/README.txt`](../app/src/core/README.txt) | App 对外能力与资料全清单（占位符/签名/凭据/登录/支付/上传/加密/日志/裁剪） |
| 工作台4.0 落盘接口文件 `cloud/knowledge/助理包/落盘/README.md` | skill 制作接口（蓝图协议/占位符/签名/资料卡/上传/裁剪/加密/日志） |

---

## 五、验证结果

- 三端（App / skill / 云端）代码、文档、透传**三处一致**
- bridge 方法全部对上（ui.html 调用 ↔ MainActivity 实现）
- Java 大括号平衡、Python 语法通过
- App 内平台名硬编码清零（只剩协议签名名 sha1_md5 + 授权中心展示映射）
- minSdk 24 ≥ 23，满足 Keystore 加密要求

---

## 六、可选后续（未做）

- 超时/重试蓝图可配（当前硬编码 15s/40s/3 次）
- 长时间任务通知（等验证码/支付提醒）
- 崩溃上报、图片压缩上传、App 版本自检
