# 同事接手指南（Windows 开发环境）

云端服务已部署在服务器上。你在 Windows 上拉代码、搭本地环境、编译 App 装到手机即可。

**仓库地址**：`git@github.com:349878055-dotcom/black-box.git`（GitHub，私有仓库）

---

## 已经克隆过仓库？只要更新，不要重新 clone

```powershell
cd D:\projects\personal-assistant
git config --global core.autocrlf input
git pull origin master
.venv\Scripts\activate
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

依赖里新增了 `langgraph-checkpoint-sqlite`，**必须再装一次 pip**，否则对话状态落盘会失败。

本地改过文件、`git pull` 冲突时，先把改动 stash 或提交，再 pull。不要用 `git reset --hard` 除非你确定可以丢掉本地修改。

---

## 交给你自己的 AI 怎么说（复制下面整段）

同事用 Cursor / 其它 AI 改代码时，把下面这段贴进对话（或放进项目规则），避免 AI 按旧架构乱改：

```text
请先读 docs/同事接手指南-Windows.md 和 INDEX.md。

对话编排以当前代码为准：
- 入口：cloud/cloud_orchestrator/core/graph_native.py（LangGraph StateGraph）
- 用户回答：master.feed_answer → feed_graph_resume（必须对上 ask_id）→ interrupt resume
- 答非所问 / 放弃 / 换事 / 整句填表：core/dialogue/ 纯函数，不要只改提示词
- 办事字段权威在 LangGraph checkpoint（data/checkpoints.db），不是 conversations.json 的 forms/dialogue
- 禁止再引入：_answer_waiter、DialogueOrchestrator、direct_ask 双通道、ask_user_fn、_asked_norm

改对话行为先改 dialogue/ 和 graph_native；skill 契约仍看 plans/contract-v2-接口说明.md。
```

---

## 第 1 步：安装 Git 并配置换行符

Windows 默认会把换行符转成 `\r\n`，导致 Python 和 Shell 脚本出错。**必须先配置再克隆**。

### 1.1 安装 Git

如果还没装 Git，下载安装：https://git-scm.com/download/win

安装时一路默认即可。装好后打开 **PowerShell**（或 Git Bash），验证：

```powershell
git --version
```

能输出版本号即可。

### 1.2 配置换行符 + SSH 密钥

```powershell
# 换行符：checkout 时不转换，保持 LF
git config --global core.autocrlf input

# 如果还没配过 SSH 密钥（GitHub 需要），生成一个：
ssh-keygen -t ed25519 -C "你的邮箱"
# 一路回车，然后把公钥添加到 GitHub：
cat ~/.ssh/id_ed25519.pub
# 复制输出内容，到 https://github.com/settings/keys 添加 SSH key
```

### 1.3 克隆仓库

```powershell
# 建议放在纯英文路径下，避免中文路径兼容问题
cd D:\projects
git clone git@github.com:349878055-dotcom/black-box.git personal-assistant
cd personal-assistant
```

> **已经克隆了才看到这条？** 补救：
> ```powershell
> git config --global core.autocrlf input
> git rm --cached -r .
> git reset --hard
> ```

### 1.4 验证

```powershell
git status
# 应该显示 "On branch master" 且没有异常修改
```

---

## 第 2 步：搭建 Python 环境

### 2.1 安装 Python

下载 **Python 3.11 或 3.12**：https://www.python.org/downloads/

安装时 **务必勾选 "Add Python to PATH"**。

安装后验证：

```powershell
python --version
# 应输出 Python 3.11.x 或 3.12.x
pip --version
```

### 2.2 创建虚拟环境并安装依赖

```powershell
cd D:\projects\personal-assistant
python -m venv .venv
.venv\Scripts\activate
# 激活后命令行前面会出现 (.venv)

# 安装依赖（用清华镜像加速）
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

### 2.3 验证 Python 环境

```powershell
python -c "import fastapi; import langchain_openai; import langgraph; print('Python 依赖 OK')"
```

如果没报错，说明环境就绪。

---

## 第 3 步：放入配置文件（找金涛要）

以下文件含密钥，不在 Git 仓库里，需要找金涛单独拿：

| 文件 | 放到哪里 | 内容 |
|---|---|---|
| `config.json` | `cloud/config.json` | LLM 密钥（DeepSeek/通义千问）、JWT 密钥、博查搜索 key、skill 平台密钥 |

拿到后直接放到项目的 `cloud/` 目录下。

### 验证配置文件

