虾米办 · 手机端对外能力说明（做 skill 的人看这份就够）

原则：App 是纯执行器——只执行云端传来的指令/蓝图，不认识任何平台。
所有平台细节（接口地址、参数、签名方式、登录方式、支付产物）都由 skill 约定，
App 不内置。做 skill 的人照本文件的能力声明写，不需要看 App 源码。

────────────────────────────────────────
一、客户端对外能力与资料全清单（可拼进云端蓝图的原料）
────────────────────────────────────────

【A. 占位符】在蓝图 headers / body / url / sign_content 里写 {{xxx}}，App 自动替换

  1) 时间/签名（App 生成，保证最新）
     {{timestamp}}   当前毫秒时间戳
     {{nonce}}       32 位随机串
     {{sign}}        按 sign_type + sign_content 算出的签名
     {{appKey}}      headers 里的 appKey 值

  2) 凭据（按 active 邮箱从本机凭据库填）
     {{token}}          Bearer token
     {{refresh_token}}  refresh token（续期配置用）
     {{cookie}}         网页 cookies
     {{session_id}}     小程序会话
     {{api_key}}        开放平台 key
     {{deviceid}}       Android 真机唯一 ID（风控用）

  3) 个人资料（两张独立卡：中文卡 + 英文卡；客户分别填，英文自己填、不自动翻译）
     蓝图用 profile_card 选卡（"zh" 中文卡 / "en" 英文卡；缺省主卡=中文卡），App 用该卡字段填占位符；
     读不到为空，skill 可再问客户。只存本机、按邮箱隔离、云端不聚合
     中文卡（id=zh）：{{name}} 姓名  {{gender}} 性别  {{birthday}} 出生日期
       {{nationality}} 国籍  {{province}} 省份  {{city}} 城市  {{area}} 区县  {{address}} 地址  {{postal_code}} 邮编
       {{idnum}} 身份证号  {{idnum_photo}} 身份证照片  {{phone}} 手机号  {{email}} 邮箱  {{occupation}} 职业
       {{linkman}} / {{linkmanpho}} 紧急联系人  {{username}} / {{password}} 登录账号
     英文卡（id=en）：{{name}} Name  {{gender}} Gender  {{birthday}} Date of Birth
       {{nationality}} Nationality  {{province}} Province/State  {{city}} City  {{area}} Area
       {{address}} Address  {{postal_code}} Postal Code  {{passport_no}} Passport No.  {{passport_no_photo}} Passport Photo
       {{phone}} Phone  {{email}} Email …（字段同模板、值用英文；占位符名与中文卡一致，靠 profile_card 区分）
     （资料卡新增任何字段，都自动成为同名占位符）

【B. 签名算法】sign_type
  md5 / sha1 / sha256 / hmac_md5 / hmac_sha1 / hmac_sha256 / sha1_md5 / none
  配套字段：
    request.sign_content  待签名内容模板（占位符 {{appKey}}/{{timestamp}}/{{nonce}}/…）
    request.sign_key      HMAC 密钥（可选；缺省取 headers 的 appKey；非 HMAC 忽略）
  App 先把 sign_content 占位符替换为真实值，再按 sign_type 求哈希。
  同一算法的所有平台都不用改 App；时间戳由 App 在发出请求那一刻生成，保证最新。

【C. 凭据存储】蓝图的 credential / store 声明
  token / refresh_token / expires_at / cookie / session_id / api_key
  只存本机、按邮箱隔离、云端不聚合、互不串号

【D. 登录能力】contract 的 login 配置声明，App 只提供原语
  browser（内置浏览器真人登录）：clear_cookies / navigate / export_cookies / export_token / check_ready
  sms_verify（API 短信登录）：验证码图推送显示 → 用户输入回传

【E. 支付】App 不参与收款，App 内零收款
  skill 返回 pay_url / scheme → open_external（系统浏览器/系统拉起）

【F. 文件上传】body_type=multipart：body 里声明
  { "fields": {普通字段…}, "files": [ { "field","path","filename","content_type" } ] }
  文件从手机本地读（/绝对路径、file://、content://，如 /sdcard/Download/xxx.jpg）
  资料卡证件照：{{idnum_photo}} / {{passport_no_photo}} 存 App 沙盒 file:// 路径（资料卡「📷」拍照/相册选），
  上传时直接用该值作 path（文件从手机直连发平台，不过云端）

【G. 凭据/资料加密】token / cookie / session / api_key / 个人资料 用 Android Keystore + AES/GCM
  加密存储（密钥不出硬件；换机后密钥不随备份走 → 需重新登录）

【H. 网络诊断日志】直连失败 / 非 2xx 时写本机 logs/exec.log
  （脱敏：skill / method / status / url / 错误摘要，不记完整 body / 凭据），供云端排查 skill 问题

【I. 响应裁剪】云端在蓝图 response 里指定只回传部分数据，避免全量回传过重：
  response: { "pick": ["data.access_token", "data.orders"], "max_size": 20000 }
  - pick：只回传这些字段（点分路径，支持嵌套）
  - max_size：body 截断到 N 字符
  App 回传裁剪后的 body（附 picked / truncated 标记）；不声明则全量回传

────────────────────────────────────────
二、skill 执行通道（skill_request 蓝图）
────────────────────────────────────────
云端下发「请求蓝图」→ App 手机真实 IP 直连平台 → 回 skill_result 原始响应。
蓝图字段：
  skill        平台标识（App 只当 key 用）
  request      { method, url, headers, body, body_type, sign_type, sign_content, sign_key, insecure_tls }
                 body_type: json | form | multipart（multipart 上传本地文件，见 A.4）
                 insecure_tls: 缺省 false（校验证书）；仅自签名老站才 true
                 url / headers / body 均支持占位符（{{token}}/{{cookie}}/{{timestamp}}/{{sign}}…）
  credential   { kind: none|bearer|cookie|session|api_key, target }
                 ⚠️ 声明性字段，App 不读取（仅作云端了解凭据类型用）。
                 实际生效机制：kind=cookie → App 自动补 Cookie 头；
                 kind=bearer/session/api_key → 在 headers/body/url 写 {{token}}/{{session_id}}/{{api_key}} 占位符
  store        登录成功后的回写字段（App 写入本地凭据库）
  auto_refresh + refresh   token 快过期时的续期配置（App 按配置执行）
  response     { pick:[字段...], max_size:N }   可选：只回传部分字段 / 截断（见 A.9）

────────────────────────────────────────
三、App 不做什么（红线）
────────────────────────────────────────
- 不编排（选方法 / 前置条件 / 登录触发，都是云端的事）
- 不判断平台（不知道 glyy / tuniu / 美团 是什么）
- 不执行 skill 代码（红线 A：只执行 JSON 蓝图）
- 不持有登录态（凭据只存本机，云端不聚合）

────────────────────────────────────────
四、实现文件
────────────────────────────────────────
MainActivity.java    WebView 宿主 + AndroidBridge + 登录/支付原语
SkillExecutor.java   蓝图执行引擎（直连 / 凭据 / 签名 / 资料 / 续期）
CredentialStore.java 凭据库 + 个人资料（按邮箱隔离）