```powershell
python -c "import json; d=json.load(open('cloud/config.json','r',encoding='utf-8')); print('config.json OK, keys:', list(d.keys()))"
```

应该输出类似：`config.json OK, keys: ['deepseek', 'qwen', 'auth', 'bocha', 'skills']`

---

## 第 4 步：本地启动云端服务（调试用）

正式环境已经部署在服务器上在跑了。本地调试代码时可以这样启动：

```powershell
cd D:\projects\personal-assistant
.venv\Scripts\activate
$env:PYTHONPATH = "."
python -m cloud.cloud_orchestrator.main
# 首次启动会自动创建 cloud/cloud_orchestrator/data/checkpoints.db（对话状态落盘，SqliteSaver）
```

### 验证

启动后应该看到类似输出：

```
INFO:     Uvicorn running on http://0.0.0.0:19000
```

浏览器访问 http://localhost:19000 能有响应即可。`Ctrl+C` 停止。

---

## 第 5 步：编译并安装 Android App

手机端 App 必须重新编译安装到你的手机上。

### 5.1 安装 JDK 17

下载 **JDK 17**（推荐 Eclipse Temurin）：https://adoptium.net/

安装后验证：

```powershell
java -version
# 应输出 openjdk version "17.x.x" 或更高
```

### 5.2 安装 Android Studio + SDK

下载 Android Studio：https://developer.android.com/studio

安装时勾选 Android SDK。装好后打开一次 Android Studio，让它下载完 SDK 组件。

默认 SDK 安装路径为：`C:\Users\<你的用户名>\AppData\Local\Android\Sdk`

### 5.3 配置 local.properties

在 `app\project\` 目录下新建文件 `local.properties`，写入（替换用户名）：

```properties
sdk.dir=C:\\Users\\你的用户名\\AppData\\Local\\Android\\Sdk
```

### 5.4 编译 APK

```powershell
cd D:\projects\personal-assistant\app\project
.\gradlew.bat :app:assembleDebug
```

首次编译会下载 Gradle 9.1.0 和 Android Gradle Plugin 8.5.2，可能需要几分钟。

> **下载卡住？** 在 PowerShell 中设置代理后重试：
> ```powershell
> $env:HTTPS_PROXY = "http://127.0.0.1:你的代理端口"
> .\gradlew.bat :app:assembleDebug
> ```

### 5.5 验证编译结果

```powershell
dir app\project\app\build\outputs\apk\debug\app-debug.apk
# 应该能看到这个文件，大小约几 MB
```

### 5.6 安装到手机

1. 手机开启 **开发者模式** → 打开 **USB 调试**
2. USB 连接电脑，手机上点"允许调试"
3. 安装：

```powershell
# 确保 adb 在 PATH 中（Android SDK 自带）
adb install app\project\app\build\outputs\apk\debug\app-debug.apk
```

或者直接用 Android Studio 打开 `app\project` 目录，点运行按钮。

---

## 第 6 步：完整验证检查清单

按顺序执行以下命令，全部通过即环境就绪：

```powershell
cd D:\projects\personal-assistant

# 1. Git 换行符
git config --global --get core.autocrlf
# 期望输出：input

# 2. Python 版本
python --version
# 期望输出：Python 3.11.x 或 3.12.x

# 3. 虚拟环境激活
.venv\Scripts\activate

# 4. Python 依赖
python -c "import fastapi; import langchain_openai; import langgraph; import langgraph.checkpoint.sqlite; import sentence_transformers; print('ALL DEPS OK')"
# 期望输出：ALL DEPS OK

# 5. 配置文件
python -c "import json; json.load(open('cloud/config.json','r',encoding='utf-8')); print('CONFIG OK')"
# 期望输出：CONFIG OK

# 6. 云端可启动（启动后 Ctrl+C 退出）
$env:PYTHONPATH = "."
python -m cloud.cloud_orchestrator.main
# 期望看到：Uvicorn running on http://0.0.0.0:19000

# 7. APK 已编译
dir app\project\app\build\outputs\apk\debug\app-debug.apk
# 期望：文件存在
```

---

## Windows 常见问题速查

| 症状 | 原因 | 解决 |
|---|---|---|
| Python/脚本报 `SyntaxError` 含 `\r` | 换行符没配对 | `git config --global core.autocrlf input` 然后 `git rm --cached -r . && git reset --hard` |
| `run.sh` 无法执行 | 这是 Linux 脚本 | Windows 上不用它，用第 4 步的 PowerShell 命令 |
| 端口 19000 被占 | 其他程序占了 | `netstat -ano | findstr 19000` 查占用；或 `$env:ORCH_PORT=19001` 换端口 |
| `gradlew.bat` 报找不到 JDK | JDK 没装或没加 PATH | 装 JDK 17 并确认 `java -version` 正常 |
| Gradle 下载超慢 | 网络问题 | 设代理 `$env:HTTPS_PROXY="http://127.0.0.1:端口"` |
| `pip install` 超慢 | PyPI 被墙 | 加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 路径含中文报错 | 某些工具不支持中文路径 | 项目放到纯英文路径如 `D:\projects\personal-assistant` |
| `adb` 命令找不到 | 没加 PATH | 把 `C:\Users\<用户名>\AppData\Local\Android\Sdk\platform-tools` 加到系统 PATH |

---

## 架构速览：对话编排（2026-08 已改 LangGraph 原生）

- **一条主链**：`master.submit` → `Agent.handle` → `graph_native.run_agent_graph`（LangGraph：route → model → tools / force_ask → wait_ask）。
- **用户回答不直接进 LLM**：`interrupt` 等人；回复经 `feed_answer`（核对 ask_id）→ `Command(resume)`，先过 `core/dialogue/resolve_reply`（零 LLM）：
  - `ABANDON`（「算了不买了」）→ 收尾、不写表单；
  - `REASK`（答非所问）→ 原问题再问（attempt 上限 3）；
  - `SET_SLOT`（校验通过 / 整句拆槽 / 改成后天）→ 写入图状态 `forms`；
  - `OFF_TOPIC_CHAT`（「几点了」）→ 短答 + 继续原问；
  - `NEW_INTENT`（「帮我点外卖」）→ 停掉当前提问，用原话重新走 route。
- **文字反问**：模型用纯文字问办事信息会被 correction / force_ask 改成真正的 `ask_user`，答案才能落盘。
- **状态落盘**：SqliteSaver → `cloud/cloud_orchestrator/data/checkpoints.db`（thread_id = 会话 ID）。
- **工具面按 phase 过滤**：`chat` 只有 search/done；`task` 才全量。
- **改对话行为先看 `core/dialogue/`**，不要只改提示词。

---

## 项目结构速览

```
personal-assistant/
├── cloud/                          # 云端 Python 服务
│   ├── cloud_orchestrator/
│   │   ├── main.py                 # 服务入口（FastAPI + Uvicorn）
│   │   ├── config.py               # 读取 cloud/config.json
│   │   ├── core/                   # Agent 引擎 + 对话编排（LangGraph 原生）
│   │   │   ├── graph_state.py      # 图状态 schema（phase/forms/locked_skill/pending_ask）
│   │   │   ├── graph_native.py     # StateGraph + interrupt/resume + checkpointer
│   │   │   ├── graph_tools.py      # 工具定义（按 phase 过滤工具面）
│   │   │   ├── graph_engine.py     # 薄入口（run_agent_graph / feed_graph_resume）
│   │   │   ├── dialogue/           # 对话护栏：resolve_reply / answer_check / route_entry / skill_lock / slots
│   │   │   ├── agent.py            # 工具执行（skill_run / search / done / 登录）
│   │   │   └── master.py           # 任务 + resume 唯一通道 + App 推送
│   │   ├── data/                   # 运行时数据（checkpoints.db 等）
│   │   ├── channel/                # WebSocket 会话管理
│   │   ├── store/archive_center/   # Skill 仓库（已接入的平台）
│   │   ├── retrieval/              # 向量检索（BGE 模型）
│   │   └── adapters/               # 工具适配器
│   └── config.json                 # ⚠️ 密钥配置，不入库
├── app/                            # Android 客户端
│   ├── project/                    # Gradle 工程根目录
│   │   ├── build.gradle.kts        # AGP 8.5.2
│   │   ├── app/build.gradle.kts    # compileSdk 35, minSdk 24, JDK 17
│   │   ├── gradle.properties       # JVM 参数
│   │   └── local.properties        # ⚠️ SDK 路径，不入库，自己创建
│   └── src/                        # 源码 + UI 资源
│       ├── core/                   # Java 源码 + AndroidManifest.xml
│       └── ui/                     # HTML/CSS/JS + drawable 资源
├── tools/                          # 对话规则单测
├── plans/                          # 契约接口 + LangGraph 架构说明
├── docs/                           # 文档
├── requirements.txt                # 云端 Python 依赖
├── INDEX.md                        # 按问题找文件的索引
└── README.md                       # 项目总览
```

详细文件索引见 `INDEX.md`，有问题找金涛。
